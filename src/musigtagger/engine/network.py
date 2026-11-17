"""Minimal network release-date lookup provider (MusicBrainz).

The only network capability in Phase 1 (operator-approved, MUSI-14). It
resolves an album + artist pair to the release group's *first* release year
via the open MusicBrainz web service and proposes the matching taxonomy
``era.<decade>s`` tag through the same mapping the local metadata provider
uses.

Failure behaviour (CONTRACTS §3.6): network unavailable, timeout, rate
limit, or no match are all honest abstentions. Transport failures raise
:class:`NetworkLookupError` so the caller (``SuggestionRunner``) logs the
skip and continues the batch; the provider itself never blocks forever
(every HTTP call carries a timeout) and never aborts a batch. Offline runs
degrade to exactly the pre-MUSI-14 behaviour when the provider is simply
not constructed.

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

#: MusicBrainz asks anonymous clients to stay at ~1 request per second.
DEFAULT_MIN_QUERY_INTERVAL_SECONDS = 1.0
DEFAULT_TIMEOUT_SECONDS = 5.0
_DEFAULT_SEARCH_LIMIT = 10

_FIRST_RELEASE_YEAR_RE = re.compile(r"^\s*(\d{4})")
_TOKEN_SPLIT_RE = re.compile(r"[^\w]+", re.UNICODE)


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
            " WHERE cache_key = ?",
            (cache_key(normalized_album, normalized_artist),),
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
            " matched_release, source_url, suspicion, queried_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (cache_key) DO UPDATE SET"
            " found = excluded.found, release_year = excluded.release_year,"
            " musicbrainz_release_group_id = excluded.musicbrainz_release_group_id,"
            " matched_artist = excluded.matched_artist,"
            " matched_release = excluded.matched_release,"
            " source_url = excluded.source_url,"
            " suspicion = excluded.suspicion,"
            " queried_at = excluded.queried_at",
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
            ),
        )
        self.connection.commit()


class MusicBrainzHttpTransport:
    """Thin urllib transport for the MusicBrainz search endpoint.

    Every failure mode (DNS, refused connection, timeout, rate limit, 5xx,
    non-JSON body) is raised as :class:`NetworkLookupError`; nothing here
    retries unboundedly or waits past ``timeout_seconds``.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://musicbrainz.org",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        limit: int = _DEFAULT_SEARCH_LIMIT,
        user_agent: str = (
            "MusicTagger/0.1.0 (local personal-library tagger; "
            "no public contact endpoint)"
        ),
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.limit = limit
        self.user_agent = user_agent

    def search_release_groups(self, *, album: str, artist: str) -> dict:
        """Query ``ws/2/release-group`` and return the parsed JSON document."""
        # Lucene-reserved characters are quoted so album/artist text is treated
        # as data, never as query syntax.
        query = (
            f'releasegroup:"{_lucene_quote(album)}" AND '
            f'artist:"{_lucene_quote(artist)}"'
        )
        url = (
            f"{self.base_url}/ws/2/release-group/"
            f"?query={urllib.parse.quote(query, safe='')}"
            f"&fmt=json&limit={int(self.limit)}"
        )
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                status = response.status
                payload = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                raise NetworkLookupError(
                    f"musicbrainz rate-limited the lookup (HTTP {exc.code})"
                ) from exc
            raise NetworkLookupError(
                f"musicbrainz returned HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise NetworkLookupError(
                f"musicbrainz unreachable: {type(exc).__name__}: {exc}"
            ) from exc
        if status != 200:
            raise NetworkLookupError(f"musicbrainz returned HTTP {status}")
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
    """Pick the best release group from a search document.

    Deterministic: results are taken in MusicBrainz score order; the first
    entry whose artist credit is compatible with the query artist wins. The
    returned ``suspicion`` is non-``None`` when the best-compatible match
    disagrees with the query text in a way a reviewer should see (artist
    matched only by one shared word, or no year on the group).
    """
    queried_at = queried_at or _utc_now()
    results = document.get("release-groups")
    if not isinstance(results, list):
        return _Resolution(_no_match(normalized_album, normalized_artist, queried_at))

    for entry in results:
        if not isinstance(entry, dict):
            continue
        group_id = entry.get("id")
        title = entry.get("title")
        credit = _credit_name(entry.get("artist-credit"))
        if not isinstance(group_id, str) or not group_id:
            continue
        if not _artists_compatible(artist, credit):
            continue
        first_release = entry.get("first-release-date")
        if not isinstance(first_release, str):
            continue
        match = _FIRST_RELEASE_YEAR_RE.match(first_release)
        if match is None:
            continue
        year = int(match.group(1))
        suspicion = None
        if normalise_text(title or "") != normalized_album:
            suspicion = (
                f"album title differs: queried {album!r}, "
                f"matched {title!r} on release group {group_id}"
            )
        return _Resolution(
            CachedLookup(
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
            ),
            suspicion,
        )
    return _Resolution(_no_match(normalized_album, normalized_artist, queried_at))


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
            self._pace()
            try:
                document = self.transport.search_release_groups(
                    album=album, artist=artist
                )
            except NetworkLookupError:
                self._failed_pairs.add((normalized_album, normalized_artist))
                raise
            resolution = resolve_release_year(
                document,
                album=album,
                artist=artist,
                normalized_album=normalized_album,
                normalized_artist=normalized_artist,
            )
            lookup = resolution.lookup
            suspicion = resolution.suspicion
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
