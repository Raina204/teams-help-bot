import requests
import time
import random
from config.config import CONFIG

# ── Mode detection ─────────────────────────────────────────
# MOCK mode  — RMM_BASE_URL is empty in .env (default now)
# LIVE mode  — RMM_BASE_URL, RMM_USERNAME, RMM_PASSWORD filled in .env
# Nothing else changes. The switch is automatic.

def _is_live_mode() -> bool:
    return bool(
        CONFIG.RMM_BASE_URL and
        CONFIG.RMM_USERNAME and
        CONFIG.RMM_PASSWORD
    )

def _auth() -> tuple:
    return (CONFIG.RMM_USERNAME, CONFIG.RMM_PASSWORD)


# ── Mock data ──────────────────────────────────────────────
# Realistic simulated data used when RMM credentials are
# not yet configured. Values vary slightly each call so
# results feel natural in Teams during demos and testing.

def _mock_device(username: str) -> dict:
    first = username.split(".")[0].upper()
    return {
        "Id":           9999,
        "ComputerName": f"{first}-LAPTOP",
        "OS":           "Windows 11 Pro (22H2)",
        "UserName":     username,
        "LastContact":  "2026-04-07T10:00:00Z",
        "_mock":        True
    }

def _mock_diagnostics(device: dict) -> dict:
    mem_pct   = random.randint(55, 88)
    total_gb  = 16
    used_gb   = round(total_gb * mem_pct / 100, 1)
    free_gb   = round(total_gb - used_gb, 1)
    cpu_load  = random.randint(20, 75)
    disk_pct  = random.randint(45, 85)
    disk_free = round(256 * (1 - disk_pct / 100), 1)
    return {
        "device": {
            "name":  device["ComputerName"],
            "os":    device["OS"],
            "_mock": True
        },
        "memory": {
            "usedPercent": mem_pct,
            "usedGB":      used_gb,
            "totalGB":     total_gb
        },
        "cpu": {
            "loadPercent": cpu_load
        },
        "storage": [
            {
                "name":        "C:",
                "usedPercent": disk_pct,
                "freeGB":      disk_free
            }
        ]
    }


# ── Live mode — ConnectWise Automate API calls ─────────────
# These functions activate automatically when RMM credentials
# are present in .env. No other code changes needed.

def _find_device_live(username: str) -> dict:
    url    = f"{CONFIG.RMM_BASE_URL}/cwa/api/v1/computers"
    params = {"condition": f"UserName like '%{username}%'"}
    r      = requests.get(url, params=params, auth=_auth(), timeout=15)
    r.raise_for_status()
    computers = r.json()
    if not computers:
        raise Exception(
            f"No managed device found for '{username}'. "
            "Make sure the device is online and enrolled in Automate."
        )
    return computers[0]

def _run_script_live(computer_id: int, script_id: int) -> dict:
    url     = f"{CONFIG.RMM_BASE_URL}/cwa/api/v1/scripts/{script_id}/run"
    payload = {"ComputerId": computer_id}
    r       = requests.post(url, json=payload, auth=_auth(), timeout=15)
    r.raise_for_status()
    return r.json()

def _get_script_result_live(computer_id: int, script_id: int) -> str:
    """Polls for script output after execution completes."""
    url    = f"{CONFIG.RMM_BASE_URL}/cwa/api/v1/computers/{computer_id}/scripts"
    params = {"scriptId": script_id, "pageSize": 1}
    r      = requests.get(url, params=params, auth=_auth(), timeout=15)
    if r.ok and r.json():
        return r.json()[0].get("output", "")
    return ""

