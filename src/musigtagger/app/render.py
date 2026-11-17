"""Server-rendered HTML for the local review app (no JavaScript, no assets).

The UI is deliberately plain: forms and links only, everything on localhost, no
external resource that could require network access. It is optimised for the
operator's real workflow — a batch of 100s of tracks, low-effort review — by
putting the high-leverage actions (accept/reject a whole filtered batch, accept
one track's suggestions at once) above the per-suggestion controls.
"""

from __future__ import annotations

import html
import json
import math
import sqlite3
from typing import Mapping, Sequence

from .config import AppConfig
from .taxonomy_service import TaxonomyService

_ = html.escape


def _e(value: object) -> str:
    return _(str(value), quote=True)


CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       margin: 0; color: #1d1d1f; background: #f5f5f7; }
header { background: #fff; border-bottom: 1px solid #d2d2d7; padding: 14px 22px;
         display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap; }
header h1 { font-size: 18px; margin: 0; }
header nav a { margin-right: 14px; color: #0066cc; text-decoration: none; }
main { padding: 20px 22px 80px; max-width: 1100px; }
.panel { background: #fff; border: 1px solid #d2d2d7; border-radius: 8px;
         padding: 14px 16px; margin-bottom: 16px; }
.panel h2 { font-size: 15px; margin: 0 0 10px; }
.notice { background: #e8f5e9; border: 1px solid #a5d6a7; padding: 10px 12px;
          border-radius: 6px; margin-bottom: 14px; }
.error { background: #fdecea; border: 1px solid #f5a3a0; padding: 10px 12px;
         border-radius: 6px; margin-bottom: 14px; white-space: pre-wrap; }
.counts span { margin-right: 12px; color: #515154; }
.muted { color: #6e6e73; font-size: 13px; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #ececef;
         vertical-align: top; }
th { font-size: 12px; text-transform: uppercase; color: #6e6e73; letter-spacing: .03em; }
.track { background: #fff; border: 1px solid #d2d2d7; border-radius: 8px;
         padding: 12px 16px; margin-bottom: 14px; }
.track h3 { font-size: 14px; margin: 0 0 2px; }
.track .path { font-size: 12px; color: #6e6e73; word-break: break-all; }
.badge { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 10px;
         background: #ececef; color: #333; margin-left: 6px; }
.badge.suggested { background: #e3f2fd; }
.badge.accepted { background: #e8f5e9; }
.badge.edited { background: #fff8e1; }
.badge.rejected { background: #fdecea; }
.badge.applied { background: #ede7f6; }
form.inline { display: inline-flex; gap: 6px; align-items: center; margin: 0 6px 6px 0; }
button { font: inherit; padding: 4px 10px; border-radius: 6px; border: 1px solid #b9b9c0;
         background: #fff; cursor: pointer; }
button.primary { background: #0066cc; color: #fff; border-color: #0066cc; }
button.danger { color: #b3261e; border-color: #e3a9a5; }
select, input[type=text], input[type=number] { font: inherit; padding: 4px 6px;
         border: 1px solid #b9b9c0; border-radius: 6px; background: #fff; }
.filters { display: flex; gap: 10px; flex-wrap: wrap; align-items: end; }
.filters label { display: flex; flex-direction: column; font-size: 12px; color: #6e6e73; }
.batch { display: flex; gap: 10px; flex-wrap: wrap; align-items: end; }
.pager a { margin-right: 10px; color: #0066cc; }
pre { background: #f5f5f7; padding: 8px; border-radius: 6px; overflow-x: auto;
      font-size: 12px; margin: 4px 0; }
.stat { font-weight: 600; }
"""


def layout(
    *,
    title: str,
    body: str,
    counts: Mapping[str, int] | None = None,
    notice: str | None = None,
    error: str | None = None,
) -> str:
    counts_html = ""
    if counts:
        counts_html = (
            '<div class="counts">'
            + "".join(
                f"<span>{_e(key)}: <b>{_e(value)}</b></span>"
                for key, value in counts.items()
            )
            + "</div>"
        )
    banners = ""
    if notice:
        banners += f'<div class="notice">{_e(notice)}</div>'
    if error:
        banners += f'<div class="error">{_e(error)}</div>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)} · Music Tagger</title>
<style>{CSS}</style></head>
<body>
<header>
  <h1>Music Tagger</h1>
  <nav><a href="/">Review</a><a href="/history">History</a></nav>
  {counts_html}
</header>
<main>
{banners}
{body}
</main>
</body></html>"""


def _hidden(name: str, value: object) -> str:
    return (
        f'<input type="hidden" name="{_e(name)}" value="{_e(value)}">'
    )


def _filter_hidden(filters: Mapping[str, object]) -> str:
    return "".join(
        _hidden(key, value)
        for key, value in filters.items()
        if value not in (None, "")
    )


def _tag_label(taxonomy: TaxonomyService, tag_id: str, language: str) -> str:
    try:
        return taxonomy.tag(tag_id).display_label(language)
    except Exception:  # noqa: BLE001 - never let a bad id break the page
        return tag_id


def _status_badge(status: str) -> str:
    return f'<span class="badge {_e(status)}">{_e(status)}</span>'


def _pager(
    *, page: int, page_size: int, total: int, filters: Mapping[str, object]
) -> str:
    pages = max(1, math.ceil(total / page_size)) if total else 1
    params = "&".join(
        f"{_e(key)}={_e(value)}" for key, value in filters.items() if value not in (None, "")
    )
    base = f"/?{params}&" if params else "/?"
    links = []
    if page > 1:
        links.append(f'<a href="{base}page={page - 1}">← previous</a>')
    links.append(f"<span class=\"muted\">page {page} of {pages}</span>")
    if page < pages:
        links.append(f'<a href="{base}page={page + 1}">next →</a>')
    return '<div class="pager">' + " ".join(links) + "</div>"


def queue_page(
    *,
    config: AppConfig,
    taxonomy: TaxonomyService,
    counts: Mapping[str, int],
    tracks: Sequence[sqlite3.Row],
    suggestions_by_track: Mapping[int, Sequence[sqlite3.Row]],
    total: int,
    page: int,
    filters: Mapping[str, object],
    writable_count: int,
    notice: str | None = None,
    error: str | None = None,
    scanned: Sequence[str] = (),
) -> str:
    language = config.language
    statuses = ["suggested", "accepted", "edited", "rejected", "applied"]
    facet_choices = [
        f'<option value="{_e(facet)}"{" selected" if filters.get("facet") == facet else ""}>'
        f"{_e(taxonomy.taxonomy.facet(facet).label)}</option>"
        for facet in taxonomy.taxonomy.facet_ids
    ]
    filter_form = f"""
<div class="panel">
<form class="filters" method="get" action="/">
  <label>Status<select name="status">
    {''.join(f'<option value="{_e(s)}"{" selected" if filters.get("status") == s else ""}>{_e(s)}</option>' for s in statuses)}
  </select></label>
  <label>Facet<select name="facet"><option value="">any</option>
    {''.join(facet_choices)}
  </select></label>
  <label>Min confidence<input type="number" name="min_confidence" step="0.05" min="0" max="1" value="{_e(filters.get('min_confidence') or '')}"></label>
  <label>Search<input type="text" name="q" value="{_e(filters.get('q') or '')}" placeholder="path, title, artist"></label>
  <button class="primary" type="submit">Filter</button>
</form>
</div>"""

    scan_panel = f"""
<div class="panel">
<h2>Library</h2>
<form class="inline" method="post" action="/scan">
  <input type="text" name="root" value="{_e(config.library_root)}" size="60">
  <button class="primary" type="submit">Scan &amp; suggest</button>
</form>
<span class="muted">Read-only scan; nothing is written to audio files.</span>
{''.join(f'<div class="muted">{_e(line)}</div>' for line in scanned)}
</div>"""

    apply_panel = f"""
<div class="panel">
<h2>Write back</h2>
<form class="inline" method="post" action="/apply">
  <button class="primary" type="submit" {'disabled' if writable_count == 0 else ''}>Apply all reviewed tags ({writable_count})</button>
</form>
<span class="muted">Every apply is preceded by a verified backup of each file; undo restores it byte-for-byte.</span>
</div>"""

    batch_panel = ""
    if filters.get("status") == "suggested":
        batch_panel = f"""
<div class="panel">
<h2>Batch review</h2>
<form class="batch" method="post" action="/batch">
  {_filter_hidden({'status': filters.get('status'), 'facet': filters.get('facet'), 'q': filters.get('q')})}
  <label>Min confidence<input type="number" name="min_confidence" step="0.05" min="0" max="1" value="{_e(filters.get('min_confidence') or '')}"></label>
  <button class="primary" name="action" value="accept" type="submit">Accept all {total} matching track(s)</button>
  <button name="action" value="reject" type="submit" formnovalidate>Reject all matching</button>
  <span class="muted">Applies to every match in the filter, not just this page.</span>
</form>
</div>"""

    track_blocks: list[str] = []
    for track in tracks:
        track_id = int(track["id"])
        rows = suggestions_by_track.get(track_id, ())
        title = track["title"] or ""
        artist = track["artist"] or ""
        heading = " — ".join(part for part in (artist, title) if part) or "(untitled)"
        facet_buttons = []
        for row in rows:
            facet = row["tag_id"].split(".", 1)[0]
            current = row["final_tag_id"] or row["tag_id"]
            label = _tag_label(taxonomy, str(current), language)
            confidence = float(row["confidence"])
            evidence = row["evidence"]
            status = str(row["status"])
            actions: list[str] = []
            if status == "suggested":
                actions.append(
                    f'<form class="inline" method="post" action="/review">'
                    f'{_hidden("id", row["id"])}'
                    f'<button class="primary" name="action" value="accept" type="submit">Accept</button>'
                    f'<button class="danger" name="action" value="reject" type="submit">Reject</button>'
                    f"</form>"
                )
            if status in ("suggested", "accepted", "edited", "rejected"):
                options = "".join(
                    f'<option value="{_e(choice["id"])}"'
                    f'{" selected" if choice["id"] == current else ""}>{_e(choice["label"])}</option>'
                    for choice in taxonomy.facet_tags(facet, language)
                )
                actions.append(
                    f'<form class="inline" method="post" action="/review">'
                    f'{_hidden("id", row["id"])}'
                    f'<select name="tag_id">{options}</select>'
                    f'<button name="action" value="edit" type="submit">Save edit</button>'
                    f"</form>"
                )
            facets = "".join(
                f'<tr><td><span class="muted">{_e(facet)}</span>'
                f'{_status_badge(status)}</td>'
                f"<td>{_e(label)}<div class=\"muted\">conf {confidence:.2f} · {_e(row['source'])}</div>"
                f'<div class="muted">{_e(evidence)}</div></td>'
                f"<td>{''.join(actions)}</td></tr>"
            )
            facet_buttons.append(facets)
        single_track_forms = ""
        if any(str(row["status"]) == "suggested" for row in rows):
            single_track_forms = (
                f'<form class="inline" method="post" action="/batch">'
                f'{_hidden("track_ids", track_id)}'
                f'{_hidden("status", "suggested")}'
                f'<button class="primary" name="action" value="accept" type="submit">'
                f"Accept all for this track</button>"
                f'<button name="action" value="reject" type="submit">Reject all for this track</button>'
                f"</form>"
            )
        track_blocks.append(
            f'<div class="track"><h3>{_e(heading)}</h3>'
            f'<div class="path">{_e(track["path"])}</div>'
            f"{single_track_forms}"
            f'<table><thead><tr><th>Facet</th><th>Tag</th><th>Decision</th></tr></thead>'
            f"<tbody>{''.join(facet_buttons)}</tbody></table></div>"
        )

    if not track_blocks:
        track_blocks.append(
            '<div class="panel"><p>No suggestions match these filters.</p>'
            '<p class="muted">Run a scan above, or widen the filters.</p></div>'
        )

    body = f"""
{scan_panel}
{apply_panel}
{filter_form}
{batch_panel}
{''.join(track_blocks)}
{_pager(page=page, page_size=config.page_size, total=total, filters=filters)}
<p class="muted">{total} track(s) match the filter{'' if total == 1 else 's'}.</p>
"""
    return layout(
        title="Review", body=body, counts=counts, notice=notice, error=error
    )


def history_page(
    *,
    batches: Sequence[sqlite3.Row],
    batch_details: Mapping[int, Sequence[sqlite3.Row]],
    events: Sequence[ Mapping[str, object]],
    counts: Mapping[str, int],
    applied_count: int,
    notice: str | None = None,
    error: str | None = None,
) -> str:
    rows: list[str] = []
    for batch in batches:
        batch_id = int(batch["id"])
        note = batch["note"] or ""
        detail = batch_details.get(batch_id, ())
        actions = ""
        if (
            batch["kind"] == "apply"
            and batch["status"] in ("completed", "failed")
        ):
            actions = (
                f'<form class="inline" method="post" action="/undo">'
                f'{_hidden("batch_id", batch_id)}'
                f'<button class="danger" type="submit">Undo batch</button></form>'
            )
        detail_rows = "".join(
            f"<tr><td>{_e(row['track_id'])}</td>"
            f"<td>{_e(_backup_summary(row))}</td>"
            f"<td>{_e(row['restored_at'] or '—')}</td></tr>"
            for row in detail
        )
        detail_html = (
            f'<details><summary class="muted">{len(detail)} backup(s)</summary>'
            f"<table><thead><tr><th>Track</th><th>Backup</th><th>Restored</th></tr></thead>"
            f"<tbody>{detail_rows}</tbody></table></details>"
            if detail
            else ""
        )
        rows.append(
            f"<tr><td>{batch_id}</td><td>{_e(batch['kind'])}</td>"
            f"<td>{_e(batch['status'])}</td><td>{_e(batch['track_count'])}</td>"
            f"<td>{_e(batch['taxonomy_version'])}</td>"
            f"<td>{_e(batch['created_at'])}</td><td>{actions}</td></tr>"
            f'<tr><td colspan="7"><div class="muted">{_e(note[:400])}</div>{detail_html}</td></tr>'
        )
    batches_html = (
        "<table><thead><tr><th>#</th><th>Kind</th><th>Status</th><th>Tracks</th>"
        "<th>Taxonomy</th><th>Created</th><th></th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        if rows
        else '<p class="muted">No write batches yet.</p>'
    )
    event_rows = "".join(
        f"<tr><td>{_e(event.get('occurred_at', ''))}</td>"
        f"<td>{_e(event.get('event', ''))}</td>"
        f"<td>{_e(event.get('track_path') or (event.get('track') or {}).get('path', ''))}</td>"
        f"<td>{_e(event.get('to_status') or event.get('tag_id') or '')}</td>"
        f"<td>{_e(event.get('final_tag_id') or event.get('source') or '')}</td></tr>"
        for event in events
    )
    body = f"""
<div class="panel">
<h2>Applied tags</h2>
<p>{applied_count} suggestion(s) currently applied.
<a href="/">Back to review</a></p>
</div>
<div class="panel"><h2>Write batches</h2>
<p class="muted">Each batch backed up every target file before writing. An undo restores the backup exactly.</p>
{batches_html}
</div>
<div class="panel"><h2>History log (CONTRACTS.md §4 events)</h2>
<p class="muted">Append-only local JSONL. This is the product's tagging history and the evaluation harness's input.</p>
<table><thead><tr><th>When</th><th>Event</th><th>Track</th><th>Tag/state</th><th>Final/source</th></tr></thead>
<tbody>{event_rows}</tbody></table>
</div>
"""
    return layout(title="History", body=body, counts=counts, notice=notice, error=error)


def _backup_summary(row: sqlite3.Row) -> str:
    try:
        payload = json.loads(row["prior_tags_json"])
    except Exception:  # noqa: BLE001 - display only
        return "unreadable backup record"
    return (
        f"{payload.get('format')} · {payload.get('size_bytes')} bytes · "
        f"sha256 {str(payload.get('sha256'))[:12]}…"
    )
