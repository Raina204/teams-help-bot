# tests/test_timezone.py

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.timezone_service import IANA_TO_WINDOWS, get_timezone_command


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_openai_response(payload: dict) -> MagicMock:
    mock_resp      = MagicMock()
    mock_resp.json = AsyncMock(return_value={
        "choices": [{"message": {"content": json.dumps(payload)}}]
    })
    return mock_resp


def _make_turn_context(message: str = "") -> MagicMock:
    activity                     = MagicMock()
    activity.text                = message
    activity.value               = {}
    activity.from_property       = MagicMock()
    activity.from_property.name  = "John Smith"

    context               = MagicMock()
    context.activity      = activity
    context.send_activity = AsyncMock()
    return context


# ---------------------------------------------------------------------------
# 1. timezone_service — unit tests
# ---------------------------------------------------------------------------

class TestGetTimezoneCommand(unittest.TestCase):

    def test_windows_new_york(self):
        result = get_timezone_command("America/New_York", "windows")
        self.assertNotIn("error", result)
        self.assertIn("Eastern Standard Time", result["command"])
        self.assertIn("tzutil", result["command"])

    def test_windows_tokyo(self):
        result = get_timezone_command("Asia/Tokyo", "windows")
        self.assertNotIn("error", result)
        self.assertIn("Tokyo Standard Time", result["command"])

    def test_windows_utc(self):
        result = get_timezone_command("UTC", "windows")
        self.assertNotIn("error", result)
        self.assertIn("UTC", result["command"])

    def test_windows_unknown_iana(self):
        result = get_timezone_command("Mars/Olympus_Mons", "windows")
        self.assertIn("error", result)

    def test_macos_london(self):
        result = get_timezone_command("Europe/London", "macos")
        self.assertNotIn("error", result)
        self.assertIn("Europe/London", result["command"])
        self.assertIn("systemsetup", result["command"])

    def test_macos_kolkata(self):
        result = get_timezone_command("Asia/Kolkata", "macos")
        self.assertNotIn("error", result)
        self.assertIn("Asia/Kolkata", result["command"])

    def test_linux_sydney(self):
        result = get_timezone_command("Australia/Sydney", "linux")
        self.assertNotIn("error", result)
        self.assertIn("Australia/Sydney", result["command"])
        self.assertIn("timedatectl", result["command"])

    def test_linux_sao_paulo(self):
        result = get_timezone_command("America/Sao_Paulo", "linux")
        self.assertNotIn("error", result)
        self.assertIn("America/Sao_Paulo", result["command"])

    def test_unknown_os(self):
        result = get_timezone_command("America/New_York", "windows95")
        self.assertIn("error", result)

    def test_os_name_is_case_insensitive(self):
        lower = get_timezone_command("Asia/Tokyo", "linux")
        upper = get_timezone_command("Asia/Tokyo", "LINUX")
        mixed = get_timezone_command("Asia/Tokyo", "Linux")
        self.assertEqual(lower.get("command"), upper.get("command"))
        self.assertEqual(lower.get("command"), mixed.get("command"))

    def test_all_mapped_iana_zones_resolve_on_windows(self):
        for iana in IANA_TO_WINDOWS:
            with self.subTest(iana=iana):
                result = get_timezone_command(iana, "windows")
                self.assertNotIn("error", result)

    def test_all_mapped_iana_zones_resolve_on_macos(self):
        for iana in IANA_TO_WINDOWS:
            with self.subTest(iana=iana):
                result = get_timezone_command(iana, "macos")
                self.assertNotIn("error", result)
                self.assertIn(iana, result["command"])

    def test_all_mapped_iana_zones_resolve_on_linux(self):
        for iana in IANA_TO_WINDOWS:
            with self.subTest(iana=iana):
                result = get_timezone_command(iana, "linux")
                self.assertNotIn("error", result)
                self.assertIn(iana, result["command"])

    def test_result_contains_required_keys(self):
        result = get_timezone_command("Asia/Tokyo", "windows")
        for key in ("command", "label", "note", "iana", "os"):
            self.assertIn(key, result)

    def test_iana_and_os_echoed_in_result(self):
        result = get_timezone_command("Asia/Tokyo", "macos")
        self.assertEqual(result["iana"], "Asia/Tokyo")
        self.assertEqual(result["os"],   "macos")


# ---------------------------------------------------------------------------
# 2. Intent detection — unit tests
# ---------------------------------------------------------------------------

