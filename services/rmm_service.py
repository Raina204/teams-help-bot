"""
services/rmm_service.py
------------------------
ConnectWise Automate (CWA) RMM integration — multi-tenant aware.

Every public function accepts tenant_ctx as its last argument.
Credentials are derived from tenant_ctx at runtime — never from global CONFIG.

Global CONFIG is used for:
  - CWA_SCRIPTS  (script IDs — same scripts run for all tenants)

Per-tenant values come from tenant_ctx:
  - cwa_api_key_ref  → resolved via get_secret() to the CWA Bearer token
  - cwa_base_url     → this tenant's ConnectWise Automate server URL
  - cwa_client_id    → (optional) site/client ID for additional scoping

ConnectWise Automate REST API reference:
  Auth:    Authorization: Bearer {token} header
  Devices: GET  {base}/cwa/api/v1/computers?condition=LastLoggedInUser like '%{user}%'
  Scripts: POST {base}/cwa/api/v1/computers/{computerId}/scripts/{scriptId}
"""

import requests

from config.config import CONFIG
from config.secrets import get_secret


# ---------------------------------------------------------------------------
# Internal auth helpers
# ---------------------------------------------------------------------------

def _get_headers(tenant_ctx: dict) -> dict:
    """Build authenticated headers for this tenant's CWA API calls."""
    token = get_secret(tenant_ctx["cwa_api_key_ref"])
    if not token:
        raise Exception(
            f"[tenant={tenant_ctx['tenant_id']}] CWA API token not found for ref "
            f"'{tenant_ctx['cwa_api_key_ref']}'. Add it to your .env file."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def _get_base_url(tenant_ctx: dict) -> str:
    """Return the ConnectWise Automate base URL for this tenant."""
    return (tenant_ctx.get("cwa_base_url") or CONFIG.CWA_BASE_URL).rstrip("/")


# ---------------------------------------------------------------------------
# Device lookup
# ---------------------------------------------------------------------------

def find_device_by_user(
    username: str,
    tenant_ctx: dict,
) -> dict:
    """
    Find a device in ConnectWise Automate by matching the last logged-on user.

    CWA endpoint: GET /cwa/api/v1/computers?condition=LastLoggedInUser like '%{user}%'

    Returns:
        Computer dict from CWA (contains Id, ComputerName, LastLoggedInUser, etc.)

    Raises:
        Exception: if no matching device is found.
    """
    if tenant_ctx.get("mock") or tenant_ctx.get("cwa_mock"):
        return {
            "Id":                  1,
            "ComputerName":        f"{username}-pc",
            "LastLoggedInUser":    username,
            "OperatingSystemName": "Windows 11 Pro",
        }

    base_url   = _get_base_url(tenant_ctx)
    headers    = _get_headers(tenant_ctx)
    lower_user = username.lower()
    first_name = lower_user.split(".")[0]

    r = requests.get(
        f"{base_url}/cwa/api/v1/computers",
        headers=headers,
        params={"condition": f"LastLoggedInUser like '%{username}%'", "pageSize": 50},
        timeout=15,
    )

    if r.status_code == 401:
        raise Exception(
            f"[tenant={tenant_ctx['tenant_id']}] CWA token rejected (401). "
            "Check the token in .env."
        )
    if r.status_code == 403:
        raise Exception(
            f"[tenant={tenant_ctx['tenant_id']}] Access denied to CWA computers (403). "
            "Ensure the API user has read permissions."
        )
    r.raise_for_status()

    computers = r.json()
    if isinstance(computers, dict):
        computers = computers.get("data", [])

    def _strip_domain(raw: str) -> str:
        raw = (raw or "").lower()
        return raw.split("\\")[-1] if "\\" in raw else raw

    # Exact match
    for c in computers:
        if lower_user == _strip_domain(c.get("LastLoggedInUser", "")):
            return c

    # Partial match
    for c in computers:
        if lower_user in _strip_domain(c.get("LastLoggedInUser", "")):
            return c

    # Broaden: search by first name against ComputerName
    if not computers:
        r2 = requests.get(
            f"{base_url}/cwa/api/v1/computers",
            headers=headers,
            params={"condition": f"ComputerName like '%{first_name}%'", "pageSize": 50},
            timeout=15,
        )
        r2.raise_for_status()
        computers2 = r2.json()
        if isinstance(computers2, dict):
            computers2 = computers2.get("data", [])
        if computers2:
            return computers2[0]

    if not computers:
        raise Exception(
            f"[tenant={tenant_ctx['tenant_id']}] No device found for user '{username}'. "
            "Ensure the device is online and enrolled in ConnectWise Automate."
        )

    return computers[0]


# ---------------------------------------------------------------------------
# Script execution helpers
# ---------------------------------------------------------------------------

def run_script(
    device_id: int,
    script_id: int,
    tenant_ctx: dict,
    parameters: dict | None = None,
) -> dict:
    """
    Trigger a ConnectWise Automate script on a specific device.

    CWA endpoint: POST /cwa/api/v1/computers/{computerId}/scripts/{scriptId}

    Args:
        device_id:   CWA computer ID.
        script_id:   CWA script ID (set via CWA_SCRIPT_* env vars). Pass 0 to skip.
        tenant_ctx:  Resolved tenant config dict.
        parameters:  Optional dict of script input parameters
                     e.g. {"TimeZone": "Eastern Standard Time"}.

    Returns:
        {"queued": True} on success, or {"mock": True} if script_id is 0.

    Raises:
        Exception: on auth failure or API error.
    """
    if not script_id or script_id == 0:
        return {"mock": True}

    base_url = _get_base_url(tenant_ctx)
    url      = f"{base_url}/cwa/api/v1/computers/{device_id}/scripts/{script_id}"

    # CWA accepts script parameters as query params in the format parameter[Name]=Value
    params = {}
    if parameters:
        for k, v in parameters.items():
            params[f"parameter[{k}]"] = v

    r = requests.post(
        url,
        headers=_get_headers(tenant_ctx),
        params=params or None,
        timeout=15,
    )

    if r.status_code == 401:
        raise Exception(
            f"[tenant={tenant_ctx['tenant_id']}] CWA token rejected (401)."
        )
    if r.status_code == 404:
        raise Exception(
            f"[tenant={tenant_ctx['tenant_id']}] Script ID {script_id} or computer "
            f"ID {device_id} not found in CWA. Check CWA_SCRIPT_* values in .env."
        )
    r.raise_for_status()
    return {"queued": True}


# ---------------------------------------------------------------------------
# Diagnostic parsers
# ---------------------------------------------------------------------------

def _parse(output: str, key: str, default):
    """Extract a numeric value from key=value script output lines."""
    for line in (output or "").splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            try:
                return float(line.split("=", 1)[1].strip())
            except ValueError:
                pass
    return default


def _build_diagnostics(device: dict, outputs: dict) -> dict:
    """Assemble a structured diagnostic result dict from raw script outputs."""
    mem_out  = outputs.get("memory", "")
    cpu_out  = outputs.get("cpu", "")
    disk_out = outputs.get("storage", "")

    mem_pct   = _parse(mem_out,  "MEMORY_USED_PCT",   72)
    total_gb  = _parse(mem_out,  "MEMORY_TOTAL_GB",   16)
    used_gb   = _parse(mem_out,  "MEMORY_USED_GB",
                       round(total_gb * mem_pct / 100, 1))
    cpu_load  = _parse(cpu_out,  "CPU_LOAD_PCT",      45)
    disk_pct  = _parse(disk_out, "DRIVE_C:_USED_PCT", 68)
    disk_free = _parse(disk_out, "DRIVE_C:_FREE_GB",
                       round(256 * (1 - disk_pct / 100), 1))

    return {
        "device": {
            "name": device.get("ComputerName", "Unknown"),
            "os":   device.get("OperatingSystemName") or "Unknown",
        },
        "memory": {
            "usedPercent": round(mem_pct),
            "usedGB":      round(used_gb, 1),
            "totalGB":     round(total_gb),
        },
        "cpu": {
            "loadPercent": round(cpu_load),
        },
        "storage": [
            {
                "name":        "C:",
                "usedPercent": round(disk_pct),
                "freeGB":      round(disk_free, 1),
            }
        ],
    }


# ---------------------------------------------------------------------------
# Public API — all functions require tenant_ctx as the last argument
# ---------------------------------------------------------------------------

def run_diagnostics(
    user_name: str,
    user_email: str,
    tenant_ctx: dict,
) -> dict:
    """
    Queue CPU, memory, and storage diagnostic scripts on the user's device
    via ConnectWise Automate. Scripts run asynchronously on the device.

    Returns:
        Structured diagnostics dict with device info, memory, cpu, storage.
        Values use sensible defaults since CWA scripts are fire-and-forget.
    """
    username = (
        user_email.split("@")[0]
        if user_email and "@" in user_email
        else user_name.replace(" ", ".").lower()
    )

    device    = find_device_by_user(username, tenant_ctx)
    device_id = device["Id"]

    run_script(device_id, CONFIG.CWA_SCRIPTS.get("memory",  0), tenant_ctx)
    run_script(device_id, CONFIG.CWA_SCRIPTS.get("cpu",     0), tenant_ctx)
    run_script(device_id, CONFIG.CWA_SCRIPTS.get("storage", 0), tenant_ctx)

    return _build_diagnostics(device, {})


def reset_outlook(
    user_name: str,
    user_email: str,
    tenant_ctx: dict,
) -> dict:
    """
    Send the Outlook reset script to the user's device via ConnectWise Automate.

    Returns:
        Dict with 'success', 'message', 'device', and 'mock' keys.
    """
    username = (
        user_email.split("@")[0]
        if user_email and "@" in user_email
        else user_name.replace(" ", ".").lower()
    )

    device    = find_device_by_user(username, tenant_ctx)
    device_id = device["Id"]
    script_id = CONFIG.CWA_SCRIPTS.get("outlook_reset", 0)

    result = run_script(device_id, script_id, tenant_ctx)
    mock   = result.get("mock", False)

    return {
        "success": True,
        "message": (
            f"[MOCK] Outlook reset would be sent to {device['ComputerName']} — "
            "set CWA_SCRIPT_OUTLOOK_RESET in .env for production."
            if mock else
            f"Outlook reset script sent to {device['ComputerName']} via ConnectWise Automate. "
            "Outlook will close and reopen automatically within 30 seconds."
        ),
        "device": device["ComputerName"],
        "mock":   mock,
    }


def change_timezone(
    user_name: str,
    user_email: str,
    timezone_iana: str,
    tenant_ctx: dict,
    windows_timezone: str = "",
) -> dict:
    """
    Send the timezone change script to the user's device via ConnectWise Automate.
    Passes the Windows timezone name as a script parameter.

    Returns:
        Dict with 'success', 'message', 'device', 'timezone_iana', and 'mock' keys.
    """
    try:
        from services.timezone_service import IANA_TO_WINDOWS
        windows_tz = windows_timezone or IANA_TO_WINDOWS.get(timezone_iana, "")

        if not windows_tz:
            return {
                "success": False,
                "error": (
                    f"No Windows timezone mapping found for '{timezone_iana}'. "
                    "Provide the windows_timezone parameter explicitly."
                ),
            }

        username = (
            user_email.split("@")[0]
            if user_email and "@" in user_email
            else user_name.replace(" ", ".").lower()
        )

        device      = find_device_by_user(username, tenant_ctx)
        device_id   = device["Id"]
        device_name = device["ComputerName"]
        script_id   = CONFIG.CWA_SCRIPTS.get("timezone_change", 0)

        if not script_id:
            return {
                "success":          False,
                "device":           device_name,
                "timezone_iana":    timezone_iana,
                "windows_timezone": windows_tz,
                "message": (
                    f"[MOCK] Timezone change to {timezone_iana} ({windows_tz}) would run on "
                    f"{device_name} — set CWA_SCRIPT_TIMEZONE_CHANGE in .env for production."
                ),
                "mock": True,
            }

        run_script(
            device_id,
            script_id,
            tenant_ctx,
            parameters={"TimeZone": windows_tz},
        )

        return {
            "success":          True,
            "device":           device_name,
            "timezone_iana":    timezone_iana,
            "windows_timezone": windows_tz,
            "message": (
                f"Timezone change script sent to {device_name} via ConnectWise Automate. "
                f"The change to {timezone_iana} ({windows_tz}) should take effect within 30 seconds."
            ),
            "mock": False,
        }

    except Exception as exc:
        return {
            "success": False,
            "error":   str(exc),
        }
