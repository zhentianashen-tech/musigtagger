"""Command line entry point: ``python -m musigtagger.app <command>``.

Commands mirror what the web UI does, so the whole workflow is scriptable and
the safety path can be exercised without a browser:

``serve``   — start the local review app (default 127.0.0.1:8765)
``scan``    — scan the library and persist suggestions
``status``  — counts of tracks, review states, batches
``apply``   — apply every accepted/edited suggestion (or selected tracks)
``retry``   — retry the remaining tracks of a failed apply batch
``undo``    — undo an apply batch, restoring the exact prior bytes
``history`` — show write batches and the event log tail
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .backup import BackupError
from .config import AppConfig, ProtectedPathError
from .factory import build_context
from .writer import NothingToApplyError, WriteError

DEFAULT_PORT = 8765


def _common_options(parser: argparse.ArgumentParser) -> None:
    # SUPPRESS keeps a value given before the subcommand from being overwritten
    # by the subparser's defaults.
    parser.add_argument(
        "--library-root", default=argparse.SUPPRESS, help="library directory to scan"
    )
    parser.add_argument(
        "--db", dest="database_path", default=argparse.SUPPRESS, help="SQLite index path"
    )
    parser.add_argument(
        "--backup-dir", dest="backup_root", default=argparse.SUPPRESS, help="backup root"
    )
    parser.add_argument(
        "--events", dest="events_path", default=argparse.SUPPRESS, help="JSONL event log"
    )
    parser.add_argument(
        "--taxonomy-dir", default=argparse.SUPPRESS, help="taxonomy data directory"
    )
    parser.add_argument(
        "--taxonomy-version",
        default=argparse.SUPPRESS,
        help="pinned taxonomy version (default 1.0.0)",
    )
    parser.add_argument(
        "--provider",
        dest="provider_spec",
        default=argparse.SUPPRESS,
        help="suggestion provider as 'module:Attribute' (comma-separate for several)",
    )
    parser.add_argument(
        "--scanner",
        dest="scanner_spec",
        default=argparse.SUPPRESS,
        help="scanner as 'module:Attribute' (default: bundled mutagen scanner)",
    )
    parser.add_argument(
        "--protect",
        dest="protected_roots",
        action="append",
        default=argparse.SUPPRESS,
        help="read-only source root that must never be written (repeatable)",
    )
    parser.add_argument(
        "--language", default=argparse.SUPPRESS, help="label language (e.g. en, zh)"
    )
    parser.add_argument(
        "--page-size", type=int, default=argparse.SUPPRESS, help="review UI page size"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="musigtagger-app",
        description="Music Tagger Phase 1 review app and safe tag-write path",
    )
    _common_options(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="start the local review web app")
    _common_options(serve)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)

    scan = subparsers.add_parser("scan", help="scan a library and record suggestions")
    _common_options(scan)
    scan.add_argument("--root", default=None, help="directory to scan (default library root)")

    status = subparsers.add_parser("status", help="show index and review counts")
    _common_options(status)

    apply_cmd = subparsers.add_parser("apply", help="apply reviewed tags")
    _common_options(apply_cmd)
    apply_cmd.add_argument(
        "--track-id", action="append", type=int, default=None, help="limit to a track id"
    )

    retry = subparsers.add_parser("retry", help="retry a failed apply batch")
    _common_options(retry)
    retry.add_argument("--batch", type=int, required=True)

    undo = subparsers.add_parser("undo", help="undo an apply batch")
    _common_options(undo)
    undo.add_argument("--batch", type=int, required=True)

    history = subparsers.add_parser("history", help="show batches and event log")
    _common_options(history)
    history.add_argument("--limit", type=int, default=20)

    return parser


def _args_to_mapping(args: argparse.Namespace) -> dict[str, object]:
    values: dict[str, object] = {}
    for name in (
        "library_root",
        "database_path",
        "backup_root",
        "events_path",
        "taxonomy_dir",
        "taxonomy_version",
        "provider_spec",
        "scanner_spec",
        "language",
    ):
        value = getattr(args, name, None)
        if value is not None:
            values[name] = value
    if getattr(args, "page_size", None) is not None:
        values["page_size"] = args.page_size
    protected = getattr(args, "protected_roots", None)
    if protected is not None:
        values["protected_roots"] = protected
    return values


def build_config(args: argparse.Namespace) -> AppConfig:
    return AppConfig.from_mapping(_args_to_mapping(args), base=Path.cwd())


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = build_config(args)
    except Exception as exc:  # noqa: BLE001 - configuration errors are user-facing
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if args.command == "serve":
        from .webapp import make_server

        context = build_context(config)
        server = make_server(context, args.host, args.port)
        host, port = server.server_address[:2]
        print(f"Music Tagger review app: http://{host}:{port}/")
        print(f"library: {config.library_root}")
        print(f"database: {config.database_path}")
        print(f"backups: {config.backup_root}")
        print("Ctrl-C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopping")
        finally:
            server.server_close()
            context.close()
        return 0

    try:
        context = build_context(config)
    except Exception as exc:  # noqa: BLE001 - startup errors are user-facing
        print(f"cannot open the library: {exc}", file=sys.stderr)
        return 1

    try:
        if args.command == "scan":
            report = context.ingestion.scan(args.root)
            print(
                f"scan {report.root}: {report.indexed} indexed, "
                f"{report.skipped_count} skipped, "
                f"{report.suggestions_new} new suggestion(s), "
                f"{report.suggestions_duplicate} duplicate(s)"
            )
            if not report.providers:
                print(
                    "warning: no --provider configured, so no suggestions were "
                    "produced; the review queue will be empty",
                    file=sys.stderr,
                )
            for skipped in report.skipped[:20]:
                print(f"  skipped {skipped.path}: {skipped.reason}")
            if len(report.skipped) > 20:
                print(f"  ... {len(report.skipped) - 20} more skipped")
            return 0

        if args.command == "status":
            counts = context.store.review_counts()
            totals = context.store.counts()
            print(f"tracks: {totals['tracks']}")
            for state in ("suggested", "accepted", "edited", "rejected", "applied"):
                print(f"{state}: {counts[state]}")
            print(f"batches: {totals['batches']}")
            return 0

        if args.command == "apply":
            result = context.writer.apply(track_ids=args.track_id)
            print(
                f"batch {result.batch_id} {result.status}: "
                f"{result.succeeded}/{result.track_count} track(s) written"
            )
            for outcome in result.outcomes:
                if not outcome.ok:
                    print(f"  failed {outcome.path}: {outcome.error}")
            return 0 if result.status == "completed" else 1

        if args.command == "retry":
            result = context.writer.retry(args.batch)
            print(
                f"batch {result.batch_id} {result.status}: "
                f"{result.succeeded}/{result.track_count} track(s) written"
            )
            for outcome in result.outcomes:
                if not outcome.ok:
                    print(f"  failed {outcome.path}: {outcome.error}")
            return 0 if result.status == "completed" else 1

        if args.command == "undo":
            result = context.writer.undo(args.batch)
            print(
                f"undo batch {result.batch_id} {result.status}: "
                f"{result.succeeded}/{result.track_count} track(s) restored"
            )
            for outcome in result.outcomes:
                if not outcome.ok:
                    print(f"  failed {outcome.path}: {outcome.error}")
            return 0 if result.status == "completed" else 1

        if args.command == "history":
            from .events import read_events

            for batch in context.store.list_batches(limit=args.limit):
                print(
                    f"batch {batch['id']}: {batch['kind']} {batch['status']} "
                    f"{batch['track_count']} track(s) at {batch['created_at']}"
                )
            print("\nevents (tail):")
            for event in read_events(config.events_path, limit=args.limit):
                print(
                    f"  {event.get('occurred_at', '')} {event.get('event', '')} "
                    f"{event.get('track_path') or (event.get('track') or {}).get('path', '')}"
                )
            return 0
    except (WriteError, NothingToApplyError, BackupError, ProtectedPathError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        context.close()
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
