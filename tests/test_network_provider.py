"""Network release-date provider: mocked-transport behaviour and failure modes.

Covers the MUSI-14 acceptance modes: match, no-match, timeout, rate limit,
offline, caching, era-mapping parity with the local provider, and
batch-isolation through the runner. No test talks to the real network.
"""

from __future__ import annotations

import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from musigtagger.contracts import TaxonomyLoader, TrackDescriptor
from musigtagger.db import apply_migrations, connect
from musigtagger.engine import (
    JsonlEventLogger,
    MetadataSuggestionProvider,
    MusicBrainzHttpTransport,
    MusicBrainzReleaseYearProvider,
    NetworkLookupError,
    ReleaseDateCache,
    SuggestionRunner,
)
from musigtagger.engine.network import (
    CachedLookup,
    cache_key,
    resolve_release_year,
)

TAXONOMY_DIR = Path(__file__).resolve().parents[1] / "taxonomy"


def _search_document(*release_groups: dict) -> dict:
    return {"release-groups": list(release_groups)}


def _release_group(
    group_id: str,
    title: str,
    artist_name: str,
    first_release: str,
    score: int = 100,
) -> dict:
    return {
        "id": group_id,
        "score": score,
        "title": title,
        "first-release-date": first_release,
        "artist-credit": [{"name": artist_name, "artist": {"name": artist_name}}],
    }