class TestDetectIntent(unittest.TestCase):

    def setUp(self):
        from dialogs.main_dialog import detect_intent
        self.detect = detect_intent

    def test_timezone_keywords(self):
        cases = [
            "set my timezone to Tokyo",
            "change timezone to EST",
            "my clock is wrong",
            "change my time zone",
            "set timezone to UTC",
            "I need to change to PST",
            "wrong time on my device",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(self.detect(text), "CHANGE_TIMEZONE")

    def test_create_ticket_keywords(self):
        cases = ["I have an issue", "create ticket", "log a support ticket", "something is broken"]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(self.detect(text), "CREATE_TICKET")

    def test_diagnostics_keywords(self):
        cases = ["my pc is slow", "run diagnostics", "check cpu", "memory issue"]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(self.detect(text), "RUN_DIAGNOSTICS")

    def test_outlook_keywords(self):
        cases = ["fix my outlook", "reset outlook", "email not working", "ost file"]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(self.detect(text), "RESET_OUTLOOK")

    def test_main_menu_keywords(self):
        cases = ["hello", "hi", "help", "menu", "start"]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(self.detect(text), "MAIN_MENU")

    def test_unknown_returns_unknown(self):
        cases = ["what is the weather", "tell me a joke", ""]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(self.detect(text), "UNKNOWN")

    def test_case_insensitive(self):
        self.assertEqual(self.detect("SET MY TIMEZONE TO TOKYO"), "CHANGE_TIMEZONE")
        self.assertEqual(self.detect("Set My TimeZone To Tokyo"), "CHANGE_TIMEZONE")

    def test_empty_and_none(self):
        self.assertEqual(self.detect(""),   "UNKNOWN")
        self.assertEqual(self.detect(None), "UNKNOWN")


# ---------------------------------------------------------------------------
# 3. Timezone request handler — integration tests
# ---------------------------------------------------------------------------

class TestHandleTimezoneRequest(unittest.IsolatedAsyncioTestCase):

    async def _run(self, user_text: str, openai_payload: dict,
                   conversation_data: dict = None):
        from dialogs.main_dialog import _handle_timezone_request

        context  = _make_turn_context(user_text)
        conv     = conversation_data if conversation_data is not None else {}
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=_make_openai_response(openai_payload))
        mock_ctx.__aexit__  = AsyncMock(return_value=False)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch("dialogs.main_dialog.aiohttp.ClientSession") as mock_session:
                mock_session.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                    post=MagicMock(return_value=mock_ctx)
                ))
                mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

                await _handle_timezone_request(
                    context, user_text, "John Smith", "john.smith@itbd.net", conv
                )

        return context, conv

    async def test_valid_timezone_sends_response(self):
        payload = {
            "found":            True,
            "timezone_iana":    "America/New_York",
            "timezone_display": "Eastern Time (New York)",
            "utc_offset":       "UTC-5 / UTC-4 DST",
        }
        context, _ = await self._run("set my timezone to New York", payload)
        context.send_activity.assert_called_once()
        response = context.send_activity.call_args[0][0]
        text     = response.text if hasattr(response, "text") else str(response)
        self.assertIn("Eastern Time (New York)", text)
        self.assertIn("America/New_York",        text)
        self.assertIn("tzutil",                  text)
        self.assertIn("timedatectl",             text)
        self.assertIn("systemsetup",             text)

    async def test_valid_timezone_persists_pending_state(self):
        payload = {
            "found":            True,
            "timezone_iana":    "Asia/Tokyo",
            "timezone_display": "Japan Standard Time (Tokyo)",
            "utc_offset":       "UTC+9",
        }
        _, conv = await self._run("change timezone to Tokyo", payload)
        self.assertIn("pending_timezone_ticket", conv)
        self.assertIn("Tokyo", conv["pending_timezone_ticket"]["summary"])
        self.assertIn("Asia/Tokyo", conv["pending_timezone_ticket"]["description"])
        self.assertIn("john.smith@itbd.net", conv["pending_timezone_ticket"]["description"])

    async def test_valid_timezone_attaches_suggested_actions(self):
        payload = {
            "found":            True,
            "timezone_iana":    "Europe/London",
            "timezone_display": "GMT (London)",
            "utc_offset":       "UTC+0 / UTC+1 BST",
        }
        context, _ = await self._run("set timezone to London", payload)
        response   = context.send_activity.call_args[0][0]
        self.assertIsNotNone(response.suggested_actions)
        titles = [a.title for a in response.suggested_actions.actions]
        self.assertIn("Yes, log a ticket", titles)
        self.assertIn("No, thank you",     titles)

    async def test_unrecognised_timezone_sends_error_message(self):
        payload = {"found": False, "message": "Could not identify a timezone."}
        context, conv = await self._run("please fix my time thingy", payload)
        context.send_activity.assert_called_once()
        response = str(context.send_activity.call_args[0][0])
        self.assertIn("Could not identify", response)

    async def test_unrecognised_timezone_does_not_persist_state(self):
        payload = {"found": False, "message": "Timezone not found."}
        _, conv = await self._run("gibberish timezone", payload)
        self.assertNotIn("pending_timezone_ticket", conv)

    async def test_yes_reply_creates_connectwise_ticket(self):
        from dialogs.main_dialog import handle_turn

        conv = {
            "pending_timezone_ticket": {
                "summary":     "Timezone change request — Eastern Time (New York)",
                "description": "User: John Smith\nRequested: America/New_York",
            }
        }
        context     = _make_turn_context("yes")
        mock_ticket = {"id": 9001}

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with patch("dialogs.main_dialog.cw.create_ticket", return_value=mock_ticket):
                await handle_turn(context, conv)

        self.assertNotIn("pending_timezone_ticket", conv)
        calls = [str(c) for c in context.send_activity.call_args_list]
        self.assertTrue(any("9001" in c for c in calls))

    async def test_no_reply_clears_pending_state(self):
        from dialogs.main_dialog import handle_turn

        conv = {
            "pending_timezone_ticket": {
                "summary":     "Timezone change request — Tokyo",
                "description": "User: John Smith",
            }
        }
        context = _make_turn_context("no thanks")

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with patch("dialogs.main_dialog.cw.create_ticket") as mock_cw:
                await handle_turn(context, conv)
                mock_cw.assert_not_called()

        self.assertNotIn("pending_timezone_ticket", conv)

    async def test_unrelated_reply_clears_pending_state_and_reroutes(self):
        from dialogs.main_dialog import handle_turn

        conv = {
            "pending_timezone_ticket": {
                "summary":     "Timezone change request",
                "description": "Some details",
            }
        }
        context = _make_turn_context("hello")

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with patch("dialogs.main_dialog.cw.create_ticket") as mock_cw:
                with patch("dialogs.main_dialog._handle_main_menu",
                           new_callable=AsyncMock) as mock_menu:
                    await handle_turn(context, conv)
                    mock_cw.assert_not_called()
                    mock_menu.assert_called_once()

        self.assertNotIn("pending_timezone_ticket", conv)

    async def test_yes_variants_all_trigger_ticket_creation(self):
        from dialogs.main_dialog import handle_turn

        yes_variants = [
            "yes", "yeah", "yep", "sure", "ok", "okay",
            "yes please", "create ticket", "log ticket",
        ]
        for variant in yes_variants:
            with self.subTest(variant=variant):
                conv = {
                    "pending_timezone_ticket": {
                        "summary":     "Timezone change request",
                        "description": "Details",
                    }
                }
                context = _make_turn_context(variant)

                with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                    with patch("dialogs.main_dialog.cw.create_ticket",
                               return_value={"id": 1}):
                        await handle_turn(context, conv)

                self.assertNotIn(
                    "pending_timezone_ticket", conv,
                    msg=f"Pending state not cleared for variant: '{variant}'"
                )

    async def test_ticket_creation_failure_sends_error_message(self):
        from dialogs.main_dialog import handle_turn

        conv = {
            "pending_timezone_ticket": {
                "summary":     "Timezone change request",
                "description": "Details",
            }
        }
        context = _make_turn_context("yes")

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with patch("dialogs.main_dialog.cw.create_ticket",
                       side_effect=Exception("ConnectWise API unavailable")):
                await handle_turn(context, conv)

        calls = [str(c) for c in context.send_activity.call_args_list]
        self.assertTrue(
            any("could not be created" in c.lower() or "error" in c.lower() for c in calls)
        )

    async def test_openai_network_failure_sends_error_message(self):
        from dialogs.main_dialog import _handle_timezone_request

        context = _make_turn_context("set timezone to Tokyo")
        conv    = {}

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch("dialogs.main_dialog.aiohttp.ClientSession") as mock_session:
                mock_session.return_value.__aenter__ = AsyncMock(
                    side_effect=Exception("Network unreachable")
                )
                mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
                await _handle_timezone_request(
                    context, "set timezone to Tokyo",
                    "John Smith", "john.smith@itbd.net", conv
                )

        context.send_activity.assert_called_once()
        response = str(context.send_activity.call_args[0][0])
        self.assertIn("failed", response.lower())
        self.assertNotIn("pending_timezone_ticket", conv)


