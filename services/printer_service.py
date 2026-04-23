"""
services/printer_service.py
───────────────────────────────────────────────────────────────────────────────
Printer Spooler Service — integrates with N-able RMM to manage the Windows
Print Spooler service on a user's machine under a multi-tenant setup.

Capabilities
------------
  • restart_print_spooler(user_email)   — stops spooler, clears stuck jobs, restarts
  • check_printer_status(user_email)    — reports spooler state + queued jobs
  • clear_print_queue(user_email)       — clears stuck jobs without restart
  • list_printers(user_email)           — lists all printers installed on device

All methods fall back to mock mode when NABLE_JWT_TOKEN is empty.
Multi-tenant support via NABLE_CUSTOMER_MAP (same as rmm_service.py).
"""

import os
import json
import logging
import requests
from datetime import datetime
from config.config import Config

logger = logging.getLogger(__name__)


# ── PowerShell scripts uploaded to N-able on demand ──────────────────────────

SCRIPT_RESTART_SPOOLER = r"""
# Restart-PrintSpooler.ps1
# Stops the Print Spooler, clears stuck jobs, and restarts it.
$spoolerPath = "$env:SystemRoot\System32\spool\PRINTERS"

Write-Output "=== Print Spooler Restart ==="
Write-Output "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

# Stop spooler
Write-Output "Stopping Print Spooler service..."
Stop-Service -Name Spooler -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Clear spool files
$files = Get-ChildItem -Path $spoolerPath -ErrorAction SilentlyContinue
$count = ($files | Measure-Object).Count
if ($count -gt 0) {
    Remove-Item "$spoolerPath\*" -Force -Recurse -ErrorAction SilentlyContinue
    Write-Output "Cleared $count stuck print job(s)."
} else {
    Write-Output "No stuck jobs found in spool folder."
}

# Restart spooler
Start-Service -Name Spooler -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$svc = Get-Service -Name Spooler
Write-Output "Print Spooler status: $($svc.Status)"

if ($svc.Status -eq 'Running') {
    Write-Output "SUCCESS: Print Spooler restarted successfully."
    exit 0
} else {
    Write-Output "ERROR: Print Spooler failed to start. Manual intervention needed."
    exit 1
}
"""

SCRIPT_CHECK_STATUS = r"""
# Check-PrinterStatus.ps1
$svc = Get-Service -Name Spooler -ErrorAction SilentlyContinue
$spoolerPath = "$env:SystemRoot\System32\spool\PRINTERS"
$stuckJobs   = (Get-ChildItem -Path $spoolerPath -ErrorAction SilentlyContinue | Measure-Object).Count
$printers    = Get-Printer | Select-Object Name, PrinterStatus, DriverName

Write-Output "=== Printer Status Report ==="
Write-Output "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Output "Spooler Service: $($svc.Status)"
Write-Output "Stuck Jobs in Spool: $stuckJobs"
Write-Output ""
Write-Output "--- Installed Printers ---"
foreach ($p in $printers) {
    Write-Output "Printer: $($p.Name) | Status: $($p.PrinterStatus) | Driver: $($p.DriverName)"
}
"""

SCRIPT_CLEAR_QUEUE = r"""
# Clear-PrintQueue.ps1
$spoolerPath = "$env:SystemRoot\System32\spool\PRINTERS"

Stop-Service -Name Spooler -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$files = Get-ChildItem -Path $spoolerPath -ErrorAction SilentlyContinue
$count = ($files | Measure-Object).Count
Remove-Item "$spoolerPath\*" -Force -Recurse -ErrorAction SilentlyContinue

Start-Service -Name Spooler -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Output "Cleared $count print job(s). Spooler restarted."
$svc = Get-Service -Name Spooler
Write-Output "Spooler status: $($svc.Status)"
"""