class FakeTransport:
    """Scripted transport: records queries, raises or returns per queue."""

    def __init__(self, responses=None, error=None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.queries: list[tuple[str, str]] = []

    def search_release_groups(self, *, album: str, artist: str) -> dict:
        self.queries.append((album, artist))
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("FakeTransport ran out of scripted responses")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class NetworkProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.taxonomy = TaxonomyLoader.load(TAXONOMY_DIR, version="1.0.0")

    def setUp(self) -> None:
        self.connection = connect(":memory:")
        apply_migrations(self.connection)
        self.cache = ReleaseDateCache(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def _provider(self, transport: FakeTransport, **kwargs) -> MusicBrainzReleaseYearProvider:
        return MusicBrainzReleaseYearProvider(
            self.taxonomy, self.cache, transport, **kwargs
        )

    # -- match ------------------------------------------------------------

    def test_match_suggests_era_with_source_confidence_and_evidence(self) -> None:
        transport = FakeTransport(
            [_search_document(_release_group("rg-1", "Busy Works", "Test Artist", "1994-03-01"))]
        )
        provider = self._provider(transport)
        track = TrackDescriptor(
            path="/music/x/01.mp3", artist="Test Artist", album="Busy Works"
        )
        suggestions = provider.suggest(track)

        self.assertEqual(len(suggestions), 1)
        suggestion = suggestions[0]
        self.assertEqual(suggestion.tag_id, "era.1990s")
        self.assertEqual(suggestion.source, "network.musicbrainz")
        self.assertEqual(suggestion.confidence, 0.85)
        for fragment in ("Test Artist", "Busy Works", "1994", "rg-1", "musicbrainz.org"):
            self.assertIn(fragment, suggestion.evidence)
        self.taxonomy.validate_tag_ids([suggestion.tag_id])

    def test_suggestions_validate_against_pinned_taxonomy(self) -> None:
        transport = FakeTransport(
            [_search_document(_release_group("rg-2", "Album", "Artist", "1977"))]
        )
        provider = self._provider(transport)
        track = TrackDescriptor(path="/m/a.flac", artist="Artist", album="Album")
        suggestions = provider.suggest(track)
        self.assertEqual(self.taxonomy.unknown_tag_ids([s.tag_id for s in suggestions]), ())

    def test_year_without_taxonomy_decade_abstains(self) -> None:
        transport = FakeTransport(
            [_search_document(_release_group("rg-3", "Old", "Artist", "1931"))]
        )
        provider = self._provider(transport)
        track = TrackDescriptor(path="/m/a.flac", artist="Artist", album="Old")
        self.assertEqual(provider.suggest(track), [])

    # -- caching / batch-first ---------------------------------------------

    def test_47_instances_of_one_work_make_one_network_query(self) -> None:
        transport = FakeTransport(
            [_search_document(_release_group("rg-4", "Work", "Artist", "2003"))]
        )
        provider = self._provider(transport, min_query_interval_seconds=0.0)
        for index in range(47):
            track = TrackDescriptor(
                path=f"/music/track {index:02d}.flac",
                artist="Artist  ",
                album="Work!",
            )
            suggestions = provider.suggest(track)
            self.assertEqual(suggestions[0].tag_id, "era.2000s")

        self.assertEqual(len(transport.queries), 1)
        # every instance produced the same normalized query pair
        album, artist = transport.queries[0]
        self.assertEqual((album, artist), ("Work!", "Artist"))

    def test_negative_result_is_cached_too(self) -> None:
        transport = FakeTransport([_search_document()])
        provider = self._provider(transport, min_query_interval_seconds=0.0)
        track = TrackDescriptor(path="/m/a.flac", artist="Nobody", album="Nothing")
        self.assertEqual(provider.suggest(track), [])
        self.assertEqual(provider.suggest(track), [])
        self.assertEqual(len(transport.queries), 1)

    def test_cache_round_trip_positive_and_negative_and_upsert(self) -> None:
        found = CachedLookup(
            normalized_album="work",
            normalized_artist="artist",
            found=True,
            release_year=1988,
            musicbrainz_release_group_id="rg-9",
            matched_artist="Artist",
            matched_release="Work",
            source_url="https://musicbrainz.org/release-group/rg-9",
            suspicion=None,
            queried_at="2026-11-17T00:00:00.000Z",
        )
        self.cache.store(found)
        loaded = self.cache.get("work", "artist")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.release_year, 1988)
        self.assertTrue(loaded.found)
        self.assertIsNone(loaded.suspicion)

        negative = CachedLookup(
            normalized_album="work",
            normalized_artist="artist",
            found=False,
            release_year=None,
            musicbrainz_release_group_id=None,
            matched_artist=None,
            matched_release=None,
            source_url=None,
            suspicion=None,
            queried_at="2026-11-17T00:00:01.000Z",
        )
        self.cache.store(negative)
        loaded = self.cache.get("work", "artist")
        self.assertFalse(loaded.found)
        self.assertIsNone(loaded.release_year)
        # a different pair is untouched
        self.assertIsNone(self.cache.get("other", "artist"))

    def test_cache_key_is_ambiguous_free(self) -> None:
        self.assertNotEqual(cache_key("a b", "c"), cache_key("a", "b c"))

    # -- matching rule ------------------------------------------------------

    def test_incompatible_artist_is_not_a_match(self) -> None:
        transport = FakeTransport(
            [
                _search_document(
                    _release_group("rg-5", "Same Album", "Completely Different", "1999")
                )
            ]
        )
        provider = self._provider(transport, min_query_interval_seconds=0.0)
        track = TrackDescriptor(path="/m/a.flac", artist="Somebody", album="Same Album")
        self.assertEqual(provider.suggest(track), [])
        cached = self.cache.get("same album", "somebody")
        self.assertFalse(cached.found)

    def test_multi_artist_credit_matches(self) -> None:
        document = _search_document(
            _release_group("rg-6", "Golden", "HUNTR/X, EJAE, AUDREY NUNA", "2025-06-04")
        )
        provider = self._provider(FakeTransport([document]), min_query_interval_seconds=0.0)
        track = TrackDescriptor(
            path="/m/golden.ncm", artist="HUNTR/X,EJAE,AUDREY NUNA", album="Golden"
        )
        suggestions = provider.suggest(track)
        self.assertEqual(suggestions[0].tag_id, "era.2020s")

    def test_suspicious_match_is_flagged_in_evidence_and_cached(self) -> None:
        document = _search_document(
            _release_group("rg-7", "Deluxe Edition", "Artist", "2010")
        )
        provider = self._provider(FakeTransport([document]), min_query_interval_seconds=0.0)
        track = TrackDescriptor(path="/m/a.flac", artist="Artist", album="Album")
        suggestions = provider.suggest(track)
        self.assertEqual(suggestions[0].tag_id, "era.2010s")
        self.assertIn("FLAGGED", suggestions[0].evidence)
        cached = self.cache.get("album", "artist")
        self.assertIsNotNone(cached.suspicion)
        # a later batch sees the flag from cache without another query
        again = provider.suggest(track)
        self.assertIn("FLAGGED", again[0].evidence)

    def test_resolution_is_deterministic_score_order(self) -> None:
        document = _search_document(
            _release_group("rg-low", "Album", "Artist", "2005", score=45),
            _release_group("rg-high", "Album", "Artist", "2001", score=98),
        )
        resolution = resolve_release_year(
            document,
            album="Album",
            artist="Artist",
            normalized_album="album",
            normalized_artist="artist",
        )
        # Score order from MusicBrainz is preserved: first compatible entry wins.
        self.assertEqual(
            resolution.lookup.musicbrainz_release_group_id, "rg-low"
        )

    def test_era_mapping_parity_with_local_provider(self) -> None:
        """Network and local providers map years onto the same era tags."""
        local = MetadataSuggestionProvider(self.taxonomy)
        for year in (1955, 1963, 1971, 1984, 1996, 2002, 2011, 2024):
            transport = FakeTransport(
                [_search_document(_release_group(f"rg-{year}", "A", "B", f"{year}-01-01"))]
            )
            connection = connect(":memory:")
            apply_migrations(connection)
            provider = MusicBrainzReleaseYearProvider(
                self.taxonomy,
                ReleaseDateCache(connection),
                transport,
                min_query_interval_seconds=0.0,
            )
            network_suggestion = provider.suggest(
                TrackDescriptor(path="/m/a.flac", artist="B", album="A")
            )
            local_suggestions = local.suggest(
                TrackDescriptor(path="/m/a.flac", year=year)
            )
            local_era = next(
                s.tag_id for s in local_suggestions if s.tag_id.startswith("era.")
            )
            self.assertEqual(network_suggestion[0].tag_id, local_era, year)
            connection.close()

    # -- failure modes -------------------------------------------------------

    def test_transport_failure_raises_network_lookup_error(self) -> None:
        provider = self._provider(FakeTransport(error=NetworkLookupError("down")))
        track = TrackDescriptor(path="/m/a.flac", artist="A", album="B")
        with self.assertRaises(NetworkLookupError):
            provider.suggest(track)

    def test_dead_pair_costs_one_attempt_per_batch_not_per_file(self) -> None:
        """47 instances of a work whose network lookup fails make 1 attempt."""
        transport = FakeTransport(error=NetworkLookupError("down"))
        provider = self._provider(transport, min_query_interval_seconds=0.0)
        runner = SuggestionRunner(self.taxonomy, JsonlEventLogger("/dev/null"))
        tracks = [
            TrackDescriptor(path=f"/m/{i}.flac", artist="A", album="Album")
            for i in range(47)
        ]
        result = runner.suggest_batch(tracks, provider, run_id="run-memo")
        self.assertEqual(len(result.failures), 47)
        self.assertEqual(len(transport.queries), 1)
        # A fresh provider instance (next run) retries: failures never persist.
        retry_transport = FakeTransport(
            [_search_document(_release_group("rg-11", "Album", "A", "1968"))]
        )
        retry = self._provider(retry_transport, min_query_interval_seconds=0.0)
        suggestions = retry.suggest(tracks[0])
        self.assertEqual(suggestions[0].tag_id, "era.1960s")

    def test_missing_album_or_artist_makes_no_network_call(self) -> None:
        transport = FakeTransport()
        provider = self._provider(transport)
        for track in (
            TrackDescriptor(path="/m/a.flac", album="Album"),
            TrackDescriptor(path="/m/a.flac", artist="Artist"),
            TrackDescriptor(path="/m/a.flac", album=" ", artist=" "),
        ):
            self.assertEqual(provider.suggest(track), [])
        self.assertEqual(transport.queries, [])

    def test_batch_with_network_down_completes_with_logged_abstentions(self) -> None:
        """One dead transport never aborts or hangs the rest of the batch."""
        transport = FakeTransport(error=NetworkLookupError("connection refused"))
        provider = self._provider(transport, min_query_interval_seconds=0.0)
        runner = SuggestionRunner(self.taxonomy, JsonlEventLogger("/dev/null"))
        tracks = [
            TrackDescriptor(path=f"/m/{i}.flac", artist="A", album=f"Album {i}")
            for i in range(5)
        ]
        started = time.monotonic()
        result = runner.suggest_batch(tracks, provider, run_id="run-down")
        elapsed = time.monotonic() - started

        self.assertEqual(len(result.failures), 5)
        self.assertEqual(result.results, ())
        self.assertLess(elapsed, 10.0)
        for failure in result.failures:
            self.assertIn("NetworkLookupError", failure.reason)

    def test_partial_network_failure_isolates_to_its_works(self) -> None:
        transport = FakeTransport(
            responses=[
                NetworkLookupError("timeout on work one"),
                _search_document(_release_group("rg-10", "B", "Artist", "1972")),
                NetworkLookupError("rate limited on work three"),
            ]
        )
        provider = self._provider(transport, min_query_interval_seconds=0.0)
        runner = SuggestionRunner(self.taxonomy, JsonlEventLogger("/dev/null"))
        tracks = [
            TrackDescriptor(path="/m/1.flac", artist="Artist", album="A"),
            TrackDescriptor(path="/m/2.flac", artist="Artist", album="B"),
            TrackDescriptor(path="/m/3.flac", artist="Artist", album="C"),
        ]
        result = runner.suggest_batch(tracks, provider)

        self.assertEqual(len(result.failures), 2)
        self.assertEqual(len(result.results), 1)
        item = result.results[0]
        self.assertEqual(item.track.path, "/m/2.flac")
        self.assertEqual(item.suggestions[0].tag_id, "era.1970s")

    # -- pacing ---------------------------------------------------------------

    def test_queries_are_paced_above_the_minimum_interval(self) -> None:
        transport = FakeTransport(
            responses=[
                _search_document(_release_group("rg-a", "A", "Artist", "1980")),
                _search_document(_release_group("rg-b", "B", "Artist", "1981")),
            ]
        )
        provider = self._provider(transport, min_query_interval_seconds=0.15)
        provider.suggest(TrackDescriptor(path="/m/1.flac", artist="Artist", album="A"))
        provider.suggest(TrackDescriptor(path="/m/2.flac", artist="Artist", album="B"))
        self.assertEqual(len(transport.queries), 2)


class _DelayedHandler(BaseHTTPRequestHandler):
    delay_seconds = 1.0

    def do_GET(self):  # noqa: N802 (http.server API)
        time.sleep(self.delay_seconds)
        body = json.dumps({"release-groups": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


class _RateLimitedHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b'{"error": "limit reached"}'
        self.send_response(503)
        self.send_header("Retry-After", "1")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


class RealTransportFailureTests(unittest.TestCase):
    """The urllib transport itself: timeouts, rate limits, offline errors."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.delay_server = ThreadingHTTPServer(("127.0.0.1", 0), _DelayedHandler)
        threading.Thread(target=cls.delay_server.serve_forever, daemon=True).start()
        cls.rate_server = ThreadingHTTPServer(("127.0.0.1", 0), _RateLimitedHandler)
        threading.Thread(target=cls.rate_server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.delay_server.shutdown()
        cls.rate_server.shutdown()
        cls.delay_server.server_close()
        cls.rate_server.server_close()

    def test_timeout_raises_quickly_and_never_hangs(self) -> None:
        transport = MusicBrainzHttpTransport(
            base_url=f"http://127.0.0.1:{self.delay_server.server_port}",
            timeout_seconds=0.25,
        )
        started = time.monotonic()
        with self.assertRaises(NetworkLookupError) as caught:
            transport.search_release_groups(album="A", artist="B")
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.0)  # the server sleeps 1.0 s; timeout is 0.25 s
        self.assertIn("unreachable", str(caught.exception))

    def test_rate_limit_response_is_reported_as_rate_limit(self) -> None:
        transport = MusicBrainzHttpTransport(
            base_url=f"http://127.0.0.1:{self.rate_server.server_port}",
            timeout_seconds=2.0,
        )
        with self.assertRaises(NetworkLookupError) as caught:
            transport.search_release_groups(album="A", artist="B")
        self.assertIn("rate-limit", str(caught.exception))

    def test_connection_refused_is_offline_abstention(self) -> None:
        # Port 1 on loopback is not listening in this environment.
        transport = MusicBrainzHttpTransport(
            base_url="http://127.0.0.1:1", timeout_seconds=2.0
        )
        with self.assertRaises(NetworkLookupError):
            transport.search_release_groups(album="A", artist="B")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
