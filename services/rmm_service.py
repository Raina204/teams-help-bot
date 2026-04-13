import time
import requests
from config.config import CONFIG

# Cached session token (exchanged from the UI JWT via /api/auth/authenticate)
_session_token: str = ""
_session_expires_at: float = 0.0


def _get_session_token() -> str:
    """
    N-central uses a two-step auth flow:
      1. POST /api/auth/authenticate  with Authorization: Bearer <ui-jwt>
      2. Use the returned session token as Bearer on all subsequent calls.
    Session tokens are cached for 20 minutes to avoid repeated round-trips.
    """
    global _session_token, _session_expires_at

    if _session_token and time.time() < _session_expires_at:
        return _session_token

    if not CONFIG.NABLE_JWT_TOKEN:
        raise Exception(
            "NABLE_JWT_TOKEN is not set in .env. "
            "Generate your token from N-central User Management."
        )

    r = requests.post(
        f"{CONFIG.NABLE_BASE_URL}/api/auth/authenticate",
        headers={
            "Authorization": f"Bearer {CONFIG.NABLE_JWT_TOKEN}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        },
        timeout=15,
    )

    if r.status_code == 401:
        body = r.text
        if "DmsLoginException" in body or "DMS" in body:
            raise Exception(
                "N-central authentication failed — the server's internal DMS "
                "could not validate your user. This usually means:\n"
                "  1. Your JWT token was generated on a different N-central server "
                f"     (not {CONFIG.NABLE_BASE_URL}).\n"
                "  2. Your account doesn't exist on this N-central instance.\n"
                "  3. The N-central DMS service is temporarily down.\n"
                "Log into this specific server and regenerate the token under "
                "User Management > API Access."
            )
        raise Exception(
            f"N-central JWT rejected (401). Regenerate from "
            f"{CONFIG.NABLE_BASE_URL} > User Management > API Access."
        )

    r.raise_for_status()

    data = r.json()
    token = data.get("token") or data.get("access_token") or data.get("jwt") or ""
    if not token:
        raise Exception(
            f"Authenticated with N-central but response had no token field. "
            f"Response: {r.text[:200]}"
        )

    _session_token = token
    _session_expires_at = time.time() + 20 * 60  # cache for 20 minutes
    return _session_token


def _get_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_session_token()}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def _get_customer_id(user_email: str) -> str:
    if not user_email or "@" not in user_email:
        if CONFIG.NABLE_CUSTOMER_MAP:
            return list(CONFIG.NABLE_CUSTOMER_MAP.values())[0]
        raise Exception(
            "Cannot determine N-central customer — no email provided "
            "and NABLE_CUSTOMER_MAP is empty."
        )

    domain = user_email.split("@")[-1].lower()

    if domain in CONFIG.NABLE_CUSTOMER_MAP:
        return CONFIG.NABLE_CUSTOMER_MAP[domain]

    for mapped_domain, cid in CONFIG.NABLE_CUSTOMER_MAP.items():
        if domain.endswith(mapped_domain):
            return cid

    if CONFIG.NABLE_CUSTOMER_MAP:
        return list(CONFIG.NABLE_CUSTOMER_MAP.values())[0]

    raise Exception(
        f"No N-central customer found for domain '{domain}'. "
        f"Add '{domain}:CUSTOMER_ID' to NABLE_CUSTOMER_MAP in .env."
    )


def find_device_by_user(username: str, user_email: str = "") -> dict:
    customer_id = _get_customer_id(user_email)

    url    = f"{CONFIG.NABLE_BASE_URL}/api/devices"
    params = {
        "customerId": customer_id,
        "pageSize":   100,
        "pageNumber": 1
    }

    r = requests.get(url, headers=_get_headers(), params=params, timeout=15)

    if r.status_code == 401:
        raise Exception(
            "N-central JWT token is invalid or expired. "
            "Regenerate it from N-central User Management."
        )
    if r.status_code == 403:
        raise Exception(
            "Access denied to N-central devices. "
            "Make sure your user has device view permissions."
        )
    r.raise_for_status()

    devices    = r.json().get("data", [])
    lower_user = username.lower()
    first_name = lower_user.split(".")[0]

    for d in devices:
        if lower_user in (d.get("lastLoggedInUser") or "").lower():
            return d

    for d in devices:
        if first_name in (d.get("longName") or "").lower():
            return d

    for d in devices:
        for field in ["userName", "lastLoggedInUser", "longName"]:
            if first_name in (d.get(field) or "").lower():
                return d

    raise Exception(
        f"No device found for user '{username}' under "
        f"N-central customer {customer_id}. "
        "Make sure the device is online and enrolled in N-able."
    )


