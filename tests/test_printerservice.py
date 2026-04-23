"""
tests/test_printer_service.py
─────────────────────────────────────────────────────────────────────────────
Run with:   pytest tests/test_printer_service.py -v
─────────────────────────────────────────────────────────────────────────────
All tests run in MOCK mode (no N-able credentials needed).
"""

import pytest
import sys
import os

# Make sure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force mock mode — no real N-able token
os.environ.pop("NABLE_JWT_TOKEN", None)
os.environ["NABLE_CUSTOMER_MAP"] = "itbd.net:1118,testcorp.com:9999"

from services.printer_service import (
    restart_print_spooler,
    check_printer_status,
    clear_print_queue,
    list_printers,
)


class TestRestartPrintSpooler:
    def test_returns_success(self):
        result = restart_print_spooler("user@itbd.net")
        assert result["success"] is True

    def test_output_contains_success_keyword(self):
        result = restart_print_spooler("user@itbd.net")
        assert "SUCCESS" in result["output"]

    def test_mock_flag_set(self):
        result = restart_print_spooler("user@itbd.net")
        assert result.get("mock") is True

    def test_hostname_present(self):
        result = restart_print_spooler("user@itbd.net")
        assert "hostname" in result and result["hostname"]


class TestCheckPrinterStatus:
    def test_returns_success(self):
        result = check_printer_status("user@testcorp.com")
        assert result["success"] is True

    def test_output_contains_spooler_status(self):
        result = check_printer_status("user@testcorp.com")
        assert "Spooler" in result["output"]

    def test_output_contains_printer_info(self):
        result = check_printer_status("user@testcorp.com")
        assert "Printer" in result["output"]

    def test_mock_flag_set(self):
        result = check_printer_status("user@testcorp.com")
        assert result.get("mock") is True


class TestClearPrintQueue:
    def test_returns_success(self):
        result = clear_print_queue("user@itbd.net")
        assert result["success"] is True

    def test_output_mentions_cleared(self):
        result = clear_print_queue("user@itbd.net")
        assert "Cleared" in result["output"] or "cleared" in result["output"]

    def test_mock_flag_set(self):
        result = clear_print_queue("user@itbd.net")
        assert result.get("mock") is True


class TestListPrinters:
    def test_returns_success(self):
        result = list_printers("user@itbd.net")
        assert result["success"] is True

    def test_output_contains_printer_list(self):
        result = list_printers("user@itbd.net")
        assert "Printers" in result["output"] or "Printer" in result["output"]

    def test_mock_flag_set(self):
        result = list_printers("user@itbd.net")
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
