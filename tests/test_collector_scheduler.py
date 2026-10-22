"""Fault-injection checks. These tests never contact Discord or read credentials."""

import copy
import threading
import unittest
from datetime import datetime, timedelta, timezone
from urllib.error import URLError

from discord_archive.collector import (
    AccessDenied,
    AuthRequired,
    CaptureBusy,
    CaptureService,
    DiscordAPIError,
    DiscordClient,
)
from discord_archive.scheduler import day_bounds, due, market_day
from discord_archive.settings import DEFAULT_CONFIG
from discord_archive.store import ArchiveStore


class ScriptedTransport:
    def __init__(self, *events):
        self.events = list(events)
        self.calls = []

    def __call__(self, method, url, headers):
        self.calls.append((method, url, headers))
        if not self.events:
            raise AssertionError("Unexpected request after the scripted responses")
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


class DiscordClientReliabilityTests(unittest.TestCase):
    def make_client(self, *events):
        transport = ScriptedTransport(*events)
        sleeps = []
        client = DiscordClient(
            "test-token-not-a-real-credential", transport=transport, sleep=sleeps.append
        )
        return client, transport, sleeps

    def test_message_read_is_get_and_encodes_pagination(self):
        client, transport, _ = self.make_client((200, {}, [{"id": "123"}]))
        result = client.list_messages("456", before="789", limit=100)
        self.assertEqual(result, [{"id": "123"}])
        method, url, headers = transport.calls[0]
        self.assertEqual(method, "GET")
        self.assertIn("/channels/456/messages", url)
        self.assertIn("before=789", url)
        self.assertIn("limit=100", url)
        self.assertNotIn("test-token-not-a-real-credential", url)
        self.assertEqual(headers.get("Authorization"), "test-token-not-a-real-credential")

    def test_rate_limit_waits_for_json_retry_after_then_recovers(self):
        client, transport, sleeps = self.make_client(
            (429, {}, {"retry_after": 0.25}), (200, {}, {"ok": True})
        )
        self.assertEqual(client.get("/test"), {"ok": True})
        self.assertEqual(len(transport.calls), 2)
        self.assertTrue(sleeps)
        self.assertGreaterEqual(sleeps[0], 0.25)

    def test_rate_limit_waits_for_header_retry_after(self):
        client, transport, sleeps = self.make_client(
            (429, {"Retry-After": "0.6"}, {}), (200, {}, [])
        )
        self.assertEqual(client.get("/test"), [])
        self.assertEqual(len(transport.calls), 2)
        self.assertGreaterEqual(sleeps[0], 0.6)

    def test_repeated_rate_limit_is_bounded(self):
        client, transport, sleeps = self.make_client(
            *[(429, {}, {"retry_after": 0.01})] * 8
        )
        with self.assertRaises(DiscordAPIError) as raised:
            client.get("/test")
        self.assertEqual(raised.exception.status, 429)
        self.assertGreater(len(transport.calls), 1)
        self.assertLessEqual(len(transport.calls), 4)
        self.assertTrue(all(delay >= 0.01 for delay in sleeps))

    def test_unauthorized_is_not_retried(self):
        client, transport, sleeps = self.make_client((401, {}, {"message": "Unauthorized"}))
        with self.assertRaises(AuthRequired):
            client.get("/test")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(sleeps, [])

    def test_forbidden_is_not_retried(self):
        client, transport, sleeps = self.make_client((403, {}, {"message": "Missing Access"}))
        with self.assertRaises(AccessDenied):
            client.get("/test")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(sleeps, [])

    def test_temporary_network_failure_recovers(self):
        client, transport, sleeps = self.make_client(
            URLError("Network unavailable"), (200, {}, {"ok": True})
        )
        self.assertEqual(client.get("/test"), {"ok": True})
        self.assertEqual(len(transport.calls), 2)
        self.assertTrue(sleeps)
        self.assertTrue(all(delay > 0 for delay in sleeps))

    def test_server_failure_recovers(self):
        client, transport, sleeps = self.make_client(
            (503, {}, {"message": "Unavailable"}), (200, {}, [])
        )
        self.assertEqual(client.get("/test"), [])
        self.assertEqual(len(transport.calls), 2)
        self.assertTrue(sleeps)

    def test_repeated_network_failure_is_bounded_and_sanitized(self):
        secret = "test-token-not-a-real-credential"
        client, transport, _ = self.make_client(*[URLError(f"offline {secret}")] * 8)
        with self.assertRaises(DiscordAPIError) as raised:
            client.get("/test")
        self.assertGreater(len(transport.calls), 1)
        self.assertLessEqual(len(transport.calls), 4)
        self.assertNotIn(secret, str(raised.exception))

    def test_other_client_errors_do_not_retry(self):
        client, transport, sleeps = self.make_client((404, {}, {"message": "Unknown Channel"}))
        with self.assertRaises(DiscordAPIError) as raised:
            client.get("/test")
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(sleeps, [])


