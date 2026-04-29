"""
tests/test_printer_service.py
─────────────────────────────────────────────────────────────────────────────
Run with:   pytest tests/test_printer_service.py -v
─────────────────────────────────────────────────────────────────────────────
All tests run in MOCK mode (no ConnectWise Automate credentials needed).
"""

import pytest
import sys
import os

# Make sure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.printer_service import (
    restart_spooler,
    check_printer_status,
    clear_queue,
    list_printers,
)

MOCK_TENANT = {
    "tenant_id":       "test",
    "cwa_client_id":   "1",
    "cwa_api_key_ref": "TEST_KEY",
    "printer_sites":   ["Main Office"],
    "mock":            True,
}


class TestRestartPrintSpooler:
    def test_returns_success(self):
        result = restart_spooler("user@itbd.net", MOCK_TENANT)
        assert result["success"] is True

    def test_output_contains_success_keyword(self):
        result = restart_spooler("user@itbd.net", MOCK_TENANT)
        assert "SUCCESS" in result["output"]

    def test_mock_flag_set(self):
        result = restart_spooler("user@itbd.net", MOCK_TENANT)
        assert result.get("mock") is True

    def test_hostname_present(self):
        result = restart_spooler("user@itbd.net", MOCK_TENANT)
        assert "hostname" in result and result["hostname"]


class TestCheckPrinterStatus:
    def test_returns_success(self):
        result = check_printer_status("user@itbd.net", MOCK_TENANT)
        assert result["success"] is True

    def test_output_contains_spooler_status(self):
        result = check_printer_status("user@itbd.net", MOCK_TENANT)
        assert "Spooler" in result["output"]

    def test_output_contains_printer_info(self):
        result = check_printer_status("user@itbd.net", MOCK_TENANT)
        assert "Printer" in result["output"]

    def test_mock_flag_set(self):
        result = check_printer_status("user@itbd.net", MOCK_TENANT)
        assert result.get("mock") is True


class TestClearPrintQueue:
    def test_returns_success(self):
        result = clear_queue("user@itbd.net", MOCK_TENANT)
        assert result["success"] is True

    def test_output_mentions_cleared(self):
        result = clear_queue("user@itbd.net", MOCK_TENANT)
        assert "Cleared" in result["output"] or "cleared" in result["output"]

    def test_mock_flag_set(self):
        result = clear_queue("user@itbd.net", MOCK_TENANT)
        assert result.get("mock") is True


class TestListPrinters:
    def test_returns_success(self):
        result = list_printers("user@itbd.net", MOCK_TENANT)
        assert result["success"] is True

    def test_output_contains_printer_list(self):
        result = list_printers("user@itbd.net", MOCK_TENANT)
        assert "Printers" in result["output"] or "Printer" in result["output"]

    def test_mock_flag_set(self):
        result = list_printers("user@itbd.net", MOCK_TENANT)
        assert result.get("mock") is True


class TestIntentDetection:
    """Verify the new intents are correctly matched in main_dialog."""

    def setup_method(self):
        from dialogs.main_dialog_printer_update import detect_intent
        self.detect = detect_intent

    def test_printer_status_detected(self):
        assert self.detect("my printer is not working") == "PRINTER_STATUS"

    def test_restart_spooler_detected(self):
        assert self.detect("restart print spooler") == "RESTART_SPOOLER"

    def test_cant_print_maps_to_restart(self):
        assert self.detect("I can't print anything today") == "RESTART_SPOOLER"

    def test_clear_queue_detected(self):
        assert self.detect("clear print queue please") == "CLEAR_PRINT_QUEUE"

    def test_list_printers_detected(self):
        assert self.detect("list my printers") == "LIST_PRINTERS"

    def test_existing_outlook_still_works(self):
        assert self.detect("fix my outlook") == "RESET_OUTLOOK"

    def test_existing_diagnostics_still_works(self):
        assert self.detect("my pc is slow") == "RUN_DIAGNOSTICS"
