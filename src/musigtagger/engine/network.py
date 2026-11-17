"""Minimal network release-date lookup provider (MusicBrainz).

The only network capability in Phase 1 (operator-approved, MUSI-14). It
resolves an album + artist pair to the release group's *first* release year
via the open MusicBrainz web service and proposes the matching taxonomy
``era.<decade>s`` tag through the same mapping the local metadata provider
uses.

Matching strategy (fixed after the v0.2 era-recall defect, MUSI-14
reopened 2026-11-17): a *two-stage* release-group lookup.

1. Stage 1 — precise: ``releasegroup:"<album>" AND artist:"<artist>"``.
   Exact-for-artist libraries resolve here with no suspicion.
2. Stage 2 — album-only fallback (runs only when stage 1 matches nothing):
   ``releasegroup:"<album>"`` with the edition suffix stripped. This is what
   makes various-artists soundtracks resolvable: a cast-credited release
   group shares no token with a per-track artist such as ``TWICE``, so the
   artist AND-term eliminated every result. Stage 2 requires a strong album
   title match; when the query artist is not credited on the matched group
   the suggestion is still proposed but **FLAGGED** in the evidence — never
   silently accepted — so the reviewer decides (standing guidance, MUSI-14
   2026-11-17).

Edition suffixes such as `` / Deluxe Version`` are stripped from the album
query term; they never match a release-group title.

Failure behaviour (CONTRACTS §3.6): network unavailable, timeout, rate
limit, or no match are all honest abstentions. Transport failures raise
:class:`NetworkLookupError` so the caller (``SuggestionRunner``) logs the
skip and continues the batch; the provider itself never blocks forever
(every HTTP call carries a timeout) and never aborts a batch. Transient
HTTP failures (429/5xx) are retried a bounded number of times with paced
backoff; connection-level failures fail fast and are retried on the *next*
run. Offline runs degrade to exactly the pre-MUSI-14 behaviour when the
provider is simply not constructed.

Privacy/locality: network requests carry only the album and artist query
strings plus a User-Agent identifying this application — no personal data,
no file contents, no telemetry, no paths. Results are cached only in the
local SQLite library database (``release_date_cache``, schema migration
v2), so a 47-instance library makes ~14 network queries, not 47.

Contract note: CONTRACTS.md §2 describes ``suggest`` as free of I/O. The
leader approved, via MUSI-14, that *this* provider reads and writes its own
cache table inside ``suggest`` (the cache is injected through the
constructor, never opens audio files, and touches no v1 table). The
``suggest`` signature itself is unchanged, so this remains an additive
implementation behind the same seam.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from musigtagger.contracts import (
    SuggestionProvider,
    TagSuggestion,
    Taxonomy,
    TrackDescriptor,
)

from .metadata import PINNED_TAXONOMY_VERSION, _normalise as normalise_text

LOGGER = logging.getLogger(__name__)

#: Proposed confidence for a MusicBrainz-resolved era. Deliberately below the
#: embedded-metadata year (0.98) and above every filename/path/text-derived
#: era signal (0.65 and below). *A proposal for evaluation tuning*, not a
#: settled threshold (MUSI-14).
NETWORK_YEAR_CONFIDENCE = 0.85

SOURCE = "network.musicbrainz"

#: Semantic version of the lookup *query*. Bump whenever the query
#: construction, matching rule, or edition-stripping changes in a way that
#: could change results: cache rows written under an older query version are
#: ignored (never trusted), so a fixed query actually re-runs instead of
#: being masked by stale rows — the exact failure the v0.2 era-recall defect
#: exposed (16 cached ``found=false`` rows hid the bug). History:
#: 1 = original single-stage query; 2 = two-stage query + edition stripping
#: (MUSI-14 defect fix, 2026-11-17).
QUERY_VERSION: Final[int] = 2

#: MusicBrainz asks anonymous clients to stay at ~1 request per second. The
#: 1.1 s spacing (enforced across retries *and* pairs) leaves margin so a
#: burst never tips over the documented limit — the v0.2 baseline measured
#: 503 storms at exactly 1.0 s.
DEFAULT_MIN_QUERY_INTERVAL_SECONDS = 1.1
DEFAULT_TIMEOUT_SECONDS = 5.0
_DEFAULT_SEARCH_LIMIT = 10

#: Bounded retry budget for *transient* HTTP failures (429/5xx). The live
#: search endpoint 503s on roughly a third of paced requests (measured on
#: the v0.2 rerun and the MUSI-14 fix verification), so a 3-attempt budget
#: still lost pairs; 5 paced attempts (linear backoff) converge within one
#: run. Connection-level failures are not retried here; they fail fast and
#: are retried on the next run (failures are retried, never silently
#: dropped).
_DEFAULT_MAX_ATTEMPTS = 5

_FIRST_RELEASE_YEAR_RE = re.compile(r"^\s*(\d{4})")
_TOKEN_SPLIT_RE = re.compile(r"[^\w]+", re.UNICODE)

#: Trailing edition/delivery suffixes that appear on embedded album strings
#: but never on release-group titles. The segment must *start* with a known
#: edition word, so real album names that merely contain these words are not
#: mangled. Examples stripped: `` / Deluxe Version``, ``- Remastered
#: Edition``, ``(Deluxe)``.
_EDITION_SUFFIX_RE = re.compile(
    r"\s*(?:[/\-–—]\s*|\()\s*"
    r"(?:deluxe|remastered|remaster|expanded|special|anniversary|explicit|"
    r"limited|bonus|deluxe\s+edition|deluxe\s+version)\b[^)]*\)?\s*$",
    re.IGNORECASE,
)


class NetworkLookupError(Exception):
    """A transport-level lookup failure: offline, timeout, rate limit, or 5xx.

    Raising this from ``suggest`` is deliberate: the runner records the skip,
    logs it, and keeps the rest of the batch moving. It is the honest-abstention
    path for *environmental* failures; "MusicBrainz has no matching release" is
    not an error and yields an empty suggestion list instead.
    """


def cache_key(normalized_album: str, normalized_artist: str) -> str:
    """Stable cache key for one normalized (album, artist) lookup pair.

    ``\\x1f`` (unit separator) cannot survive :func:`normalise_text`, so the
    join is unambiguous.
    """
    return f"{normalized_album}\x1f{normalized_artist}"


def strip_edition_suffix(album: str) -> str:
    """Remove a trailing edition/delivery suffix from an album string.

    Embedded album tags frequently carry `` / Deluxe Version``-style suffixes
    that no release group is titled with — the v0.2 era-recall defect had
    them eliminating every result. The segment is only stripped when it
    *starts* with a known edition word (see :data:`_EDITION_SUFFIX_RE`), so
    genuine album titles are preserved.
    """
    stripped = album.strip()
    while True:
        match = _EDITION_SUFFIX_RE.search(stripped)
        if match is None:
            return stripped.strip()
        stripped = stripped[: match.start()].rstrip(" /-–—(")


def era_tag_for_year(taxonomy: Taxonomy, year: int) -> str | None:
    """Map a release year to the taxonomy's ``era.<decade>s`` tag.

    The same mapping the local metadata provider applies to embedded years;
    the provider abstains when the decade has no taxonomy tag.
    """
    tag_id = f"era.{year // 10 * 10}s"
    return tag_id if taxonomy.has_tag(tag_id) else None


@dataclass(frozen=True, slots=True)
class CachedLookup:
    """One resolved (or negatively resolved) album/artist lookup."""

    normalized_album: str
    normalized_artist: str
    found: bool
    release_year: int | None
    musicbrainz_release_group_id: str | None
    matched_artist: str | None
    matched_release: str | None
    source_url: str | None
    suspicion: str | None
    queried_at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


class ReleaseDateCache:
    """Read/write access to the ``release_date_cache`` table (schema v2)."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get(
        self, normalized_album: str, normalized_artist: str
    ) -> CachedLookup | None:
        row = self.connection.execute(
            "SELECT normalized_album, normalized_artist, found, release_year,"
            " musicbrainz_release_group_id, matched_artist, matched_release,"
            " source_url, suspicion, queried_at FROM release_date_cache"
            " WHERE cache_key = ? AND query_version = ?",
            (
                cache_key(normalized_album, normalized_artist),
                QUERY_VERSION,
            ),
        ).fetchone()
        if row is None:
            return None
        found = bool(row["found"])
        return CachedLookup(
            normalized_album=row["normalized_album"],
            normalized_artist=row["normalized_artist"],
            found=found,
            release_year=row["release_year"] if found else None,
            musicbrainz_release_group_id=row["musicbrainz_release_group_id"],
            matched_artist=row["matched_artist"],
            matched_release=row["matched_release"],
            source_url=row["source_url"],
            suspicion=row["suspicion"],
            queried_at=row["queried_at"],
        )

    def store(self, lookup: CachedLookup) -> None:
        self.connection.execute(
            "INSERT INTO release_date_cache ("
            " cache_key, normalized_album, normalized_artist, found,"
            " release_year, musicbrainz_release_group_id, matched_artist,"
            " matched_release, source_url, suspicion, queried_at,"
            " query_version)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (cache_key) DO UPDATE SET"
            " found = excluded.found, release_year = excluded.release_year,"
            " musicbrainz_release_group_id = excluded.musicbrainz_release_group_id,"
            " matched_artist = excluded.matched_artist,"
            " matched_release = excluded.matched_release,"
            " source_url = excluded.source_url,"
            " suspicion = excluded.suspicion,"
            " queried_at = excluded.queried_at,"
            " query_version = excluded.query_version",
            (
                cache_key(lookup.normalized_album, lookup.normalized_artist),
                lookup.normalized_album,
                lookup.normalized_artist,
                int(lookup.found),
                lookup.release_year if lookup.found else None,
                lookup.musicbrainz_release_group_id,
                lookup.matched_artist,
                lookup.matched_release,
                lookup.source_url,
                lookup.suspicion,
                lookup.queried_at,
                QUERY_VERSION,
            ),
        )
        self.connection.commit()


