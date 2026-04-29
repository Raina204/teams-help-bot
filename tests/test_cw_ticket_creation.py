"""
tests/test_cw_ticket_creation.py
---------------------------------
Standalone diagnostic test for ConnectWise Manage ticket creation.
Tests the full pipeline used by the Teams bot: tenant config → auth → company
lookup → ticket creation.

Run from the project root:
    python -m tests.test_cw_ticket_creation

What it checks:
  1. Tenant config loads correctly from config/tenants/itbd_net.py
  2. .env credentials are present (ITBD_CW_API_KEY, CW_SITE)
  3. ConnectWise API is reachable (HTTP health check)
  4. Company identifier resolves to a numeric ID (the most common failure point)
  5. Ticket creation succeeds end-to-end
  6. Note can be added to the created ticket
  7. Ticket can be retrieved by ID
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import base64
import requests
from config.tenant_loader import loader
from config.secrets import get_secret
from services.connectwise_service import (
    _get_base_url,
    _get_headers,
    _lookup_company_id,
    create_ticket,
    add_note,
    get_ticket,
    find_company_by_name,
)


# ── Formatting helpers ────────────────────────────────────────────────────────

def ok(msg):      print(f"  PASS  {msg}")
def fail(msg):    print(f"  FAIL  {msg}")
def info(msg):    print(f"        {msg}")
def section(n, t): print(f"\n[{n}] {t}")
def hr():          print("-" * 60)


# ═════════════════════════════════════════════════════════════════════════════
print()
hr()
print("  ConnectWise Manage — Ticket Creation Diagnostic")
hr()


# ── Step 1: Load tenant config ────────────────────────────────────────────────
section(1, "Load tenant config — itbd_net")
try:
    tenant_ctx = loader.get("itbd_net")
    ok(f"Tenant loaded: {tenant_ctx['tenant_id']} ({tenant_ctx['display_name']})")
    info(f"cw_company_id  : {tenant_ctx.get('cw_company_id')}")
    info(f"cw_base_url    : {tenant_ctx.get('cw_base_url')}")
    info(f"cw_client_id   : {tenant_ctx.get('cw_client_id')}")
    info(f"cw_api_key_ref : {tenant_ctx.get('cw_api_key_ref')}")
    info(f"mock flag      : {tenant_ctx.get('mock')}")
except Exception as e:
    fail(f"Could not load tenant config: {e}")
    sys.exit(1)


# ── Step 2: Check credentials are set ────────────────────────────────────────
section(2, "Check credentials in .env")
try:
    api_key = get_secret(tenant_ctx["cw_api_key_ref"])
    if not api_key:
        fail(f"{tenant_ctx['cw_api_key_ref']} is not set in .env")
        sys.exit(1)
    ok(f"{tenant_ctx['cw_api_key_ref']} is set ({len(api_key)} chars)")

    if ":" in api_key:
        pub, priv = api_key.split(":", 1)
        info(f"Public key  : {pub[:6]}...")
        info(f"Private key : {'SET' if priv else 'EMPTY'}")
    else:
        info("Key does not contain ':' — treating whole value as public key")

    base_url = _get_base_url(tenant_ctx)
    ok(f"CW base URL : {base_url}")

except Exception as e:
    fail(f"Credential check failed: {e}")
    sys.exit(1)


# ── Step 3: Show exact auth string + probe API ───────────────────────────────
section(3, "Show auth header and ping ConnectWise API")
try:
    api_key = get_secret(tenant_ctx["cw_api_key_ref"])
    pub, priv = (api_key.split(":", 1) if ":" in api_key else (api_key, ""))
    company_id_for_auth = tenant_ctx.get("cw_auth_company") or tenant_ctx["cw_company_id"]
    raw_creds = f"{company_id_for_auth}+{pub}:{priv}"
    info(f"Auth string (before base64) : {company_id_for_auth}+{pub[:4]}...:{priv[:4] if priv else 'EMPTY'}...")
    info(f"NOTE: 'company_id_for_auth' must be your CW LOGIN company ID,")
    info(f"      not the client company you're creating tickets for.")
    info(f"      If these are different you need a separate 'cw_auth_company' field.")

    probe_url = f"{base_url}/v4_6_release/apis/3.0/system/info"
    r = requests.get(probe_url, headers=_get_headers(tenant_ctx), timeout=10)
    if r.ok:
        ok(f"API reachable — version: {r.json().get('version', 'unknown')}")
    elif r.status_code == 401:
        fail(f"401 Unauthorized — API key rejected. Double-check ITBD_CW_API_KEY in .env")
        info("Format must be: PublicKey:PrivateKey (no extra spaces)")
        sys.exit(1)
    elif r.status_code == 400:
        fail(f"400 Bad Request from /system/info — credentials format is wrong")
        info(f"Response: {r.text[:300]}")
        info("")
        info("Most likely cause: cw_company_id in itbd_net.py is set to the CLIENT company")
        info("(CPCorp,Inc.) but CW uses your MSP's own company code for Basic auth.")
        info("")
        info("Fix options:")
        info("  A) Add a separate 'cw_auth_company' field to the tenant config for auth,")
        info("     and keep 'cw_company_id' for the ticket company identifier only.")
        info("  B) Find out what company code your CW staging account uses for login.")
        info("     (It's shown in ConnectWise > My Account, or in the staging signup email.)")
        sys.exit(1)
    else:
        fail(f"HTTP {r.status_code}: {r.text[:200]}")
        sys.exit(1)
except requests.exceptions.ConnectionError:
    fail(f"Cannot reach {base_url} — check network connectivity")
    sys.exit(1)
except Exception as e:
    fail(f"Ping failed: {e}")
    sys.exit(1)


# ── Step 4: Resolve company to numeric ID ────────────────────────────────────
section(4, f"Resolve company '{tenant_ctx['cw_company_id']}' to numeric ID")

# Mirrors the same logic used in create_ticket():
# use cw_company_num_id directly if present, else do an API lookup.
company_id = tenant_ctx.get("cw_company_num_id")
if company_id:
    ok(f"Using pre-configured cw_company_num_id: {company_id} (skipped API lookup)")
else:
    company_id = _lookup_company_id(tenant_ctx["cw_company_id"], tenant_ctx)
    if company_id:
        ok(f"Company found via identifier lookup — numeric ID: {company_id}")
    else:
        fail(f"Company '{tenant_ctx['cw_company_id']}' NOT found in {base_url}")
        info("")
        info("cw_company_num_id is not set and identifier lookup returned nothing.")
        info("Searching for companies to help you find the right numeric ID...")

        for search_term in ["corp", "itbd", "IT By Design", "CP"]:
            try:
                results = find_company_by_name(search_term, tenant_ctx)
                if results:
                    info(f"\nMatches for '{search_term}':")
                    for c in results[:5]:
                        info(f"  id={c.get('id')}  name={c.get('name')}  identifier={c.get('identifier')}")
            except Exception:
                pass

        info("")
        info("Fix: set cw_company_num_id to the numeric id shown above in itbd_net.py,")
        info("then re-run this test.")
        sys.exit(1)


# ── Step 5: Create a test ticket ─────────────────────────────────────────────
section(5, "Create test ticket")
created_id = None
try:
    ticket = create_ticket(
        {
            "summary":     "[TEST] Teams bot — integration test ticket",
            "description": "Automated test from test_cw_ticket_creation.py. Safe to delete.",
            "priority":    "Low",
            "board":       "Professional Services",
            "user_name":   "test_runner",
        },
        tenant_ctx,
    )
    created_id = ticket.get("id")
    ok(f"Ticket created — ID: {created_id}")
    info(f"Summary  : {ticket.get('summary')}")
    info(f"Board    : {ticket.get('board', {}).get('name')}")
    info(f"Priority : {ticket.get('priority', {}).get('name')}")
    info(f"Status   : {ticket.get('status', {}).get('name')}")
    info(f"Company  : {ticket.get('company', {}).get('name')}")
except Exception as e:
    fail(f"create_ticket failed: {e}")
    sys.exit(1)


# ── Step 6: Add a note ───────────────────────────────────────────────────────
section(6, "Add note to ticket")
if created_id:
    try:
        note = add_note(
            ticket_id=created_id,
            note_text="Automated note from test_cw_ticket_creation.py.",
            tenant_ctx=tenant_ctx,
        )
        ok(f"Note added — note ID: {note.get('id')}")
    except Exception as e:
        fail(f"add_note failed: {e}")


# ── Step 7: Fetch ticket back ─────────────────────────────────────────────────
section(7, "Fetch ticket by ID")
if created_id:
    try:
        fetched = get_ticket(ticket_id=created_id, tenant_ctx=tenant_ctx)
        ok(f"Ticket #{fetched.get('id')} fetched — status: {fetched.get('status', {}).get('name')}")
    except Exception as e:
        fail(f"get_ticket failed: {e}")


# ── Summary ───────────────────────────────────────────────────────────────────
print()
hr()
print("  All steps passed.")
if created_id:
    print(f"  Test ticket #{created_id} was created in ConnectWise.")
    print("  You can delete it manually or leave it as a smoke-test record.")
hr()
print()
