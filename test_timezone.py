# test_timezone_local.py

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(message: str = "") -> MagicMock:
    """Simulates a Teams TurnContext and captures bot replies."""
    activity                    = MagicMock()
    activity.text               = message
    activity.value              = {}
    activity.from_property      = MagicMock()
    activity.from_property.name = "John Smith"

    replies = []

    async def capture(msg):
        text = msg.text if hasattr(msg, "text") else str(msg)
        if text and text != "None":
            replies.append(text)
        print(f"\n    BOT REPLY: {text}")
        if hasattr(msg, "suggested_actions") and msg.suggested_actions:
            titles = [a.title for a in msg.suggested_actions.actions]
            print(f"    BUTTONS  : {titles}")

    context               = MagicMock()
    context.activity      = activity
    context.send_activity = capture
    context._replies      = replies
    return context


# ---------------------------------------------------------------------------
# Test 1 — timezone_service.py (pure logic, no network)
# ---------------------------------------------------------------------------

class TestTimezoneService(unittest.TestCase):
    """Tests get_timezone_command() with no network or N-able needed."""

    def setUp(self):
        from services.timezone_service import get_timezone_command, IANA_TO_WINDOWS
        self.get_cmd      = get_timezone_command
        self.iana_windows = IANA_TO_WINDOWS

    def test_windows_command_tokyo(self):
        result = self.get_cmd("Asia/Tokyo", "windows")
        self.assertNotIn("error", result)
        self.assertIn("tzutil",             result["command"])
        self.assertIn("Tokyo Standard Time", result["command"])
        print(f"\n    Windows Tokyo : {result['command']}")

    def test_windows_command_new_york(self):
        result = self.get_cmd("America/New_York", "windows")
        self.assertNotIn("error", result)
        self.assertIn("Eastern Standard Time", result["command"])
        print(f"\n    Windows NY    : {result['command']}")

    def test_macos_command_tokyo(self):
        result = self.get_cmd("Asia/Tokyo", "macos")
        self.assertNotIn("error", result)
        self.assertIn("systemsetup",  result["command"])
        self.assertIn("Asia/Tokyo",   result["command"])
        print(f"\n    macOS Tokyo   : {result['command']}")

    def test_linux_command_tokyo(self):
        result = self.get_cmd("Asia/Tokyo", "linux")
        self.assertNotIn("error", result)
        self.assertIn("timedatectl", result["command"])
        self.assertIn("Asia/Tokyo",  result["command"])
        print(f"\n    Linux Tokyo   : {result['command']}")

    def test_unknown_iana_returns_error(self):
        result = self.get_cmd("Mars/Olympus_Mons", "windows")
        self.assertIn("error", result)
        print(f"\n    Unknown IANA  : {result['error']}")

    def test_unknown_os_returns_error(self):
        result = self.get_cmd("Asia/Tokyo", "windows95")
        self.assertIn("error", result)
        print(f"\n    Unknown OS    : {result['error']}")

    def test_all_mapped_zones_have_windows_name(self):
        failed = []
        for iana in self.iana_windows:
            result = self.get_cmd(iana, "windows")
            if "error" in result:
                failed.append(iana)
        self.assertEqual(
            [], failed,
            msg=f"These IANA zones have no Windows mapping: {failed}"
        )
        print(f"\n    All {len(self.iana_windows)} IANA zones mapped correctly")


# ---------------------------------------------------------------------------
# Test 2 — rmm_service.change_timezone() with mocked N-able
# ---------------------------------------------------------------------------

