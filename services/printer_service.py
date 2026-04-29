"""
services/printer_service.py
────────────────────────────────────────────────────────────────────────────
Printer Spooler Service — multi-tenant aware.

Integrates with ConnectWise Automate (CWA) RMM to manage the Windows Print
Spooler on a user's machine. Every public function accepts tenant_ctx as its
last argument.

Capabilities
------------
  • restart_spooler(user_email, tenant_ctx)       — stops spooler, clears stuck jobs, restarts
  • check_printer_status(user_email, tenant_ctx)  — reports spooler state + queued jobs
  • clear_queue(user_email, tenant_ctx)           — clears stuck jobs without restart
  • list_printers(user_email, tenant_ctx)         — lists all printers installed on device

Per-tenant values used from tenant_ctx:
  - cwa_api_key_ref   → resolved via get_secret() to the CWA Bearer token
  - cwa_base_url      → this tenant's ConnectWise Automate server URL
  - printer_sites     → list of permitted printer sites for this tenant
  - mock              → True = always use mock responses (no real API calls)

Scripts must be pre-created in ConnectWise Automate and their IDs set in .env:
  CWA_SCRIPT_PRINTER_RESTART
  CWA_SCRIPT_PRINTER_STATUS
  CWA_SCRIPT_PRINTER_CLEAR_QUEUE
  CWA_SCRIPT_PRINTER_LIST
"""

import logging
from datetime import datetime

import requests

from config.config import CONFIG
from config.secrets import get_secret
from services.rmm_service import _get_headers, _get_base_url

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _use_mock(tenant_ctx: dict) -> bool:
    """
    Return True if mock mode should be used for this tenant.

    Mock mode is active when:
      - tenant_ctx["mock"] is True, OR
      - tenant_ctx["cwa_mock"] is True, OR
      - the tenant's CWA API token resolves to empty/placeholder
    """
    if tenant_ctx.get("mock") or tenant_ctx.get("cwa_mock"):
        return True
    try:
        token = get_secret(tenant_ctx["cwa_api_key_ref"])
        return not token or token.startswith("mock-")
    except Exception:
        return True


def _find_device(user_email: str, tenant_ctx: dict) -> dict | None:
    """
    Look up the user's device in this tenant's ConnectWise Automate instance.

    CWA endpoint: GET /cwa/api/v1/computers?condition=LastLoggedInUser like '%{user}%'

    Returns:
        Computer dict with at least {'Id': ..., 'ComputerName': ...}, or None.
    """
    base_url = _get_base_url(tenant_ctx)
    username = user_email.split("@")[0]

    try:
        resp = requests.get(
            f"{base_url}/cwa/api/v1/computers",
            headers=_get_headers(tenant_ctx),
            params={"condition": f"LastLoggedInUser like '%{username}%'", "pageSize": 50},
            timeout=15,
        )
        resp.raise_for_status()

        computers = resp.json()
        if isinstance(computers, dict):
            computers = computers.get("data", [])

        lower_user = username.lower()

        def _strip_domain(raw: str) -> str:
            raw = (raw or "").lower()
            return raw.split("\\")[-1] if "\\" in raw else raw

        for c in computers:
            if lower_user == _strip_domain(c.get("LastLoggedInUser", "")):
                return c
        for c in computers:
            if lower_user in _strip_domain(c.get("LastLoggedInUser", "")):
                return c
        for c in computers:
            if lower_user.split(".")[0] in _strip_domain(c.get("LastLoggedInUser", "")):
                return c

        return None

    except Exception as exc:
        logger.error(
            "[PrinterService] Device lookup failed — tenant=%s error=%s",
            tenant_ctx.get("tenant_id"), exc,
        )
        return None