# ---------------------------------------------------------------------------
# 4. End-to-end flow test
# ---------------------------------------------------------------------------

class TestTimezoneEndToEnd(unittest.IsolatedAsyncioTestCase):

    async def test_full_two_turn_flow(self):
        from dialogs.main_dialog import handle_turn

        openai_payload = {
            "found":            True,
            "timezone_iana":    "America/Chicago",
            "timezone_display": "Central Time (Chicago)",
            "utc_offset":       "UTC-6 / UTC-5 DST",
        }

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(
            return_value=_make_openai_response(openai_payload)
        )
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        conv = {}

        # Turn 1: user requests timezone change
        context_1 = _make_turn_context("set my timezone to Chicago")

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with patch("dialogs.main_dialog.aiohttp.ClientSession") as mock_session:
                mock_session.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                    post=MagicMock(return_value=mock_ctx)
                ))
                mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
                await handle_turn(context_1, conv)

        self.assertIn("pending_timezone_ticket", conv)
        response_1 = context_1.send_activity.call_args[0][0]
        self.assertIn("Central Time (Chicago)", response_1.text)

        # Turn 2: user confirms with "yes"
        context_2   = _make_turn_context("yes")
        mock_ticket = {"id": 5050}

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with patch("dialogs.main_dialog.cw.create_ticket", return_value=mock_ticket):
                await handle_turn(context_2, conv)

        self.assertNotIn("pending_timezone_ticket", conv)
        response_2 = str(context_2.send_activity.call_args[0][0])
        self.assertIn("5050", response_2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)