class TestRmmChangeTimezone(unittest.TestCase):
    """
    Tests change_timezone() in rmm_service.py with N-able calls mocked.
    No real N-able connection needed.
    """

    def _run(self, fn, *args, **kwargs):
        """Helper to run sync functions."""
        return fn(*args, **kwargs)

    def test_change_timezone_success(self):
        """Mocks device lookup and script run — verifies success response."""
        mock_device = {
            "deviceId": 12345,
            "longName": "DESKTOP-TEST01",
        }

        with patch("services.rmm_service.find_device_by_user", return_value=mock_device), \
             patch("services.rmm_service.run_script",           return_value={"status": "ok"}), \
             patch("services.rmm_service._get_script_output",   return_value="SUCCESS: Timezone changed"), \
             patch("services.rmm_service.CONFIG") as mock_config:

            mock_config.NABLE_SCRIPTS = {"timezone_change": 105}
            mock_config.NABLE_API_KEY = "test-key"
            mock_config.NABLE_BASE_URL = "https://test.n-able.com"

            from services.rmm_service import change_timezone

            result = change_timezone(
                user_name  = "John Smith",
                user_email = "john.smith@itbd.net",
                windows_tz = "Tokyo Standard Time",
                iana_tz    = "Asia/Tokyo",
            )

        print(f"\n    Result  : {result}")
        self.assertTrue(result["success"])
        self.assertEqual(result["device"],     "DESKTOP-TEST01")
        self.assertEqual(result["iana_tz"],    "Asia/Tokyo")
        self.assertEqual(result["windows_tz"], "Tokyo Standard Time")
        self.assertIn("Tokyo", result["message"])

    def test_change_timezone_device_not_found(self):
        """Verifies graceful error when device is not found."""
        with patch("services.rmm_service.find_device_by_user",
                   side_effect=Exception("No device found for user")):

            from services.rmm_service import change_timezone

            result = change_timezone(
                user_name  = "Unknown User",
                user_email = "unknown@itbd.net",
                windows_tz = "Tokyo Standard Time",
                iana_tz    = "Asia/Tokyo",
            )

        print(f"\n    Result  : {result}")
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_change_timezone_script_not_configured(self):
        """Verifies mock mode when script ID is 0."""
        mock_device = {
            "deviceId": 12345,
            "longName": "DESKTOP-TEST01",
        }

        with patch("services.rmm_service.find_device_by_user", return_value=mock_device), \
             patch("services.rmm_service.run_script",           return_value={"mock": True}), \
             patch("services.rmm_service._get_script_output",   return_value=""), \
             patch("services.rmm_service.CONFIG") as mock_config:

            mock_config.NABLE_SCRIPTS  = {"timezone_change": 0}
            mock_config.NABLE_API_KEY  = "test-key"
            mock_config.NABLE_BASE_URL = "https://test.n-able.com"

            from services.rmm_service import change_timezone

            result = change_timezone(
                user_name  = "John Smith",
                user_email = "john.smith@itbd.net",
                windows_tz = "Tokyo Standard Time",
                iana_tz    = "Asia/Tokyo",
            )

        print(f"\n    Result  : {result}")
        self.assertTrue(result.get("_mock"))
        self.assertIn("MOCK", result["message"])

    def test_change_timezone_script_run_fails(self):
        """Verifies graceful error when N-able script execution fails."""
        mock_device = {
            "deviceId": 12345,
            "longName": "DESKTOP-TEST01",
        }

        with patch("services.rmm_service.find_device_by_user", return_value=mock_device), \
             patch("services.rmm_service.run_script",
                   side_effect=Exception("N-able API returned 500")), \
             patch("services.rmm_service.CONFIG") as mock_config:

            mock_config.NABLE_SCRIPTS  = {"timezone_change": 105}
            mock_config.NABLE_API_KEY  = "test-key"
            mock_config.NABLE_BASE_URL = "https://test.n-able.com"

            from services.rmm_service import change_timezone

            result = change_timezone(
                user_name  = "John Smith",
                user_email = "john.smith@itbd.net",
                windows_tz = "Tokyo Standard Time",
                iana_tz    = "Asia/Tokyo",
            )

        print(f"\n    Result  : {result}")
        self.assertFalse(result["success"])
        self.assertIn("error", result)


# ---------------------------------------------------------------------------
# Test 3 — Full bot conversation flow (mocked OpenAI + N-able)
# ---------------------------------------------------------------------------