SCRIPT_LIST_PRINTERS = r"""
# List-Printers.ps1
$printers = Get-Printer | Select-Object Name, PrinterStatus, DriverName, PortName, Shared
Write-Output "=== Installed Printers ==="
foreach ($p in $printers) {
    Write-Output "Name: $($p.Name)"
    Write-Output "  Status : $($p.PrinterStatus)"
    Write-Output "  Driver : $($p.DriverName)"
    Write-Output "  Port   : $($p.PortName)"
    Write-Output "  Shared : $($p.Shared)"
    Write-Output "---"
}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_customer_id(user_email: str) -> int | None:
    """Resolve a user's email domain → N-able customer ID using NABLE_CUSTOMER_MAP."""
    customer_map_raw = os.environ.get("NABLE_CUSTOMER_MAP", "")
    if not customer_map_raw:
        return None
    domain = user_email.split("@")[-1].lower()
    for pair in customer_map_raw.split(","):
        if ":" in pair:
            d, cid = pair.strip().split(":", 1)
            if d.strip().lower() == domain:
                return int(cid.strip())
    return None


def _nable_headers() -> dict:
    token = os.environ.get("NABLE_JWT_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _find_device(user_email: str) -> dict | None:
    """
    Look up the user's device in N-able by email/username.
    Returns device dict with at least {'id': ..., 'hostname': ...} or None.
    """
    base_url = os.environ.get("NABLE_BASE_URL", "").rstrip("/")
    customer_id = _get_customer_id(user_email)
    username = user_email.split("@")[0]

    try:
        params = {"customerid": customer_id} if customer_id else {}
        params["username"] = username
        resp = requests.get(
            f"{base_url}/api/devices",
            headers=_nable_headers(),
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        devices = resp.json().get("devices", [])
        return devices[0] if devices else None
    except Exception as exc:
        logger.error("N-able device lookup failed: %s", exc)
        return None


def _run_inline_script(device_id: int, script_body: str, script_name: str) -> dict:
    """
    Upload a PowerShell script to N-able and immediately run it on device_id.
    Returns {'success': bool, 'output': str}.
    """
    base_url = os.environ.get("NABLE_BASE_URL", "").rstrip("/")
    headers  = _nable_headers()

    try:
        # 1. Upload script
        upload_resp = requests.post(
            f"{base_url}/api/script-management/scripts",
            headers=headers,
            json={
                "name":        script_name,
                "description": f"Auto-uploaded by Teams bot — {script_name}",
                "scriptType":  "PowerShell",
                "content":     script_body,
            },
            timeout=20,
        )
        upload_resp.raise_for_status()
        script_id = upload_resp.json().get("scriptId") or upload_resp.json().get("id")

        # 2. Run script on device
        run_resp = requests.post(
            f"{base_url}/api/script-management/scripts/{script_id}/run",
            headers=headers,
            json={"deviceIds": [device_id]},
            timeout=20,
        )
        run_resp.raise_for_status()
        job_id = run_resp.json().get("jobId")

        # 3. Poll for result (up to 30 s)
        import time
        for _ in range(6):
            time.sleep(5)
            result_resp = requests.get(
                f"{base_url}/api/script-management/jobs/{job_id}",
                headers=headers,
                timeout=15,
            )
            data = result_resp.json()
            if data.get("status") in ("Completed", "Failed"):
                output = data.get("output", "")
                success = "SUCCESS" in output or data.get("status") == "Completed"
                return {"success": success, "output": output, "script_id": script_id}

        return {"success": False, "output": "Script timed out waiting for result."}

    except Exception as exc:
        logger.error("N-able script execution error: %s", exc)
        return {"success": False, "output": str(exc)}


# ── Mock responses (used when NABLE_JWT_TOKEN is blank) ──────────────────────

def _mock_restart_spooler() -> dict:
    return {
        "success":  True,
        "hostname": "MOCK-PC-001",
        "output":   (
            "=== Print Spooler Restart ===\n"
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "Stopping Print Spooler service...\n"
            "Cleared 3 stuck print job(s).\n"
            "Print Spooler status: Running\n"
            "SUCCESS: Print Spooler restarted successfully."
        ),
        "mock": True,
    }


def _mock_check_status() -> dict:
    return {
        "success":  True,
        "hostname": "MOCK-PC-001",
        "output":   (
            "=== Printer Status Report ===\n"
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "Spooler Service: Running\n"
            "Stuck Jobs in Spool: 0\n\n"
            "--- Installed Printers ---\n"
            "Printer: HP LaserJet Pro M404 | Status: Normal | Driver: HP LaserJet Pro\n"
            "Printer: Microsoft Print to PDF | Status: Normal | Driver: Microsoft Print To PDF\n"
            "Printer: OneNote | Status: Normal | Driver: Microsoft Shared Fax Driver"
        ),
        "mock": True,
    }


def _mock_clear_queue() -> dict:
    return {
        "success":  True,
        "hostname": "MOCK-PC-001",
        "output":   "Cleared 2 print job(s). Spooler restarted.\nSpooler status: Running",
        "mock": True,
    }


def _mock_list_printers() -> dict:
    return {
        "success":  True,
        "hostname": "MOCK-PC-001",
        "output":   (
            "=== Installed Printers ===\n"
            "Name: HP LaserJet Pro M404\n"
            "  Status : Normal\n"
            "  Driver : HP LaserJet Pro M402-M403 PCL 6\n"
            "  Port   : 192.168.1.50\n"
            "  Shared : False\n---\n"
            "Name: Microsoft Print to PDF\n"
            "  Status : Normal\n"
            "  Driver : Microsoft Print To PDF\n"
            "  Port   : PORTPROMPT:\n"
            "  Shared : False\n---"
        ),
        "mock": True,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def restart_print_spooler(user_email: str) -> dict:
    """
    Restart the Windows Print Spooler on the user's machine via N-able RMM.
    Clears the spool folder before restarting.
    Returns: {success, hostname, output, mock?}
    """
    if not os.environ.get("NABLE_JWT_TOKEN"):
        logger.info("[PrinterService] Mock mode — restart_print_spooler")
        return _mock_restart_spooler()

    device = _find_device(user_email)
    if not device:
        return {"success": False, "output": f"Could not find device for {user_email}."}

    result = _run_inline_script(device["id"], SCRIPT_RESTART_SPOOLER, "Restart-PrintSpooler")
    result["hostname"] = device.get("hostname", "Unknown")
    return result


def check_printer_status(user_email: str) -> dict:
    """
    Return Print Spooler state + list of installed printers for the user's machine.
    Returns: {success, hostname, output, mock?}
    """
    if not os.environ.get("NABLE_JWT_TOKEN"):
        logger.info("[PrinterService] Mock mode — check_printer_status")
        return _mock_check_status()

    device = _find_device(user_email)
    if not device:
        return {"success": False, "output": f"Could not find device for {user_email}."}

    result = _run_inline_script(device["id"], SCRIPT_CHECK_STATUS, "Check-PrinterStatus")
    result["hostname"] = device.get("hostname", "Unknown")
    return result


def clear_print_queue(user_email: str) -> dict:
    """
    Clear all stuck print jobs without a full spooler restart — faster for minor jams.
    Returns: {success, hostname, output, mock?}
    """
    if not os.environ.get("NABLE_JWT_TOKEN"):
        logger.info("[PrinterService] Mock mode — clear_print_queue")
        return _mock_clear_queue()

    device = _find_device(user_email)
    if not device:
        return {"success": False, "output": f"Could not find device for {user_email}."}

    result = _run_inline_script(device["id"], SCRIPT_CLEAR_QUEUE, "Clear-PrintQueue")
    result["hostname"] = device.get("hostname", "Unknown")
    return result


def list_printers(user_email: str) -> dict:
    """
    List all printers installed on the user's machine with status and driver info.
    Returns: {success, hostname, output, mock?}
    """
    if not os.environ.get("NABLE_JWT_TOKEN"):
        logger.info("[PrinterService] Mock mode — list_printers")
        return _mock_list_printers()

    device = _find_device(user_email)
    if not device:
        return {"success": False, "output": f"Could not find device for {user_email}."}

    result = _run_inline_script(device["id"], SCRIPT_LIST_PRINTERS, "List-Printers")
    result["hostname"] = device.get("hostname", "Unknown")
    return result
