import requests
from config.config import CONFIG
from services.connectwise_service import (
    _get_headers,
    create_ticket,
    add_note,
    get_ticket
)

print("=" * 55)
print("  ConnectWise Staging — Full Integration Test")
print("=" * 55)
print(f"  Site:        {CONFIG.CW_SITE}")
print(f"  Company ID:  {CONFIG.CW_COMPANY_ID}")
print(f"  Board:       {CONFIG.CW_DEFAULT_BOARD}")
print(f"  Company RID: {CONFIG.CW_DEFAULT_COMPANY_ID}")
print(f"  Priority:    {CONFIG.CW_DEFAULT_PRIORITY}")
print("=" * 55)
print("")

# ── Test 1 — Connection ────────────────────────────────────
print("TEST 1 — Connection check")
try:
    url = f"{CONFIG.CW_SITE}/v4_6_release/apis/3.0/system/info"
    r = requests.get(url, headers=_get_headers(), timeout=10)
    if r.status_code == 200:
        print(f"  PASSED — Connected to ConnectWise staging")
        print(f"  Version: {r.json().get('version', 'Unknown')}")
    else:
        print(f"  FAILED — {r.status_code}")
except Exception as e:
    print(f"  ERROR — {str(e)}")
print("")

# ── Test 2 — Create ticket ─────────────────────────────────
print("TEST 2 — Create ticket")
ticket_id = None
try:
    ticket = create_ticket(
        summary="TEST — Teams Bot staging check — safe to delete",
        priority="Medium",
        board=CONFIG.CW_DEFAULT_BOARD,
        user_name="Aarav Raina (TeamsBot Test)"
    )
    ticket_id = ticket["id"]
    print(f"  PASSED — Ticket created successfully")
    print(f"  Ticket ID: #{ticket_id}")
    print(f"  Summary:   {ticket['summary']}")
    print(f"  Status:    {ticket['status']['name']}")
    print(f"  Board:     {ticket['board']['name']}")
    print(f"  Priority:  {ticket['priority']['name']}")
except Exception as e:
    print(f"  FAILED — {str(e)}")
print("")

# ── Test 3 — Add note ──────────────────────────────────────
print("TEST 3 — Add note to ticket")
if ticket_id:
    try:
        note = add_note(
            ticket_id=ticket_id,
            note_text=(
                "Automated diagnostic results from Teams Bot:\n"
                "Memory: 72% used (11.5 GB / 16 GB)\n"
                "CPU: 45% load\n"
                "Drive C: 68% used (120 GB free)\n"
                "OS: Windows 11 Pro"
            )
        )
        print(f"  PASSED — Note added successfully")
        print(f"  Note ID: #{note['id']}")
    except Exception as e:
        print(f"  FAILED — {str(e)}")
else:
    print("  SKIPPED — No ticket created in Test 2")
print("")

# ── Test 4 — Retrieve ticket ───────────────────────────────
print("TEST 4 — Retrieve ticket")
if ticket_id:
    try:
        fetched = get_ticket(ticket_id)
        print(f"  PASSED — Ticket retrieved successfully")
        print(f"  Ticket ID: #{fetched['id']}")
        print(f"  Summary:   {fetched['summary']}")
        print(f"  Status:    {fetched['status']['name']}")
    except Exception as e:
        print(f"  FAILED — {str(e)}")
else:
    print("  SKIPPED — No ticket created in Test 2")
print("")

# ── Test 5 — Triage engine ─────────────────────────────────
print("TEST 5 — Triage engine check")
TRIAGE_RULES = [
    (["outlook", "email", "calendar", "ost"],      "Email Issue",          "Medium"),
    (["slow", "freeze", "crash", "blue screen"],   "Performance",          "High"),
    (["printer", "print", "scan"],                  "Hardware",             "Medium"),
    (["vpn", "remote", "rdp"],                      "Network/Connectivity", "High"),
    (["password", "locked out", "login"],           "Account Access",       "High"),
    (["wifi", "internet", "network"],               "Network/Connectivity", "High"),
    (["install", "software", "application"],        "Software Request",     "Low"),
]

def triage(summary):
    lower = summary.lower()
    for keywords, ticket_type, priority in TRIAGE_RULES:
        if any(k in lower for k in keywords):
            return ticket_type, priority
    return "General Request", "Medium"

test_cases = [
    ("my outlook keeps crashing",      "Email Issue"),
    ("computer is running very slow",  "Performance"),
    ("cannot connect to the VPN",      "Network/Connectivity"),
    ("printer is not working",         "Hardware"),
    ("locked out of my account",       "Account Access"),
    ("need to install new software",   "Software Request"),
    ("random issue with something",    "General Request"),
]

all_passed = True
for message, expected_type in test_cases:
    ticket_type, priority = triage(message)
    passed = ticket_type == expected_type
    if not passed:
        all_passed = False
    status = "PASS" if passed else "FAIL"
    print(f"  {status} — '{message}'")
    print(f"         Type: {ticket_type} | Priority: {priority}")

print("")
if all_passed:
    print("  PASSED — All triage rules working correctly")
else:
    print("  PARTIAL — Some rules need tuning")
print("")

# ── Summary ────────────────────────────────────────────────
print("=" * 55)
print("  ALL TESTS COMPLETE")
if ticket_id:
    print(f"  Ticket #{ticket_id} created in your staging portal")
    print(f"  Go verify: {CONFIG.CW_SITE}")
print("=" * 55)