class TestFullConversationFlow(unittest.IsolatedAsyncioTestCase):
    """
    Simulates the complete two-turn Teams conversation:
      Turn 1 — user asks for timezone change
      Turn 2 — user says yes to CW ticket
    All external calls mocked.
    """

    def _make_openai_response(self, content: str) -> MagicMock:
        mock_resp         = MagicMock()
        mock_resp.json    = AsyncMock(return_value={
            "choices": [{"message": {"content": content}}]
        })
        return mock_resp

    async def test_turn1_timezone_request(self):
        """User asks to change timezone — bot shows commands and stores pending state."""
        print("\n\n  SCENARIO: Turn 1 — user requests timezone change")
        print("  " + "-" * 50)

        from dialogs.main_dialog import _handle_timezone_request

        openai_payload = json.dumps({
            "found":            True,
            "timezone_iana":    "Asia/Tokyo",
            "timezone_display": "Japan Standard Time (Tokyo)",
            "utc_offset":       "UTC+9",
        })

        context = _make_context("set my timezone to Tokyo")
        conv    = {}

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(
            return_value=self._make_openai_response(openai_payload)
        )
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), \
             patch("dialogs.main_dialog.aiohttp.ClientSession") as mock_session:

            mock_session.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=MagicMock(return_value=mock_ctx))
            )
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            await _handle_timezone_request(
                context, "set my timezone to Tokyo",
                "John Smith", "john.smith@itbd.net", conv
            )

        # Assertions
        self.assertIn("pending_timezone_ticket", conv)
        self.assertIn("Tokyo", conv["pending_timezone_ticket"]["summary"])
        self.assertIn("tzutil", context._replies[0])
        self.assertIn("timedatectl", context._replies[0])
        self.assertIn("systemsetup", context._replies[0])
        print(f"\n    Pending state set: {list(conv.keys())}")
        print("    PASS")

    async def test_turn2_yes_creates_ticket(self):
        print("\n\n  SCENARIO: Turn 2 — user confirms ticket creation")
        print("  " + "-" * 50)

        from dialogs.main_dialog import handle_turn

        conv = {
            "pending_timezone_ticket": {
                "summary":     "Timezone change request — Japan Standard Time (Tokyo)",
                "description": "User: John Smith\nRequested timezone: Asia/Tokyo",
            }
        }

        context     = _make_context("yes")
        mock_ticket = {"id": 9999}

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), \
            patch("dialogs.main_dialog.cw.create_ticket", return_value=mock_ticket):
            await handle_turn(context, conv)

        self.assertNotIn("pending_timezone_ticket", conv)

        # Safe check — join all replies into one string
        all_replies = " ".join(str(r) for r in context._replies)
        self.assertIn("9999", all_replies)

        print(f"\n    Ticket created  : #9999")
        print(f"    Pending cleared : True")
        print("    PASS")


    async def test_turn2_no_clears_state(self):
        print("\n\n  SCENARIO: Turn 2 — user declines ticket")
        print("  " + "-" * 50)

        from dialogs.main_dialog import handle_turn

        conv = {
            "pending_timezone_ticket": {
                "summary":     "Timezone change request — Tokyo",
                "description": "Details here",
            }
        }

        context = _make_context("no thanks")

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), \
            patch("dialogs.main_dialog.cw.create_ticket") as mock_cw:
            await handle_turn(context, conv)
            mock_cw.assert_not_called()

        self.assertNotIn("pending_timezone_ticket", conv)
        print(f"\n    Ticket created  : False (correct)")
        print(f"    Pending cleared : True")
        print("    PASS")


    async def test_full_two_turn_flow(self):
        print("\n\n  SCENARIO: Full two-turn flow")
        print("  " + "-" * 50)

        from dialogs.main_dialog import handle_turn

        openai_payload = json.dumps({
            "found":            True,
            "timezone_iana":    "America/New_York",
            "timezone_display": "Eastern Time (New York)",
            "utc_offset":       "UTC-5 / UTC-4 DST",
        })

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(
            return_value=MagicMock(
                json=AsyncMock(return_value={
                    "choices": [{"message": {"content": openai_payload}}]
                })
            )
        )
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        conv = {}

        # Turn 1
        print("\n    Turn 1: set my timezone to New York")
        context_1 = _make_context("set my timezone to New York")

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), \
             patch("dialogs.main_dialog.aiohttp.ClientSession") as mock_session:

            mock_session.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(
                    post=MagicMock(return_value=mock_ctx)
                )
            )
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            await handle_turn(context_1, conv)

        self.assertIn("pending_timezone_ticket", conv)

        # Turn 2
        print("\n    Turn 2: yes")
        context_2   = _make_context("yes")
        mock_ticket = {"id": 5050}

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), \
             patch("dialogs.main_dialog.cw.create_ticket", return_value=mock_ticket):
            await handle_turn(context_2, conv)

        self.assertNotIn("pending_timezone_ticket", conv)

        # Safe assertion
        all_replies = " ".join(str(r) for r in context_2._replies)
        self.assertIn("5050", all_replies)

        print(f"\n    Ticket ID       : #5050")
        print(f"    Pending cleared : True")
        print("    PASS")


# ---------------------------------------------------------------------------
# Test 4 — rmm_service.change_timezone() direct call simulation
# ---------------------------------------------------------------------------

