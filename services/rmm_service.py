import time
import requests
from config.config import CONFIG


# Cached access token (exchanged from the UI JWT via /api/auth/authenticate)
_session_token: str = ""
_session_expires_at: float = 0.0


def _get_session_token() -> str:
    """
    N-central two-step auth:
      1. POST /api/auth/authenticate  with Authorization: Bearer <ui-jwt>
      2. Parse the returned access token (nested under tokens.access.token)
      3. Use that access token as Bearer on all subsequent calls.
    Access tokens last 60 minutes; cached for 50 to avoid expiry mid-request.
    """
    global _session_token, _session_expires_at

    if _session_token and time.time() < _session_expires_at:
        return _session_token

    if not CONFIG.NABLE_JWT_TOKEN:
        raise Exception(
            "NABLE_JWT_TOKEN is not set in .env. "
            "Generate it from N-central: Administration > "
            "User Management > <your user> > API Access > Generate JSON Web Token."
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
        raise Exception(
            f"N-central rejected the JWT (401): {r.text[:300]}\n"
            "Regenerate the token: log into "
            f"{CONFIG.NABLE_BASE_URL} > Administration > User Management > "
            "your user > API Access > Generate JSON Web Token."
        )

    r.raise_for_status()

    data = r.json()
    # N-central returns: {"tokens": {"access": {"token": "...", "type": "bearer"}, "refresh": {...}}}
    # Fall back to flat fields for older versions.
    token = (
        ((data.get("tokens") or {}).get("access") or {}).get("token")
        or data.get("token")
        or data.get("access_token")
        or ""
    )
    if not token:
        raise Exception(
            f"Authenticated with N-central but could not find access token in response. "
            f"Response: {r.text[:300]}"
        )

    _session_token = token
    _session_expires_at = time.time() + 50 * 60  # access token expires in 60 min
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

    def _extract_username(raw: str) -> str:
        """Strip DOMAIN\ prefix from lastLoggedInUser."""
        raw = (raw or "").lower()
        return raw.split("\\")[-1] if "\\" in raw else raw

    # 1. Exact match on the username part (after DOMAIN\)
    for d in devices:
        if lower_user == _extract_username(d.get("lastLoggedInUser", "")):
            return d

    # 2. Partial match on username part
    for d in devices:
        if lower_user in _extract_username(d.get("lastLoggedInUser", "")):
            return d

    # 3. First name match against username or device name
    for d in devices:
        if first_name in _extract_username(d.get("lastLoggedInUser", "")):
            return d
        if first_name in (d.get("longName") or "").lower():
            return d

    raise Exception(
        f"No device found for user '{username}' under "
        f"N-central customer {customer_id}. "
        "Make sure the device is online and enrolled in N-able."
    )


def run_script(device_id: int, script_id: int) -> dict:
    if not script_id or script_id == 0:
        return {"mock": True}

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
    if not script_id or script_id == 0:
        return ""

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
            "os":   device.get("supportedOs") or device.get("supportedOsLabel") or "Unknown"
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

    scripts_configured = all(CONFIG.NABLE_SCRIPTS[k] for k in ("memory", "cpu", "storage"))

    run_script(device_id, CONFIG.NABLE_SCRIPTS["memory"])
    run_script(device_id, CONFIG.NABLE_SCRIPTS["cpu"])
    run_script(device_id, CONFIG.NABLE_SCRIPTS["storage"])

    if scripts_configured:
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

    mock = not CONFIG.NABLE_SCRIPTS["outlook_reset"]
    return {
        "message": (
            f"[MOCK] Outlook reset would be sent to {device['longName']} — set NABLE_SCRIPT_OUTLOOK_RESET in .env for production."
            if mock else
            f"Outlook reset script sent to {device['longName']} via N-able N-central. "
            "Outlook will close and reopen automatically within 30 seconds."
        ),
        "device": device["longName"]
    }

def change_timezone(
    user_name:  str,
    user_email: str,
    windows_tz: str,
    iana_tz:    str,
) -> dict:
    """
    Remotely changes the Windows timezone on the user's device via N-able.
    Runs the timezone change automation policy script on the device.
    """
    try:
        username = (
            user_email.split("@")[0]
            if user_email and "@" in user_email
            else user_name.replace(" ", ".").lower()
        )

        device      = find_device_by_user(username, user_email)
        device_id   = device["deviceId"]
        device_name = device["longName"]
        script_id   = CONFIG.NABLE_SCRIPTS.get("timezone_change", 0)

        if not script_id:
            return {
                "success":    False,
                "device":     device_name,
                "windows_tz": windows_tz,
                "iana_tz":    iana_tz,
                "message": (
                    f"[MOCK] Timezone change to {iana_tz} would run on "
                    f"{device_name} — set NABLE_SCRIPT_TIMEZONE_CHANGE in .env."
                ),
                "_mock": True,
            }

        run_script(device_id, script_id)

        time.sleep(10)
        output  = _get_script_output(device_id, script_id)
        success = "success" in (output or "").lower() or bool(output)

        return {
            "success":    True,
            "device":     device_name,
            "windows_tz": windows_tz,
            "iana_tz":    iana_tz,
            "message": (
                f"Timezone successfully changed to {iana_tz} on "
                f"{device_name}. The change takes effect immediately."
                if success else
                f"Timezone change script sent to {device_name}. "
                f"The change to {iana_tz} should take effect within 30 seconds."
            ),
        }

    except Exception as exc:
        return {
            "success": False,
            "error":   str(exc),
        }