def _run_script(
    device_id: int,
    script_id: int,
    tenant_ctx: dict,
) -> dict:
    """
    Run a ConnectWise Automate script on device_id.

    CWA endpoint: POST /cwa/api/v1/computers/{computerId}/scripts/{scriptId}

    Args:
        device_id:   CWA computer ID.
        script_id:   CWA script ID from .env.
        tenant_ctx:  Resolved tenant config dict.

    Returns:
        Dict with 'success' (bool) and 'output' (str).
    """
    if not script_id:
        return {"success": False, "output": "Script ID not configured."}

    base_url = _get_base_url(tenant_ctx)

    try:
        resp = requests.post(
            f"{base_url}/cwa/api/v1/computers/{device_id}/scripts/{script_id}",
            headers=_get_headers(tenant_ctx),
            timeout=20,
        )
        resp.raise_for_status()
        return {"success": True, "output": "Script queued successfully."}

    except Exception as exc:
        logger.error(
            "[PrinterService] Script execution error — tenant=%s script=%s error=%s",
            tenant_ctx.get("tenant_id"), script_id, exc,
        )
        return {"success": False, "output": str(exc)}


# ── Mock responses ────────────────────────────────────────────────────────────

def _mock_restart_spooler(tenant_ctx: dict) -> dict:
    tid = tenant_ctx.get("tenant_id", "mock").upper()
    return {
        "success":  True,
        "hostname": f"MOCK-PC-{tid}-001",
        "output": (
            "=== Print Spooler Restart ===\n"
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "Stopping Print Spooler service...\n"
            "Cleared 3 stuck print job(s).\n"
            "Print Spooler status: Running\n"
            "SUCCESS: Print Spooler restarted successfully."
        ),
        "tenant_id": tenant_ctx.get("tenant_id"),
        "mock":      True,
    }


def _mock_check_status(tenant_ctx: dict) -> dict:
    tid   = tenant_ctx.get("tenant_id", "mock").upper()
    sites = tenant_ctx.get("printer_sites", ["Office"])
    site  = sites[0] if sites else "Office"
    return {
        "success":  True,
        "hostname": f"MOCK-PC-{tid}-001",
        "output": (
            "=== Printer Status Report ===\n"
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "Spooler Service: Running\n"
            "Stuck Jobs in Spool: 0\n\n"
            "--- Installed Printers ---\n"
            f"Printer: {site} HP LaserJet Pro | Status: Normal | Driver: HP LaserJet Pro\n"
            "Printer: Microsoft Print to PDF | Status: Normal | Driver: Microsoft Print To PDF"
        ),
        "tenant_id": tenant_ctx.get("tenant_id"),
        "mock":      True,
    }


def _mock_clear_queue(tenant_ctx: dict) -> dict:
    tid = tenant_ctx.get("tenant_id", "mock").upper()
    return {
        "success":  True,
        "hostname": f"MOCK-PC-{tid}-001",
        "output":   "Cleared 2 print job(s). Spooler restarted.\nSpooler status: Running",
        "tenant_id": tenant_ctx.get("tenant_id"),
        "mock":      True,
    }