class TestChangeTimezoneDirectCall(unittest.TestCase):
    """
    Simulates calling change_timezone() exactly as the bot would call it
    when a user says 'set my timezone to Tokyo' in Teams.
    """

    def test_simulate_bot_calling_change_timezone(self):
        """
        This is the exact call chain the bot uses:
          orchestrator → execute_tool → rmm.change_timezone()
        """
        print("\n\n  SCENARIO: Bot calls change_timezone directly")
        print("  " + "-" * 50)

        mock_device = {
            "deviceId": 99001,
            "longName": "LAPTOP-JSMITH",
        }

        with patch("services.rmm_service.find_device_by_user", return_value=mock_device), \
             patch("services.rmm_service.run_script",           return_value={"status": "queued"}), \
             patch("services.rmm_service._get_script_output",   return_value="SUCCESS: Timezone changed to Tokyo Standard Time"), \
             patch("services.rmm_service.time.sleep",           return_value=None), \
             patch("services.rmm_service.CONFIG") as mock_config:

            mock_config.NABLE_SCRIPTS  = {"timezone_change": 105}
            mock_config.NABLE_API_KEY  = "test-key"
            mock_config.NABLE_BASE_URL = "https://test.n-able.com"

            from services.rmm_service import change_timezone

            # This is exactly what execute_tool calls in server.py
            result = change_timezone(
                user_name  = "John Smith",
                user_email = "john.smith@itbd.net",
                windows_tz = "Tokyo Standard Time",
                iana_tz    = "Asia/Tokyo",
            )

        print(f"\n    Device     : {result.get('device')}")
        print(f"    IANA TZ    : {result.get('iana_tz')}")
        print(f"    Windows TZ : {result.get('windows_tz')}")
        print(f"    Success    : {result.get('success')}")
        print(f"    Message    : {result.get('message')}")

        self.assertTrue(result["success"])
        self.assertEqual(result["device"],     "LAPTOP-JSMITH")
        self.assertEqual(result["iana_tz"],    "Asia/Tokyo")
        self.assertEqual(result["windows_tz"], "Tokyo Standard Time")
        self.assertIn("Tokyo", result["message"])
        print("    PASS")

    def test_simulate_all_timezones(self):
        """
        Tests change_timezone() for every timezone in IANA_TO_WINDOWS mapping.
        Verifies each one produces a successful result.
        """
        print("\n\n  SCENARIO: Test all timezone mappings")
        print("  " + "-" * 50)

        from services.timezone_service import IANA_TO_WINDOWS

        mock_device = {
            "deviceId": 99001,
            "longName": "LAPTOP-JSMITH",
        }

        failed = []

        with patch("services.rmm_service.find_device_by_user", return_value=mock_device), \
             patch("services.rmm_service.run_script",           return_value={"status": "ok"}), \
             patch("services.rmm_service._get_script_output",   return_value="SUCCESS"), \
             patch("services.rmm_service.time.sleep",           return_value=None), \
             patch("services.rmm_service.CONFIG") as mock_config:

            mock_config.NABLE_SCRIPTS  = {"timezone_change": 105}
            mock_config.NABLE_API_KEY  = "test-key"
            mock_config.NABLE_BASE_URL = "https://test.n-able.com"

            from services.rmm_service import change_timezone

            for iana, windows in IANA_TO_WINDOWS.items():
                result = change_timezone(
                    user_name  = "John Smith",
                    user_email = "john.smith@itbd.net",
                    windows_tz = windows,
                    iana_tz    = iana,
                )
                if not result.get("success"):
                    failed.append(iana)
                else:
                    print(f"    OK  {iana}")

        self.assertEqual(
            [], failed,
            msg=f"These timezones failed: {failed}"
        )
        print(f"\n    All {len(IANA_TO_WINDOWS)} timezones passed")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 60)
    print("TIMEZONE CHANGE — LOCAL TEST SUITE")
    print("=" * 60)
    print("No Teams, no N-able, no network required.")
    print("All external calls are mocked.\n")

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestTimezoneService))
    suite.addTests(loader.loadTestsFromTestCase(TestRmmChangeTimezone))
    suite.addTests(loader.loadTestsFromTestCase(TestFullConversationFlow))
    suite.addTests(loader.loadTestsFromTestCase(TestChangeTimezoneDirectCall))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print(f"ALL {result.testsRun} TESTS PASSED")
        print("Your timezone change function is working correctly.")
        print("Ready to test live in Teams.")
    else:
        print(f"{len(result.failures)} FAILED  "
              f"{len(result.errors)} ERRORS  "
              f"{result.testsRun} TOTAL")
        print("Fix the failures above before testing in Teams.")
    print("=" * 60)


if __name__ == "__main__":
    main()