"""The minimal local web app: routes, request handling, and the HTTP server.

Design constraints (operator's decisions, binding):

* **Local only.** The server binds ``127.0.0.1`` by default and pulls no external
  resource: the pages are self-contained HTML with inline CSS, no JavaScript, no
  fonts, no CDN. The app runs with the network unplugged.
* **Batch first.** Accept/reject act on every track matching the current filter
  (100s of tracks), and apply/undo are single batch operations.
* **No polish requirement.** Plain forms, one shared design, no framework.

The routing layer is separated from the socket layer so tests can exercise the
whole app through :meth:`WebApp.handle_get` / :meth:`WebApp.handle_post` without
starting a server, and a live-server test covers the HTTP plumbing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import parse_qs, urlencode, urlparse

from . import render
from .factory import AppContext
from .review import ReviewError
from .store import REVIEW_STATES
from .writer import NothingToApplyError, WriteError

STATUS_FILTERS = (*REVIEW_STATES, "all")


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def html_response(body: str, status: int = 200) -> Response:
    return Response(
        status=status,
        body=body.encode("utf-8"),
        headers={"Content-Type": "text/html; charset=utf-8"},
    )


def redirect(location: str) -> Response:
    return Response(
        status=303, body=b"", headers={"Location": location}
    )


def _first(values: Mapping[str, Sequence[str]], key: str, default: str | None = None):
    found = values.get(key)
    if not found:
        return default
    return found[0]


def _all(values: Mapping[str, Sequence[str]], key: str) -> list[str]:
    return list(values.get(key, []))


class WebApp:
    """Routes for the review UI, independent of the HTTP server."""

    def __init__(self, context: AppContext) -> None:
        self.context = context

    # -- GET -------------------------------------------------------------

    def handle_get(
        self, path: str, query: Mapping[str, Sequence[str]]
    ) -> Response:
        if path in ("/", "/review"):
            return self._queue_page(query)
        if path == "/history":
            return self._history_page(query)
        if path == "/health":
            return Response(status=200, body=b"ok")
        return html_response("<h1>Not found</h1>", status=404)

    def _filters(self, query: Mapping[str, Sequence[str]]) -> dict[str, object]:
        status = _first(query, "status", "suggested") or "suggested"
        if status not in STATUS_FILTERS:
            status = "suggested"
        facet = _first(query, "facet") or None
        query_text = _first(query, "q") or None
        min_confidence: float | None = None
        raw = _first(query, "min_confidence")
        if raw:
            try:
                min_confidence = max(0.0, min(1.0, float(raw)))
            except ValueError:
                min_confidence = None
        return {
            "status": status,
            "facet": facet,
            "q": query_text,
            "min_confidence": min_confidence,
        }

    def _statuses_for_filter(self, status: str) -> tuple[str, ...]:
        if status == "all":
            return REVIEW_STATES
        return (status,)

    def _queue_page(self, query: Mapping[str, Sequence[str]]) -> Response:
        context = self.context
        filters = self._filters(query)
        statuses = self._statuses_for_filter(str(filters["status"]))
        try:
            page = max(1, int(_first(query, "page", "1") or "1"))
        except ValueError:
            page = 1
        tracks, total = context.store.queue_track_page(
            statuses=statuses,
            facet=filters["facet"],  # type: ignore[arg-type]
            min_confidence=filters["min_confidence"],  # type: ignore[arg-type]
            query=filters["q"],  # type: ignore[arg-type]
            limit=context.config.page_size,
            offset=(page - 1) * context.config.page_size,
        )
        track_ids = [int(track["id"]) for track in tracks]
        rows = context.store.suggestions_for_tracks(track_ids, statuses=statuses)
        by_track: dict[int, list[sqlite3.Row]] = {}
        for row in rows:
            by_track.setdefault(int(row["track_id"]), []).append(row)
        counts = self._counts()
        writable = counts["accepted"] + counts["edited"]
        notice = _first(query, "notice")
        error = _first(query, "error")
        body = render.queue_page(
            config=context.config,
            taxonomy=context.taxonomy,
            counts=counts,
            tracks=tracks,
            suggestions_by_track=by_track,
            total=total,
            page=page,
            filters=filters,
            writable_count=writable,
            notice=notice,
            error=error,
        )
        return html_response(body)

    def _history_page(self, query: Mapping[str, Sequence[str]]) -> Response:
        context = self.context
        batches = context.store.list_batches(limit=50)
        details = {
            int(batch["id"]): context.store.list_backups(int(batch["id"]))
            for batch in batches
        }
        from .events import read_events

        events = read_events(context.config.events_path, limit=50)
        counts = self._counts()
        body = render.history_page(
            batches=batches,
            batch_details=details,
            events=events,
            counts=counts,
            applied_count=counts["applied"],
            notice=_first(query, "notice"),
            error=_first(query, "error"),
        )
        return html_response(body)

    def _counts(self) -> dict[str, int]:
        counts = self.context.store.review_counts()
        return counts

    # -- POST ------------------------------------------------------------

    def handle_post(
        self, path: str, form: Mapping[str, Sequence[str]]
    ) -> Response:
        try:
            if path == "/review":
                return self._post_review(form)
            if path == "/batch":
                return self._post_batch(form)
            if path == "/apply":
                return self._post_apply(form)
            if path == "/undo":
                return self._post_undo(form)
            if path == "/scan":
                return self._post_scan(form)
        except (ReviewError, WriteError) as exc:
            return self._back(error=str(exc))
        except Exception as exc:  # noqa: BLE001 - surface, never crash the server
            return self._back(error=f"{type(exc).__name__}: {exc}")
        return html_response("<h1>Not found</h1>", status=404)

    def _post_review(self, form: Mapping[str, Sequence[str]]) -> Response:
        raw_id = _first(form, "id")
        action = _first(form, "action", "accept")
        if not raw_id:
            raise ReviewError("missing suggestion id")
        suggestion_id = int(raw_id)
        if action == "accept":
            self.context.review.accept(suggestion_id)
            message = f"Accepted suggestion {suggestion_id}."
        elif action == "reject":
            self.context.review.reject(suggestion_id)
            message = f"Rejected suggestion {suggestion_id}."
        elif action == "edit":
            tag_id = _first(form, "tag_id")
            if not tag_id:
                raise ReviewError("choose a tag to save an edit")
            self.context.review.edit(suggestion_id, tag_id)
            message = f"Saved edit for suggestion {suggestion_id}."
        else:
            raise ReviewError(f"unknown review action {action!r}")
        return self._back(notice=message)

    def _post_batch(self, form: Mapping[str, Sequence[str]]) -> Response:
        action = _first(form, "action", "accept")
        if action not in ("accept", "reject"):
            raise ReviewError(f"unknown batch action {action!r}")
        track_ids = [int(value) for value in _all(form, "track_ids") if value]
        min_confidence: float | None = None
        raw = _first(form, "min_confidence")
        if raw:
            try:
                min_confidence = max(0.0, min(1.0, float(raw)))
            except ValueError:
                min_confidence = None
        if not track_ids:
            status = _first(form, "status", "suggested") or "suggested"
            track_ids = self.context.store.queue_track_ids(
                statuses=("suggested",) if status == "suggested" else REVIEW_STATES,
                facet=_first(form, "facet") or None,
                min_confidence=min_confidence,
                query=_first(form, "q") or None,
            )
        if not track_ids:
            raise ReviewError("no suggestions match that batch selection")
        if action == "accept":
            changed = self.context.review.batch_accept(
                track_ids=track_ids, min_confidence=min_confidence
            )
            message = f"Accepted {changed} suggestion(s) across {len(track_ids)} track(s)."
        else:
            changed = self.context.review.batch_reject(
                track_ids=track_ids, min_confidence=min_confidence
            )
            message = f"Rejected {changed} suggestion(s) across {len(track_ids)} track(s)."
        return self._back(notice=message)

    def _post_apply(self, form: Mapping[str, Sequence[str]]) -> Response:
        track_ids = [int(value) for value in _all(form, "track_ids") if value]
        result = self.context.writer.apply(
            track_ids=track_ids or None
        )
        message = (
            f"Batch {result.batch_id} {result.status}: "
            f"{result.succeeded}/{result.track_count} track(s) written."
        )
        if result.failures:
            first = result.failures[0]
            message += (
                f" {len(result.failures)} failed; first: {Path(first.path).name} — "
                f"{first.error}. Backups were kept; see History to retry or undo."
            )
        return self._back(notice=message)

    def _post_undo(self, form: Mapping[str, Sequence[str]]) -> Response:
        raw = _first(form, "batch_id")
        if not raw:
            raise WriteError("missing batch id")
        result = self.context.writer.undo(int(raw))
        message = (
            f"Undo batch {result.batch_id} {result.status}: "
            f"{result.succeeded}/{result.track_count} track(s) restored."
        )
        if result.failures:
            message += (
                f" {len(result.failures)} failed; first: "
                f"{result.failures[0].error}"
            )
        return self._back(notice=message)

    def _post_scan(self, form: Mapping[str, Sequence[str]]) -> Response:
        root = _first(form, "root") or None
        report = self.context.ingestion.scan(root)
        message = (
            f"Scanned {report.root}: {report.indexed} track(s) indexed, "
            f"{report.skipped_count} skipped, "
            f"{report.suggestions_new} new suggestion(s) "
            f"({report.suggestions_duplicate} duplicate)."
        )
        if report.skipped:
            reasons = "; ".join(
                f"{Path(item.path).name}: {item.reason}"
                for item in report.skipped[:3]
            )
            message += f" First skips — {reasons}"
        return self._back(notice=message)

    def _back(self, *, notice: str | None = None, error: str | None = None) -> Response:
        parameters: dict[str, str] = {}
        if notice:
            parameters["notice"] = notice
        if error:
            parameters["error"] = error
        suffix = urlencode(parameters)
        return redirect(f"/?{suffix}" if suffix else "/")

    # -- helpers for tests -------------------------------------------------

    def queue_html(self, query: Mapping[str, Sequence[str]] | None = None) -> str:
        return self._queue_page(query or {}).text

    def history_html(self) -> str:
        return self._history_page({}).text


class RequestHandler(BaseHTTPRequestHandler):
    """Thin HTTP adapter over :class:`WebApp`."""

    server_version = "MusicTagger/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> WebApp:
        return self.server.app  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        response = self.app.handle_get(parsed.path, parse_qs(parsed.query))
        self._write(response)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""
        form = parse_qs(raw.decode("utf-8", errors="replace"))
        response = self.app.handle_post(parsed.path, form)
        self._write(response)

    def _write(self, response: Response) -> None:
        self.send_response(response.status)
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        if response.body:
            self.wfile.write(response.body)

    def log_message(self, format: str, *args: object) -> None:
        # The app is single-user and local; console noise is not useful.
        return


class ApplicationServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, app: WebApp) -> None:
        super().__init__(address, RequestHandler)
        self.app = app


def make_server(
    context: AppContext, host: str = "127.0.0.1", port: int = 0
) -> ApplicationServer:
    server = ApplicationServer((host, port), WebApp(context))
    return server