def _parse_live_diagnostics(device: dict, outputs: dict) -> dict:
    """
    Parses raw script output from Automate into the structured
    results dict the bot expects. Script outputs contain lines like:
    MEMORY_USED_PCT=72.5
    CPU_LOAD_PCT=45
    DRIVE_C:_USED_PCT=68
    """
    def extract(text: str, key: str, default):
        for line in text.splitlines():
            if line.startswith(key + "="):
                try:
                    return float(line.split("=", 1)[1].strip())
                except ValueError:
                    pass
        return default

    mem_out  = outputs.get("memory", "")
    cpu_out  = outputs.get("cpu", "")
    disk_out = outputs.get("storage", "")

    mem_pct   = extract(mem_out,  "MEMORY_USED_PCT",  72)
    total_gb  = extract(mem_out,  "MEMORY_TOTAL_GB",  16)
    used_gb   = extract(mem_out,  "MEMORY_USED_GB",   round(total_gb * mem_pct / 100, 1))
    cpu_load  = extract(cpu_out,  "CPU_LOAD_PCT",     45)
    disk_pct  = extract(disk_out, "DRIVE_C:_USED_PCT", 68)
    disk_free = extract(disk_out, "DRIVE_C:_FREE_GB",  round(256 * (1 - disk_pct / 100), 1))

    return {
        "device": {
            "name": device.get("ComputerName", "Unknown"),
            "os":   device.get("OS", "Unknown")
        },
        "memory": {
            "usedPercent": round(mem_pct),
            "usedGB":      round(used_gb, 1),
            "totalGB":     round(total_gb)
        },
        "cpu": {
            "loadPercent": round(cpu_load)
        },
        "storage": [
            {
                "name":        "C:",
                "usedPercent": round(disk_pct),
                "freeGB":      round(disk_free, 1)
            }
        ]
    }


# ── Public API ─────────────────────────────────────────────
# These are the functions called by main_dialog.py.
# They work identically in mock and live mode.

def find_device_by_user(username: str) -> dict:
    if _is_live_mode():
        return _find_device_live(username)
    return _mock_device(username)

def run_script(computer_id: int, script_id: int) -> dict:
    if _is_live_mode():
        return _run_script_live(computer_id, script_id)
    return {"status": "mock_queued", "_mock": True}

def run_diagnostics(user_name: str, user_email: str) -> dict:
    """
    Runs memory, CPU, and storage diagnostics on the user's machine.
    Mock mode: returns simulated data instantly.
    Live mode: fires 3 Automate scripts, waits for completion,
               parses output into structured results.
    """
    username = (
        user_email.split("@")[0]
        if user_email
        else user_name.replace(" ", ".").lower()
    )
    device = find_device_by_user(username)

    if not _is_live_mode():
        time.sleep(2)
        return _mock_diagnostics(device)

    # Live mode — fire all three diagnostic scripts
    computer_id = device["Id"]
    run_script(computer_id, CONFIG.RMM_SCRIPTS["memory"])
    run_script(computer_id, CONFIG.RMM_SCRIPTS["cpu"])
    run_script(computer_id, CONFIG.RMM_SCRIPTS["storage"])

    # Wait for scripts to complete on the remote machine
    time.sleep(30)

    # Retrieve script outputs
    outputs = {
        "memory":  _get_script_result_live(computer_id, CONFIG.RMM_SCRIPTS["memory"]),
        "cpu":     _get_script_result_live(computer_id, CONFIG.RMM_SCRIPTS["cpu"]),
        "storage": _get_script_result_live(computer_id, CONFIG.RMM_SCRIPTS["storage"]),
    }

    return _parse_live_diagnostics(device, outputs)


def reset_outlook(user_name: str, user_email: str) -> dict:
    """
    Resets Outlook on the user's machine.
    Mock mode: simulates the reset with a confirmation message.
    Live mode: fires the Automate reset script and confirms execution.
    """
    username = (
        user_email.split("@")[0]
        if user_email
        else user_name.replace(" ", ".").lower()
    )
    device = find_device_by_user(username)

    if not _is_live_mode():
        time.sleep(1)
        return {
            "message": (
                f"Outlook reset completed on {device['ComputerName']}. "
                "Outlook has been closed and your profile cache cleared. "
                "Please reopen Outlook — it will rebuild your profile automatically."
            ),
            "device": device["ComputerName"],
            "_mock":  True
        }

    # Live mode — fire the Outlook reset script
    computer_id = device["Id"]
    run_script(computer_id, CONFIG.RMM_SCRIPTS["outlook_reset"])
    return {
        "message": (
            f"Outlook reset script sent to {device['ComputerName']}. "
            "Outlook will close and reopen automatically within 30 seconds."
        ),
        "device": device["ComputerName"]
    }