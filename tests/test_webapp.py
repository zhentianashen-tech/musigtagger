"""The local review web app: pages, actions, batch review, HTTP plumbing."""

from __future__ import annotations

import http.client
import threading
from urllib.parse import urlencode

from musigtagger.app.webapp import WebApp, make_server

from support import AppTestCase, make_library


class WebAppTests(AppTestCase):
    def setUp(self) -> None:
        super().setUp()
        make_library(self.library, 4)
        self.scan()
        self.app = WebApp(self.context)

    def _suggestion_id(self, tag_id: str = "genre.hip-hop") -> int:
        for row in self.context.store.suggestions_with_status(("suggested",)):
            if row["tag_id"] == tag_id:
                return int(row["id"])
        raise AssertionError("no suggestion")

    def test_queue_page_lists_reviewable_tracks(self) -> None:
        response = self.app.handle_get("/", {})
        self.assertEqual(response.status, 200)
        html = response.text
        self.assertIn("Music Tagger", html)
        self.assertIn("000 track", html)
        self.assertIn("Accept", html)
        self.assertIn("Apply all reviewed tags", html)
        self.assertIn("4 track(s) match", html)

    def test_accept_via_form(self) -> None:
        suggestion_id = self._suggestion_id()
        response = self.app.handle_post(
            "/review", {"id": [str(suggestion_id)], "action": ["accept"]}
        )
        self.assertEqual(response.status, 303)
        self.assertIn("notice=", response.headers["Location"])
        row = self.context.store.get_suggestion(suggestion_id)
        self.assertEqual(row["status"], "accepted")

    def test_edit_via_form(self) -> None:
        suggestion_id = self._suggestion_id()
        response = self.app.handle_post(
            "/review",
            {
                "id": [str(suggestion_id)],
                "action": ["edit"],
                "tag_id": ["genre.jazz"],
            },
        )
        self.assertEqual(response.status, 303)
        row = self.context.store.get_suggestion(suggestion_id)
        self.assertEqual(row["status"], "edited")
        self.assertEqual(row["final_tag_id"], "genre.jazz")

    def test_reject_via_form(self) -> None:
        suggestion_id = self._suggestion_id()
        self.app.handle_post(
            "/review", {"id": [str(suggestion_id)], "action": ["reject"]}
        )
        self.assertEqual(
            self.context.store.get_suggestion(suggestion_id)["status"], "rejected"
        )

    def test_batch_accept_covers_the_whole_filter_not_the_page(self) -> None:
        response = self.app.handle_post(
            "/batch", {"action": ["accept"], "status": ["suggested"]}
        )
        self.assertEqual(response.status, 303)
        self.assertEqual(len(self.context.store.suggestions_with_status(("accepted",))), 8)
        self.assertEqual(self.context.store.suggestions_with_status(("suggested",)), [])

    def test_invalid_action_is_reported_without_crashing(self) -> None:
        response = self.app.handle_post(
            "/review", {"id": [str(self._suggestion_id())], "action": ["nonsense"]}
        )
        self.assertEqual(response.status, 303)
        self.assertIn("error=", response.headers["Location"])

    def test_apply_and_undo_through_the_ui(self) -> None:
        self.app.handle_post("/batch", {"action": ["accept"], "status": ["suggested"]})
        apply_response = self.app.handle_post("/apply", {})
        self.assertEqual(apply_response.status, 303)
        applied = self.context.store.suggestions_with_status(("applied",))
        self.assertEqual(len(applied), 8)
        batch = self.context.store.list_batches()[0]
        self.assertEqual(batch["status"], "completed")
        undo_response = self.app.handle_post(
            "/undo", {"batch_id": [str(batch["id"])]}
        )
        self.assertEqual(undo_response.status, 303)
        self.assertEqual(self.context.store.get_batch(int(batch["id"]))["status"], "undone")

    def test_history_page_shows_batches_and_events(self) -> None:
        self.app.handle_post("/batch", {"action": ["accept"], "status": ["suggested"]})
        self.app.handle_post("/apply", {})
        html = self.app.handle_get("/history", {}).text
        self.assertIn("Write batches", html)
        self.assertIn("completed", html)
        self.assertIn("History log", html)
        self.assertIn("review_outcome", html)

    def test_pagination_handles_a_hundred_tracks(self) -> None:
        make_library(self.library, 100)
        self.scan()
        first = self.app.handle_get("/", {}).text
        self.assertIn("100 track(s) match", first)
        self.assertIn("page 1 of", first)
        second = self.app.handle_get("/", {"page": ["2"]}).text
        self.assertIn("page 2 of", second)
        self.assertIn("next", first)

    def test_health_endpoint(self) -> None:
        response = self.app.handle_get("/health", {})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, b"ok")

    def test_unknown_route_is_404(self) -> None:
        self.assertEqual(self.app.handle_get("/nope", {}).status, 404)


class HttpServerTests(AppTestCase):
    def setUp(self) -> None:
        super().setUp()
        make_library(self.library, 2)
        self.scan()
        self.server = make_server(self.context)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address[:2]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        super().tearDown()

    def test_serves_the_queue_over_http(self) -> None:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            connection.request("GET", "/")
            response = connection.getresponse()
            body = response.read().decode("utf-8")
        finally:
            connection.close()
        self.assertEqual(response.status, 200)
        self.assertIn("Music Tagger", body)

    def test_posts_a_review_decision_over_http(self) -> None:
        row = self.context.store.suggestions_with_status(("suggested",))[0]
        body = urlencode({"id": str(row["id"]), "action": "accept"})
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            connection.request(
                "POST",
                "/review",
                body=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response = connection.getresponse()
            response.read()
        finally:
            connection.close()
        self.assertEqual(response.status, 303)
        self.assertEqual(
            self.context.store.get_suggestion(int(row["id"]))["status"], "accepted"
        )
