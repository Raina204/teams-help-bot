"""
Live integration test for ConnectWise Manage — ticket creation and note adding.
Run from the project root:
    python -m tests.test_connectwise
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.config import CONFIG
from services.connectwise_service import create_ticket, add_note, get_ticket


def ok(msg):     print(f"  PASSED — {msg}")
def fail(msg):   print(f"  FAILED — {msg}")
def info(msg):   print(f"  INFO   — {msg}")
def section(t):  print(f"\nTEST {t}")


print("\n" + "=" * 55)
print("  ConnectWise Manage — Live Integration Test")
print("=" * 55)
print(f"  Site:         {CONFIG.CW_SITE}")
print(f"  Company ID:   {CONFIG.CW_COMPANY_ID}")
print(f"  Public key:   {'SET (' + CONFIG.CW_PUBLIC_KEY[:6] + '...)' if CONFIG.CW_PUBLIC_KEY else 'NOT SET'}")
print(f"  Private key:  {'SET' if CONFIG.CW_PRIVATE_KEY else 'NOT SET'}")
print(f"  Client ID:    {'SET (' + CONFIG.CW_CLIENT_ID[:8] + '...)' if CONFIG.CW_CLIENT_ID else 'NOT SET'}")
print(f"  Default board:      {CONFIG.CW_DEFAULT_BOARD}")
print(f"  Default company ID: {CONFIG.CW_DEFAULT_COMPANY_ID}")
print("=" * 55)


# ── Test 1: Create a ticket ────────────────────────────────────────────────
section("1 — Create ticket (Medium priority)")
created_ticket_id = None
try:
    ticket = create_ticket(
        summary="[TEST] Teams bot — automated integration test",
        priority="Medium",
        board=CONFIG.CW_DEFAULT_BOARD,
        ticket_type="",
        user_name="test_runner",
    )
    created_ticket_id = ticket.get("id")
    ok(f"Ticket created — ID: {created_ticket_id}")
    info(f"Summary:  {ticket.get('summary')}")
    info(f"Board:    {ticket.get('board', {}).get('name')}")
    info(f"Priority: {ticket.get('priority', {}).get('name')}")
    info(f"Status:   {ticket.get('status', {}).get('name')}")
    info(f"Company:  {ticket.get('company', {}).get('name')}")
except Exception as e:
    fail(str(e))
    info("Check CW_SITE, CW_COMPANY_ID, CW_PUBLIC_KEY, CW_PRIVATE_KEY, CW_CLIENT_ID in .env")


# ── Test 2: Add a note to the ticket ──────────────────────────────────────
section("2 — Add note to ticket")
if created_ticket_id:
    try:
        note = add_note(
            ticket_id=created_ticket_id,
            note_text="This is an automated note added by the Teams bot integration test.",
        )
        ok(f"Note added — note ID: {note.get('id')}")
        info(f"Text:     {note.get('text', '')[:80]}")
        info(f"Detail:   {note.get('detailDescriptionFlag')}")
        info(f"Internal: {note.get('internalAnalysisFlag')}")
    except Exception as e:
        fail(str(e))
else:
    print("  SKIPPED — ticket was not created in Test 1")


# ── Test 3: Re-fetch ticket and confirm it exists ─────────────────────────
section("3 — Fetch created ticket by ID")
if created_ticket_id:
    try:
        fetched = get_ticket(created_ticket_id)
        ok(f"Ticket #{fetched.get('id')} fetched successfully")
        info(f"Summary:  {fetched.get('summary')}")
        info(f"Status:   {fetched.get('status', {}).get('name')}")
    except Exception as e:
        fail(str(e))
else:
    print("  SKIPPED — ticket was not created in Test 1")


print(f"\n{'=' * 55}")
print("  Tests complete")
if created_ticket_id:
    print(f"\n  Created test ticket ID: {created_ticket_id}")
    print("  You can delete it manually in ConnectWise or leave it as a smoke-test record.")
print(f"{'=' * 55}\n")
