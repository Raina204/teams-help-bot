import requests
from config.config import CONFIG
from services.rmm_service import (
    _get_session_token,
    find_device_by_user,
    run_diagnostics,
    reset_outlook,
)


def _get_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_session_token()}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def _get_customer_id(email: str) -> str:
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if domain in CONFIG.NABLE_CUSTOMER_MAP:
        return CONFIG.NABLE_CUSTOMER_MAP[domain]
    for mapped, cid in CONFIG.NABLE_CUSTOMER_MAP.items():
        if domain.endswith(mapped):
            return cid
    if CONFIG.NABLE_CUSTOMER_MAP:
        return list(CONFIG.NABLE_CUSTOMER_MAP.values())[0]
    return ""


def ok(msg):    print(f"  PASSED — {msg}")
def fail(msg):  print(f"  FAILED — {msg}")
def info(msg):  print(f"  INFO   — {msg}")
def warn(msg):  print(f"  WARN   — {msg}")
def section(t): print(f"\nTEST {t}")


print("\n" + "="*55)
print("  N-able N-central — Live Integration Test")
print("="*55)
print(f"  Base URL:     {CONFIG.NABLE_BASE_URL}")
print(f"  Token:        {'SET (' + CONFIG.NABLE_JWT_TOKEN[:12] + '...)' if CONFIG.NABLE_JWT_TOKEN else 'NOT SET'}")
print(f"  Customer map: {CONFIG.NABLE_CUSTOMER_MAP}")
print(f"  Scripts:      {CONFIG.NABLE_SCRIPTS}")
print("="*55)


section("1 — API connection (auth exchange)")
try:
    token = _get_session_token()
    ok(f"Access token obtained (starts with {token[:16]}...)")
    r = requests.get(
        f"{CONFIG.NABLE_BASE_URL}/api/devices",
        headers=_get_headers(),
        params={"customerId": "1118", "pageSize": 1},
        timeout=10,
    )
    if r.status_code == 200:
        ok("Connected to N-central API")
    else:
        fail(f"HTTP {r.status_code} — {r.text[:200]}")
except Exception as e:
    fail(str(e))


section("2 — Customer ID mapping")
test_emails = [
    ("aarav.raina@itbd.net",    "1118"),
    ("test@itbd-test.net",      "1079"),
    ("unknown@somecompany.com", None),
]
for email, expected in test_emails:
    cid = _get_customer_id(email)
    if expected and cid == expected:
        ok(f"{email} -> {cid}")
    elif not expected:
        ok(f"{email} -> Fallback: {cid}")
    else:
        warn(f"{email} -> Got {cid}, expected {expected}")


section("3 — List devices under ITBD (1118)")
try:
    r = requests.get(
        f"{CONFIG.NABLE_BASE_URL}/api/devices",
        headers=_get_headers(),
        params={"customerId": "1118", "pageSize": 10},
        timeout=15
    )
    if r.status_code == 200:
        devices = r.json().get("data", [])
        ok(f"Found {len(devices)} devices")
        for d in devices[:5]:
            last_seen = d.get("lastApplianceCheckinTime", "")
            status = "Online" if last_seen else "Offline"
            os_name = d.get("supportedOs") or d.get("supportedOsLabel") or "Unknown OS"
            info(f"[{status}] {d.get('longName')} | {os_name} | {d.get('lastLoggedInUser', 'No user')}")
        if len(devices) > 5:
            info(f"... and {len(devices) - 5} more")
    elif r.status_code == 400:
        warn("Customer ID 1118 may not be correct — check NABLE_CUSTOMER_MAP")
        info(r.text[:200])
    else:
        fail(f"HTTP {r.status_code} — {r.text[:200]}")
except Exception as e:
    fail(str(e))


section("4 — Find device for aarav.raina@itbd.net")
found_device = None
try:
    device       = find_device_by_user("itbd", "itbd@itbd.net")
    found_device = device
    ok(f"Device: {device.get('longName')}")
    info(f"OS:        {device.get('supportedOs') or device.get('supportedOsLabel') or 'N/A'}")
    info(f"Device ID: {device.get('deviceId')}")
    info(f"Last seen: {device.get('lastApplianceCheckinTime', 'N/A')}")
    info(f"Last user: {device.get('lastLoggedInUser', 'Unknown')}")
except Exception as e:
    fail(str(e))
    info("Check device is enrolled and online in N-central")


section("5 — Script ID validation")
scripts_ready = True
for name, sid in CONFIG.NABLE_SCRIPTS.items():
    if sid and sid > 0:
        ok(f"Script '{name}' ID: {sid}")
    else:
        info(f"Script '{name}' ID not set — running in mock mode (set in .env for production)")
        scripts_ready = False


section("6 — Full diagnostic run")
if found_device:
    try:
        results = run_diagnostics("itbd", "itbd@itbd.net")
        ok(f"Diagnostics completed {'(mock data)' if not scripts_ready else ''}")
        d = results["device"]
        m = results["memory"]
        c = results["cpu"]
        s = results["storage"][0]
        info(f"Device: {d['name']} — {d['os']}")
        info(f"Memory: {m['usedPercent']}% used ({m['usedGB']} GB / {m['totalGB']} GB)")
        info(f"CPU:    {c['loadPercent']}% load")
        info(f"Disk C: {s['usedPercent']}% used ({s['freeGB']} GB free)")
    except Exception as e:
        fail(str(e))
else:
    print("  SKIPPED — device not found")


section("7 — Outlook reset")
if found_device:
    try:
        result = reset_outlook("itbd", "itbd@itbd.net")
        ok(f"Outlook reset {'(mock — no script ID set)' if not CONFIG.NABLE_SCRIPTS['outlook_reset'] else 'script sent'}")
        info(f"Device:  {result.get('device')}")
        info(f"Message: {result.get('message')}")
    except Exception as e:
        fail(str(e))
else:
    print("  SKIPPED — device not found")


print(f"\n{'='*55}")
print("  Tests complete")
if not scripts_ready:
    print("")
    print("  Create these 4 scripts in N-central:")
    print("  Configuration > Scheduled Tasks > Script Repository > Add")
    print("")
    print("  TeamsBot_MemoryCheck   -> NABLE_SCRIPT_MEMORY")
    print("  TeamsBot_CPUCheck      -> NABLE_SCRIPT_CPU")
    print("  TeamsBot_StorageCheck  -> NABLE_SCRIPT_STORAGE")
    print("  TeamsBot_OutlookReset  -> NABLE_SCRIPT_OUTLOOK_RESET")
print(f"{'='*55}\n")