class CaptureReliabilityTests(unittest.TestCase):
    NOW = datetime(2026, 10, 22, 20, tzinfo=timezone.utc)

    def setUp(self):
        self.store = ArchiveStore(":memory:")
        initial = self.store.start_run("456", started_at=self.NOW - timedelta(hours=1))
        self.store.ingest_messages("456", [self.message(900)], run_id=initial)
        self.store.finish_run(initial, True, cursor="900", ended_at=self.NOW - timedelta(hours=1))

    def tearDown(self):
        self.store.close()

    def message(self, identity):
        return {
            "id": str(identity),
            "channel_id": "456",
            "author": {"id": "22", "username": "fictitious-user"},
            "timestamp": (self.NOW - timedelta(minutes=20)).isoformat(),
            "content": f"Fictitious content {identity}",
        }

    def test_partial_page_failure_keeps_cursor_and_recovery_deduplicates(self):
        first_page = [self.message(identity) for identity in range(1100, 1000, -1)]

        class FailingClient:
            def __init__(self):
                self.calls = 0

            def list_messages(inner_self, channel_id, before=None):
                inner_self.calls += 1
                if inner_self.calls == 1:
                    return first_page
                raise DiscordAPIError(0, "Simulated network outage")

        failed = FailingClient()
        with self.assertRaises(DiscordAPIError):
            CaptureService(self.store, failed, ["456"], clock=lambda: self.NOW).capture()
        self.assertEqual(self.store.get_cursor("456"), "900")
        self.assertIsNotNone(self.store.get_message("456", "1100"))
        self.assertEqual(self.store.list_runs("456")[0]["status"], "failed")

        class RecoveredClient:
            def list_messages(inner_self, channel_id, before=None):
                return first_page if before is None else [self.message(1000)]

        result = CaptureService(self.store, RecoveredClient(), ["456"], clock=lambda: self.NOW).capture()
        self.assertEqual(result["status"], "success")
        self.assertEqual(self.store.get_cursor("456"), "1100")
        self.assertEqual(len(self.store.list_messages(channel_id="456")), 102)
        self.assertEqual(len(self.store.get_versions("456", "1100")), 1)

    def test_repeated_page_fails_without_advancing_cursor_or_hanging(self):
        page = [self.message(identity) for identity in range(1100, 1000, -1)]

        class RepeatedPageClient:
            calls = 0

            def list_messages(inner_self, channel_id, before=None):
                inner_self.calls += 1
                if inner_self.calls > 3:
                    raise AssertionError("Pagination did not stop")
                return page

        client = RepeatedPageClient()
        with self.assertRaises(DiscordAPIError):
            CaptureService(self.store, client, ["456"], clock=lambda: self.NOW).capture()
        self.assertEqual(client.calls, 2)
        self.assertEqual(self.store.get_cursor("456"), "900")
        self.assertEqual(self.store.list_runs("456")[0]["status"], "failed")

    def test_forbidden_first_channel_does_not_skip_later_readable_channel(self):
        calls = []
        recovered = self.message(1200)
        recovered["channel_id"] = "789"

        class PartlyReadableClient:
            def list_messages(inner_self, channel_id, before=None):
                calls.append(channel_id)
                if channel_id == "456":
                    raise AccessDenied(403, "Fictitious missing access")
                return [recovered]

        result = CaptureService(self.store, PartlyReadableClient(), ["456", "789"], clock=lambda: self.NOW).capture()
        self.assertEqual(calls, ["456", "789"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["permission_denied_channels"], ["456"])
        self.assertEqual(self.store.list_runs("456")[0]["status"], "failed")
        self.assertEqual(self.store.get_cursor("456"), "900")
        self.assertEqual(self.store.list_runs("789")[0]["status"], "success")
        self.assertEqual(self.store.get_cursor("789"), "1200")
        self.assertIsNotNone(self.store.get_message("789", "1200"))

    def test_all_forbidden_channels_are_recorded_before_global_attention(self):
        calls = []

        class ForbiddenClient:
            def list_messages(inner_self, channel_id, before=None):
                calls.append(channel_id)
                raise AccessDenied(403, "Fictitious missing access")

        with self.assertRaises(AccessDenied):
            CaptureService(self.store, ForbiddenClient(), ["456", "789"], clock=lambda: self.NOW).capture()
        self.assertEqual(calls, ["456", "789"])
        self.assertEqual(self.store.list_runs("456")[0]["status"], "failed")
        self.assertEqual(self.store.list_runs("789")[0]["status"], "failed")
        self.assertEqual(self.store.get_cursor("456"), "900")
        self.assertIsNone(self.store.get_cursor("789"))

    def test_unauthorized_still_stops_before_next_channel(self):
        calls = []

        class UnauthorizedClient:
            def list_messages(inner_self, channel_id, before=None):
                calls.append(channel_id)
                raise AuthRequired(401, "Fictitious invalid session")

        with self.assertRaises(AuthRequired):
            CaptureService(self.store, UnauthorizedClient(), ["456", "789"], clock=lambda: self.NOW).capture()
        self.assertEqual(calls, ["456"])
        self.assertEqual(self.store.get_cursor("456"), "900")
        self.assertEqual(self.store.list_runs("789"), [])

    def test_lock_prevents_manual_and_scheduled_services_running_together(self):
        entered, release = threading.Event(), threading.Event()
        thread_errors = []

        class BlockingClient:
            def list_messages(inner_self, channel_id, before=None):
                entered.set()
                if not release.wait(3):
                    raise AssertionError("Test release was not signaled")
                return []

        service = CaptureService(self.store, BlockingClient(), ["456"], clock=lambda: self.NOW)

        def capture():
            try:
                service.capture(trigger="scheduled")
            except Exception as exc:
                thread_errors.append(exc)

        thread = threading.Thread(target=capture, daemon=True)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaises(CaptureBusy):
                CaptureService(self.store, BlockingClient(), ["456"], clock=lambda: self.NOW).capture(trigger="manual")
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(thread_errors, [])


class SchedulerReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(DEFAULT_CONFIG)

    def test_disabled_schedule_does_not_run_even_when_overdue(self):
        self.config["schedule"]["enabled"] = False
        self.assertIsNone(due(self.config, "2026-10-22T19:52:00Z"))

    def test_interval_catches_up_immediately_after_long_outage(self):
        self.config["schedule"]["window"]["enabled"] = False
        key = due(self.config, "2026-10-22T18:00:00Z", "2026-10-21T18:00:00Z")
        self.assertTrue(key.startswith("interval:"))
        self.assertIsNone(due(self.config, "2026-10-22T18:01:00Z", "2026-10-22T18:00:00Z", key))

    def test_market_window_uses_slot_and_suppresses_duplicate(self):
        now = "2026-10-22T19:52:20Z"  # 15:52:20 America/New_York
        slot = due(self.config, now, "2026-10-22T19:45:00Z")
        self.assertEqual(slot, "window:2026-10-22T19:50:00+00:00")
        self.assertIsNone(due(self.config, now, "2026-10-22T19:50:01Z", slot))
        next_slot = due(self.config, "2026-10-22T19:55:00Z", "2026-10-22T19:50:01Z", slot)
        self.assertEqual(next_slot, "window:2026-10-22T19:55:00+00:00")

    def test_market_window_tracks_us_dst_change(self):
        before = due(self.config, "2026-10-30T19:52:00Z", "2026-10-30T19:45:00Z")
        after = due(self.config, "2026-11-02T20:52:00Z", "2026-11-02T20:45:00Z")
        self.assertEqual(before, "window:2026-10-30T19:50:00+00:00")
        self.assertEqual(after, "window:2026-11-02T20:50:00+00:00")

    def test_display_timezone_travel_does_not_move_market_schedule(self):
        keys = []
        for display_zone in ("auto", "Asia/Shanghai", "Asia/Tokyo", "Europe/London"):
            self.config["timezone"] = display_zone
            keys.append(due(self.config, "2026-10-22T19:52:00Z", "2026-10-22T19:45:00Z"))
        self.assertEqual(len(set(keys)), 1)
        self.assertTrue(keys[0].startswith("window:"))

    def test_weekend_window_does_not_trigger(self):
        self.assertIsNone(due(self.config, "2026-10-24T19:52:00Z", "2026-10-24T19:45:00Z"))

    def test_fixed_time_does_not_duplicate_a_recent_manual_save(self):
        self.config["schedule"]["window"]["enabled"] = False
        self.config["schedule"]["times"] = ["15:50"]
        self.assertIsNone(due(self.config, "2026-10-22T19:50:30Z", "2026-10-22T19:50:00Z"))

    def test_market_day_boundary_uses_market_time(self):
        self.assertEqual(market_day("2026-10-23T05:00:00Z"), "2026-10-22")
        self.assertEqual(market_day("2026-10-23T08:00:00Z"), "2026-10-23")

    def test_market_day_bounds_span_23_and_25_hours_at_dst(self):
        spring_start, spring_end = day_bounds("2026-03-07")
        fall_start, fall_end = day_bounds("2026-10-31")
        self.assertEqual((spring_end - spring_start).total_seconds() / 3600, 23)
        self.assertEqual((fall_end - fall_start).total_seconds() / 3600, 25)

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            due(self.config, datetime(2026, 10, 22, 19, 52))


if __name__ == "__main__":
    unittest.main()