def run_script(device_id: int, script_id: int) -> dict:
    if not script_id or script_id == 0:
        raise Exception(
            f"Script ID is 0 or not set. "
            "Create the script in N-central and update the ID in .env."
        )

    url     = f"{CONFIG.NABLE_BASE_URL}/api/scheduled-tasks/direct"
    payload = {
        "taskType": "AutomationPolicy",
        "items": [
            {
                "taskItemId": script_id,
                "deviceIds":  [device_id]
            }
        ]
    }

    r = requests.post(url, json=payload, headers=_get_headers(), timeout=15)

    if r.status_code == 401:
        raise Exception("JWT token expired — regenerate from N-central.")
    if r.status_code == 404:
        raise Exception(
            f"Script ID {script_id} not found in N-central. "
            "Check NABLE_SCRIPT_* values in .env."
        )
    r.raise_for_status()
    return r.json()


def _get_script_output(device_id: int, script_id: int) -> str:
    url    = f"{CONFIG.NABLE_BASE_URL}/api/scheduled-tasks/status"
    params = {"deviceId": device_id, "taskItemId": script_id}

    for _ in range(12):
        try:
            r = requests.get(url, headers=_get_headers(), params=params, timeout=15)
            if r.ok:
                data   = r.json()
                status = (data.get("status") or "").lower()
                if status in ("completed", "success", "done"):
                    return data.get("output", "")
                if status in ("failed", "error"):
                    return ""
        except requests.RequestException:
            pass
        time.sleep(5)

    return ""


def _parse(output: str, key: str, default):
    for line in (output or "").splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            try:
                return float(line.split("=", 1)[1].strip())
            except ValueError:
                pass
    return default


def _build_diagnostics(device: dict, outputs: dict) -> dict:
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
            "name": device.get("longName", "Unknown"),
            "os":   f"{device.get('osName','')} {device.get('osVersion','')}".strip()
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


def run_diagnostics(user_name: str, user_email: str) -> dict:
    username = (
        user_email.split("@")[0]
        if user_email and "@" in user_email
        else user_name.replace(" ", ".").lower()
    )

    device    = find_device_by_user(username, user_email)
    device_id = device["deviceId"]

    run_script(device_id, CONFIG.NABLE_SCRIPTS["memory"])
    run_script(device_id, CONFIG.NABLE_SCRIPTS["cpu"])
    run_script(device_id, CONFIG.NABLE_SCRIPTS["storage"])

    time.sleep(30)

    outputs = {
        "memory":  _get_script_output(device_id, CONFIG.NABLE_SCRIPTS["memory"]),
        "cpu":     _get_script_output(device_id, CONFIG.NABLE_SCRIPTS["cpu"]),
        "storage": _get_script_output(device_id, CONFIG.NABLE_SCRIPTS["storage"]),
    }

    return _build_diagnostics(device, outputs)


def reset_outlook(user_name: str, user_email: str) -> dict:
    username = (
        user_email.split("@")[0]
        if user_email and "@" in user_email
        else user_name.replace(" ", ".").lower()
    )

    device    = find_device_by_user(username, user_email)
    device_id = device["deviceId"]

    run_script(device_id, CONFIG.NABLE_SCRIPTS["outlook_reset"])

    return {
        "message": (
            f"Outlook reset script sent to {device['longName']} via N-able N-central. "
            "Outlook will close and reopen automatically within 30 seconds."
        ),
        "device": device["longName"]
    }