class MusicBrainzHttpTransport:
    """Thin urllib transport for the MusicBrainz search endpoint.

    Pacing: every HTTP request (including retries) is spaced at least
    ``min_interval_seconds`` after the previous one, across retries and
    caller pairs alike — MusicBrainz asks anonymous clients for ~1 req/s.

    Retries: *transient* HTTP failures (429, 500, 502, 503, 504) are retried
    up to ``max_attempts`` total tries with linearly growing paced backoff
    (the live API returns 503 bursts even below 1 req/s — measured on the
    v0.2 rerun). Connection-level failures (DNS, refused, timeout) are **not**
    retried here: they fail fast as :class:`NetworkLookupError` and are
    retried by the next run, never silently dropped. Every failure mode is
    eventually raised as :class:`NetworkLookupError`; nothing here retries
    unboundedly or waits past ``timeout_seconds`` per attempt.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://musicbrainz.org",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        limit: int = _DEFAULT_SEARCH_LIMIT,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        min_interval_seconds: float = DEFAULT_MIN_QUERY_INTERVAL_SECONDS,
        user_agent: str = (
            "MusicTagger/0.1.0 (local personal-library tagger; "
            "https://github.com/zhentianashen-tech/musigtagger)"
        ),
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.limit = limit
        self.max_attempts = max(1, int(max_attempts))
        self.min_interval_seconds = min_interval_seconds
        self.user_agent = user_agent
        #: Counters for run ledgers: total HTTP requests sent and transient
        #: retries performed (the operator's date-check requires recording
        #: requests, failures, and retry behaviour).
        self.request_count = 0
        self.transient_retry_count = 0
        self._last_request_at: float | None = None

    def _pace(self) -> None:
        if self._last_request_at is not None and self.min_interval_seconds > 0:
            elapsed = time.monotonic() - self._last_request_at
            remaining = self.min_interval_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def search_release_groups(self, *, album: str, artist: str | None) -> dict:
        """Query ``ws/2/release-group`` and return the parsed JSON document.

        ``artist=None`` builds the album-only fallback query (stage 2 of the
        lookup); ``artist`` set builds the precise album+artist query.
        """
        # Lucene-reserved characters are quoted so album/artist text is treated
        # as data, never as query syntax.
        if artist:
            query = (
                f'releasegroup:"{_lucene_quote(album)}" AND '
                f'artist:"{_lucene_quote(artist)}"'
            )
        else:
            query = f'releasegroup:"{_lucene_quote(album)}"'
        url = (
            f"{self.base_url}/ws/2/release-group/"
            f"?query={urllib.parse.quote(query, safe='')}"
            f"&fmt=json&limit={int(self.limit)}"
        )
        last_error: NetworkLookupError | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._pace()
            self.request_count += 1
            request = urllib.request.Request(
                url, headers={"User-Agent": self.user_agent}
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=self.timeout_seconds
                ) as response:
                    status = response.status
                    payload = response.read()
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504):
                    last_error = NetworkLookupError(
                        f"musicbrainz rate-limited/transient failure "
                        f"(HTTP {exc.code})"
                    )
                else:
                    raise NetworkLookupError(
                        f"musicbrainz returned HTTP {exc.code}"
                    ) from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise NetworkLookupError(
                    f"musicbrainz unreachable: {type(exc).__name__}: {exc}"
                ) from exc
            else:
                if status == 200:
                    return self._parse(payload)
                last_error = NetworkLookupError(
                    f"musicbrainz returned HTTP {status}"
                )
            # Transient failure with budget left: paced backoff, then retry.
            if attempt < self.max_attempts:
                self.transient_retry_count += 1
                LOGGER.warning(
                    "MusicBrainz transient failure (attempt %d/%d): %s; retrying",
                    attempt,
                    self.max_attempts,
                    last_error,
                )
                backoff = self.min_interval_seconds * attempt
                self._last_request_at = time.monotonic()
                time.sleep(backoff)
        raise last_error  # type: ignore[misc] — set by the loop above

    def _parse(self, payload: bytes) -> dict:
        try:
            document = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as exc:
            raise NetworkLookupError(
                "musicbrainz returned a non-JSON body"
            ) from exc
        if not isinstance(document, dict):
            raise NetworkLookupError("musicbrainz returned an unexpected document")
        return document


def _lucene_quote(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _credit_name(artist_credit: object) -> str:
    """Flatten a MusicBrainz ``artist-credit`` array into one display string."""
    if not isinstance(artist_credit, list):
        return ""
    parts: list[str] = []
    for entry in artist_credit:
        if isinstance(entry, str):
            parts.append(entry)  # join phrase
            continue
        if isinstance(entry, dict):
            artist = entry.get("artist")
            name = entry.get("name")
            if isinstance(name, str) and name.strip():
                parts.append(name)
            elif isinstance(artist, dict) and isinstance(artist.get("name"), str):
                parts.append(artist["name"])
    return "".join(parts).strip()


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        token for token in _TOKEN_SPLIT_RE.split(normalise_text(text)) if token
    )


def _artists_compatible(query_artist: str, credit_artist: str) -> bool:
    """Conservative guard against matching a different artist's album.

    Multi-artist credits (``HUNTR/X, EJAE, AUDREY NUNA``), translations, and
    punctuation variants are common, so exact equality is too strict; instead
    require at least one shared word in either direction.
    """
    query_tokens = _tokens(query_artist)
    credit_tokens = _tokens(credit_artist)
    if not query_tokens or not credit_tokens:
        return False
    return bool(query_tokens & credit_tokens)


@dataclass(frozen=True, slots=True)
class _Resolution:
    lookup: CachedLookup
    suspicion: str | None = None


def resolve_release_year(
    document: dict,
    *,
    album: str,
    artist: str,
    normalized_album: str,
    normalized_artist: str,
    queried_at: str | None = None,
) -> _Resolution:
    """Pick the best release group from a *precise* (stage 1) search document.

    Deterministic: results are taken in MusicBrainz score order; the first
    entry whose artist credit is compatible with the query artist wins. The
    returned ``suspicion`` is non-``None`` when the best-compatible match
    disagrees with the query text in a way a reviewer should see (album
    title variant).
    """
    return _resolve_document(
        document,
        album=album,
        artist=artist,
        normalized_album=normalized_album,
        normalized_artist=normalized_artist,
        queried_at=queried_at,
        require_title_match=False,
    )


def resolve_release_year_album_only(
    document: dict,
    *,
    album: str,
    artist: str,
    normalized_album: str,
    normalized_artist: str,
    queried_at: str | None = None,
) -> _Resolution:
    """Pick the best release group from an *album-only* (stage 2) document.

    Stage 2 runs only when the precise query matched nothing, which is the
    normal case for various-artists soundtracks: the cast-credited release
    group shares no artist token with a per-track artist. The guard here is
    a strong *album title* match (normalized equality, or containment in
    either direction for punctuation/edition variants); an artist credit
    that does not share a token with the query artist no longer rejects the
    entry — it becomes a **FLAGGED** suspicion so the reviewer, not the
    provider, decides (standing guidance: never silently pick). Entries that
    do not match the album title at all are still rejected outright.
    """
    return _resolve_document(
        document,
        album=album,
        artist=artist,
        normalized_album=normalized_album,
        normalized_artist=normalized_artist,
        queried_at=queried_at,
        require_title_match=True,
    )


def _title_compatible(normalized_title: str, normalized_album: str) -> bool:
    if not normalized_title or not normalized_album:
        return False
    return (
        normalized_title == normalized_album
        or normalized_title in normalized_album
        or normalized_album in normalized_title
    )


def _resolve_document(
    document: dict,
    *,
    album: str,
    artist: str,
    normalized_album: str,
    normalized_artist: str,
    queried_at: str | None,
    require_title_match: bool,
) -> _Resolution:
    queried_at = queried_at or _utc_now()
    results = document.get("release-groups")
    if not isinstance(results, list):
        return _Resolution(_no_match(normalized_album, normalized_artist, queried_at))

    # First title-compatible entry with an incompatible artist credit, kept
    # as the flagged fallback in case no fully compatible entry exists.
    fallback: _Resolution | None = None

    for entry in results:
        if not isinstance(entry, dict):
            continue
        group_id = entry.get("id")
        title = entry.get("title")
        credit = _credit_name(entry.get("artist-credit"))
        if not isinstance(group_id, str) or not group_id:
            continue
        first_release = entry.get("first-release-date")
        if not isinstance(first_release, str):
            continue
        match = _FIRST_RELEASE_YEAR_RE.match(first_release)
        if match is None:
            continue
        year = int(match.group(1))

        # The edition-stripped query album is what the release-group title
        # must plausibly be: comparing against the *stripped* normalization
        # avoids flagging punctuation/edition variants (": " vs "(", the
        # stripped " / Deluxe Version") that the strip + containment rules
        # already account for. Only a genuinely different title is flagged.
        normalized_query_album = normalise_text(album)
        normalized_title = normalise_text(title or "")
        if require_title_match and not _title_compatible(
            normalized_title, normalized_query_album
        ):
            continue

        artist_compatible = _artists_compatible(artist, credit)
        suspicion = None
        if not _title_compatible(normalized_title, normalized_query_album):
            suspicion = (
                f"album title differs: queried {album!r}, "
                f"matched {title!r} on release group {group_id}"
            )
        if not artist_compatible:
            artist_flag = (
                f"query artist {artist!r} is not credited on the matched "
                f"release group (album-only match; credit: {credit or 'none'!r})"
            )
            suspicion = f"{artist_flag}; {suspicion}" if suspicion else artist_flag
            if require_title_match:
                # Stage 2: keep the best title-compatible entry as a flagged
                # fallback, but prefer a fully compatible entry if one exists.
                if fallback is None:
                    fallback = _Resolution(
                        _matched(
                            normalized_album, normalized_artist, queried_at,
                            year, group_id, credit, title, suspicion,
                        ),
                        suspicion,
                    )
                continue
            # Stage 1: the precise query matched this artist, so an entry
            # credited to a different artist is rejected outright.
            continue
        return _Resolution(
            _matched(
                normalized_album, normalized_artist, queried_at,
                year, group_id, credit, title, suspicion,
            ),
            suspicion,
        )
    if fallback is not None:
        return fallback
    return _Resolution(_no_match(normalized_album, normalized_artist, queried_at))


def _matched(
    normalized_album: str,
    normalized_artist: str,
    queried_at: str,
    year: int,
    group_id: str,
    credit: str,
    title: object,
    suspicion: str | None,
) -> CachedLookup:
    return CachedLookup(
        normalized_album=normalized_album,
        normalized_artist=normalized_artist,
        found=True,
        release_year=year,
        musicbrainz_release_group_id=group_id,
        matched_artist=credit,
        matched_release=title if isinstance(title, str) else None,
        source_url=f"https://musicbrainz.org/release-group/{group_id}",
        suspicion=suspicion,
        queried_at=queried_at,
    )


def _no_match(
    normalized_album: str, normalized_artist: str, queried_at: str
) -> CachedLookup:
    return CachedLookup(
        normalized_album=normalized_album,
        normalized_artist=normalized_artist,
        found=False,
        release_year=None,
        musicbrainz_release_group_id=None,
        matched_artist=None,
        matched_release=None,
        source_url=None,
        suspicion=None,
        queried_at=queried_at,
    )


class MusicBrainzReleaseYearProvider(SuggestionProvider):
    """Suggest the taxonomy era tag from MusicBrainz's first-release year.

    Parameters
    ----------
    taxonomy:
        The pinned run taxonomy (v1.0.0), used for era mapping and validation.
    cache:
        A :class:`ReleaseDateCache` over the library database. Injected, so
        tests can run fully in-memory and callers own the connection.
    transport:
        Anything with ``search_release_groups(album=..., artist=...)``; the
        default talks to musicbrainz.org over HTTPS.
    min_query_interval_seconds:
        Minimum spacing between actual network queries (MusicBrainz asks
        anonymous clients for ~1 req/s). Cache hits are not paced.
    confidence:
        Confidence attached to matched suggestions. The default
        :data:`NETWORK_YEAR_CONFIDENCE` (0.85) sits below embedded metadata
        (0.98) — a proposal for evaluation, not a settled threshold.
    """

    def __init__(
        self,
        taxonomy: Taxonomy,
        cache: ReleaseDateCache,
        transport: MusicBrainzHttpTransport | None = None,
        *,
        min_query_interval_seconds: float = DEFAULT_MIN_QUERY_INTERVAL_SECONDS,
        confidence: float = NETWORK_YEAR_CONFIDENCE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        taxonomy.require_version(PINNED_TAXONOMY_VERSION)
        self.taxonomy = taxonomy
        self.cache = cache
        self.transport = transport or MusicBrainzHttpTransport(
            timeout_seconds=timeout_seconds
        )
        self.min_query_interval_seconds = min_query_interval_seconds
        self.confidence = confidence
        self._last_query_at: float | None = None
        #: Pairs whose lookup failed *environmentally* in this run. Transport
        #: failures must never enter the persistent cache (the network may be
        #: back next run), but one dead network should cost one attempt per
        #: work per batch, not one per file. Instance-local, never persisted.
        self._failed_pairs: set[tuple[str, str]] = set()

    # -- pacing -----------------------------------------------------------

    def _pace(self) -> None:
        """Sleep so real network queries stay >= interval apart."""
        if self._last_query_at is not None and self.min_query_interval_seconds > 0:
            elapsed = time.monotonic() - self._last_query_at
            remaining = self.min_query_interval_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_query_at = time.monotonic()

    # -- the provider contract --------------------------------------------

    def suggest(self, track_descriptor: TrackDescriptor) -> list[TagSuggestion]:
        album = (track_descriptor.album or "").strip()
        artist = (track_descriptor.artist or "").strip()
        if not album or not artist:
            return []
        normalized_album = normalise_text(album)
        normalized_artist = normalise_text(artist)
        if not normalized_album or not normalized_artist:
            return []

        lookup = self.cache.get(normalized_album, normalized_artist)
        suspicion: str | None = None
        if lookup is None:
            if (normalized_album, normalized_artist) in self._failed_pairs:
                raise NetworkLookupError(
                    "lookup already failed earlier in this batch for album="
                    f"{album!r} artist={artist!r}; skipping without another "
                    "network attempt"
                )
            query_album = strip_edition_suffix(album)
            try:
                # Stage 1 — precise: album (edition-stripped) + artist.
                self._pace()
                document = self.transport.search_release_groups(
                    album=query_album, artist=artist
                )
                resolution = resolve_release_year(
                    document,
                    album=query_album,
                    artist=artist,
                    normalized_album=normalized_album,
                    normalized_artist=normalized_artist,
                )
                lookup = resolution.lookup
                suspicion = resolution.suspicion
                if not lookup.found:
                    # Stage 2 — album-only fallback: various-artists
                    # soundtracks credit the release group to the cast, so
                    # the artist AND-term can eliminate every result even
                    # though the album is right. Title compatibility becomes
                    # the guard; an artist mismatch is flagged, not hidden.
                    LOGGER.info(
                        "MusicBrainz: precise query matched nothing for "
                        "album=%r artist=%r; trying album-only fallback",
                        album,
                        artist,
                    )
                    self._pace()
                    document = self.transport.search_release_groups(
                        album=query_album, artist=None
                    )
                    resolution = resolve_release_year_album_only(
                        document,
                        album=query_album,
                        artist=artist,
                        normalized_album=normalized_album,
                        normalized_artist=normalized_artist,
                    )
                    lookup = resolution.lookup
                    suspicion = resolution.suspicion
            except NetworkLookupError:
                self._failed_pairs.add((normalized_album, normalized_artist))
                raise
            self.cache.store(lookup)
            if not lookup.found:
                LOGGER.info(
                    "MusicBrainz: no release group matched album=%r artist=%r",
                    album,
                    artist,
                )
        else:
            suspicion = lookup.suspicion
        if lookup.found and suspicion:
            # Flag, never silently accept: the reviewer sees this in the
            # evidence and evaluation sees the warning.
            LOGGER.warning("MusicBrainz suspicious match: %s", suspicion)

        if not lookup.found or lookup.release_year is None:
            return []
        era_tag = era_tag_for_year(self.taxonomy, lookup.release_year)
        if era_tag is None:
            return []
        evidence = (
            f"MusicBrainz release group {lookup.matched_release!r} by "
            f"{lookup.matched_artist!r}: first release year "
            f"{lookup.release_year} (queried album={album!r}, "
            f"artist={artist!r}); {lookup.source_url}"
        )
        if suspicion:
            evidence = f"{evidence}; FLAGGED: {suspicion}"
        return [
            TagSuggestion(
                tag_id=era_tag,
                confidence=self.confidence,
                source=SOURCE,
                evidence=evidence,
            )
        ]