def _mock_list_printers(tenant_ctx: dict) -> dict:
    tid   = tenant_ctx.get("tenant_id", "mock").upper()
    sites = tenant_ctx.get("printer_sites", ["Office"])

    printer_lines = []
    for site in sites:
        printer_lines.append(
            f"Name: {site} HP LaserJet Pro\n"
            "  Status : Normal\n"
            "  Driver : HP LaserJet Pro M402-M403 PCL 6\n"
            "  Port   : 192.168.1.50\n"
            "  Shared : False\n---"
        )
    printer_lines.append(
        "Name: Microsoft Print to PDF\n"
        "  Status : Normal\n"
        "  Driver : Microsoft Print To PDF\n"
        "  Port   : PORTPROMPT:\n"
        "  Shared : False\n---"
    )

    return {
        "success":  True,
        "hostname": f"MOCK-PC-{tid}-001",
        "output":   "=== Installed Printers ===\n" + "\n".join(printer_lines),
        "printers": [f"{s} HP LaserJet Pro" for s in sites] + ["Microsoft Print to PDF"],
        "tenant_id": tenant_ctx.get("tenant_id"),
        "mock":      True,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def restart_spooler(user_email: str, tenant_ctx: dict) -> dict:
    """
    Restart the Windows Print Spooler on the user's machine via ConnectWise Automate.

    Requires CWA_SCRIPT_PRINTER_RESTART to be set in .env.
    """
    if _use_mock(tenant_ctx):
        logger.info("[PrinterService] Mock mode — restart_spooler tenant=%s", tenant_ctx.get("tenant_id"))
        return _mock_restart_spooler(tenant_ctx)

    device = _find_device(user_email, tenant_ctx)
    if not device:
        return {
            "success": False,
            "output":  f"Could not find device for {user_email} in tenant '{tenant_ctx.get('tenant_id')}'.",
        }

    result = _run_script(device["Id"], CONFIG.CWA_SCRIPTS.get("printer_restart", 0), tenant_ctx)
    result["hostname"]  = device.get("ComputerName", "Unknown")
    result["tenant_id"] = tenant_ctx.get("tenant_id")
    return result


def check_printer_status(user_email: str, tenant_ctx: dict) -> dict:
    """
    Return Print Spooler state and list of installed printers for the user's machine.

    Requires CWA_SCRIPT_PRINTER_STATUS to be set in .env.
    """
    if _use_mock(tenant_ctx):
        logger.info("[PrinterService] Mock mode — check_printer_status tenant=%s", tenant_ctx.get("tenant_id"))
        return _mock_check_status(tenant_ctx)

    device = _find_device(user_email, tenant_ctx)
    if not device:
        return {
            "success": False,
            "output":  f"Could not find device for {user_email} in tenant '{tenant_ctx.get('tenant_id')}'.",
        }

    result = _run_script(device["Id"], CONFIG.CWA_SCRIPTS.get("printer_status", 0), tenant_ctx)
    result["hostname"]  = device.get("ComputerName", "Unknown")
    result["tenant_id"] = tenant_ctx.get("tenant_id")
    return result


def clear_queue(user_email: str, tenant_ctx: dict) -> dict:
    """
    Clear all stuck print jobs without a full spooler restart.

    Requires CWA_SCRIPT_PRINTER_CLEAR_QUEUE to be set in .env.
    """
    if _use_mock(tenant_ctx):
        logger.info("[PrinterService] Mock mode — clear_queue tenant=%s", tenant_ctx.get("tenant_id"))
        return _mock_clear_queue(tenant_ctx)

    device = _find_device(user_email, tenant_ctx)
    if not device:
        return {
            "success": False,
            "output":  f"Could not find device for {user_email} in tenant '{tenant_ctx.get('tenant_id')}'.",
        }

    result = _run_script(device["Id"], CONFIG.CWA_SCRIPTS.get("printer_clear", 0), tenant_ctx)
    result["hostname"]  = device.get("ComputerName", "Unknown")
    result["tenant_id"] = tenant_ctx.get("tenant_id")
    return result


def list_printers(user_email: str, tenant_ctx: dict) -> dict:
    """
    List all printers installed on the user's machine with status and driver info.

    Requires CWA_SCRIPT_PRINTER_LIST to be set in .env.
    """
    if _use_mock(tenant_ctx):
        logger.info("[PrinterService] Mock mode — list_printers tenant=%s", tenant_ctx.get("tenant_id"))
        return _mock_list_printers(tenant_ctx)

    device = _find_device(user_email, tenant_ctx)
    if not device:
        return {
            "success": False,
            "output":  f"Could not find device for {user_email} in tenant '{tenant_ctx.get('tenant_id')}'.",
        }

    result = _run_script(device["Id"], CONFIG.CWA_SCRIPTS.get("printer_list", 0), tenant_ctx)
    result["hostname"]  = device.get("ComputerName", "Unknown")
    result["tenant_id"] = tenant_ctx.get("tenant_id")
    return result
