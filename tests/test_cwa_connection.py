"""
tests/test_cwa_connection.py
------------------------------
Incremental connection tests for ConnectWise Automate RMM.

Run only the tests your current API user has permission for.
As the CWA admin grants more permissions, uncomment the later tests.

Usage:
    python -m pytest tests/test_cwa_connection.py -v
    python -m pytest tests/test_cwa_connection.py -v -k "auth"   # auth only
    python -m pytest tests/test_cwa_connection.py -v -k "device" # device lookup only
"""

import os
import pytest
import requests
from dotenv import load_dotenv

load_dotenv()

CWA_BASE_URL = os.environ.get("CWA_BASE_URL", "").rstrip("/")
CWA_USERNAME = os.environ.get("CWA_USERNAME", "")
CWA_PASSWORD = os.environ.get("CWA_PASSWORD", "")
CWA_CLIENT_ID = os.environ.get("CWA_CLIENT_ID", "")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_token() -> str:
    """Authenticate and return a Bearer token. Raises on failure."""
    resp = requests.post(
        f"{CWA_BASE_URL}/cwa/api/v1/apitoken",
        json={"UserName": CWA_USERNAME, "Password": CWA_PASSWORD},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    data  = resp.json()
    token = data.get("AccessToken") or data.get("access_token") or data.get("token") or ""
    assert token, f"Auth succeeded but no token found in response: {data}"
    return token


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Token auth (run this first with current permissions)
# ─────────────────────────────────────────────────────────────────────────────

def test_cwa_credentials_are_configured():
    """Fail fast if .env is missing CWA values — nothing else will work."""
    assert CWA_BASE_URL,  "CWA_BASE_URL is not set in .env"
    assert CWA_USERNAME,  "CWA_USERNAME is not set in .env"
    assert CWA_PASSWORD,  "CWA_PASSWORD is not set in .env"
    assert CWA_BASE_URL.startswith("http"), "CWA_BASE_URL must start with http(s)://"


def test_cwa_auth_endpoint_reachable():
    """Confirm the CWA server responds (even if auth fails)."""
    assert CWA_BASE_URL, "CWA_BASE_URL is not set — skipping"
    try:
        resp = requests.post(
            f"{CWA_BASE_URL}/cwa/api/v1/apitoken",
            json={"UserName": "__probe__", "Password": "__probe__"},
            timeout=10,
        )
        # 401 means the server is reachable and auth is working — we just used wrong creds
        assert resp.status_code in (200, 401, 403), (
            f"Unexpected status {resp.status_code} — server may be unreachable or URL is wrong."
        )
    except requests.exceptions.ConnectionError as exc:
        pytest.fail(f"Cannot reach CWA server at {CWA_BASE_URL}: {exc}")
    except requests.exceptions.Timeout:
        pytest.fail(f"CWA server timed out at {CWA_BASE_URL}")


def test_cwa_token_auth():
    """
    ✅ STAGE 1 — Validate your API credentials return a token.
    Requires: CWA_BASE_URL, CWA_USERNAME, CWA_PASSWORD in .env
    Permission needed: API login only (no extra CWA permissions required)
    """
    if not CWA_BASE_URL or not CWA_USERNAME or not CWA_PASSWORD:
        pytest.skip("CWA credentials not configured in .env")

    token = _get_token()
    assert len(token) > 20, f"Token looks too short to be valid: {token!r}"
    print(f"\n✅ Auth succeeded — token length: {len(token)} chars")
    print(f"   Token preview: {token[:12]}...")


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Computer listing (requires 'Computers - View' permission in CWA)
# Uncomment once your CWA admin grants this permission.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skip(reason="Requires 'Computers - View' permission — uncomment once granted")
def test_cwa_list_computers():
    """
    STAGE 2 — Confirm the API user can list computers scoped to CWA_CLIENT_ID.
    Permission needed: Computers - View (scoped to client)
    """
    token = _get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }

    params = {"pageSize": 5, "page": 1}
    if CWA_CLIENT_ID:
        params["condition"] = f"ClientId={CWA_CLIENT_ID}"

    resp = requests.get(
        f"{CWA_BASE_URL}/cwa/api/v1/computers",
        headers=headers,
        params=params,
        timeout=15,
    )

    if resp.status_code == 403:
        pytest.fail(
            "403 Forbidden — API user needs 'Computers - View' permission in CWA.\n"
            "Ask your CWA admin to grant it under System > Security > Roles."
        )

    resp.raise_for_status()
    computers = resp.json() if isinstance(resp.json(), list) else resp.json().get("data", [])
    print(f"\n✅ Computer listing succeeded — found {len(computers)} computers")
    for c in computers[:3]:
        print(f"   {c.get('Id')} | {c.get('ComputerName')} | Last user: {c.get('LastLoggedInUser')}")


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Script listing (requires 'Scripts - View' permission in CWA)
# Uncomment once your CWA admin grants this permission.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skip(reason="Requires 'Scripts - View' permission — uncomment once granted")
def test_cwa_list_scripts():
    """
    STAGE 3 — Confirm the API user can list available scripts.
    Permission needed: Scripts - View
    """
    token = _get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }

    resp = requests.get(
        f"{CWA_BASE_URL}/cwa/api/v1/scripts",
        headers=headers,
        params={"pageSize": 10},
        timeout=15,
    )

    if resp.status_code == 403:
        pytest.fail(
            "403 Forbidden — API user needs 'Scripts - View' permission in CWA."
        )

    resp.raise_for_status()
    scripts = resp.json() if isinstance(resp.json(), list) else resp.json().get("data", [])
    print(f"\n✅ Script listing succeeded — found {len(scripts)} scripts")
    for s in scripts[:5]:
        print(f"   ID: {s.get('Id')} | Name: {s.get('Name')}")


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 — Script execution (requires 'Scripts - Run' permission in CWA)
# Uncomment once your CWA admin grants this permission AND script IDs are set.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skip(reason="Requires 'Scripts - Run' permission + CWA_SCRIPT_* set in .env")
def test_cwa_run_script_on_device():
    """
    STAGE 4 — Confirm a script can be triggered on a specific computer.
    Permission needed: Scripts - Run Scheduled Scripts
    Prerequisites: CWA_SCRIPT_PRINTER_STATUS and a known computer ID must be set.
    """
    script_id   = int(os.environ.get("CWA_SCRIPT_PRINTER_STATUS", 0))
    computer_id = int(os.environ.get("CWA_TEST_COMPUTER_ID", 0))

    if not script_id:
        pytest.skip("CWA_SCRIPT_PRINTER_STATUS not set in .env")
    if not computer_id:
        pytest.skip("CWA_TEST_COMPUTER_ID not set in .env — set it to a known online computer ID")

    token = _get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }

    resp = requests.post(
        f"{CWA_BASE_URL}/cwa/api/v1/computers/{computer_id}/scripts/{script_id}",
        json={},
        headers=headers,
        timeout=20,
    )

    if resp.status_code == 403:
        pytest.fail(
            "403 Forbidden — API user needs 'Scripts - Run Scheduled Scripts' permission."
        )
    if resp.status_code == 404:
        pytest.fail(
            f"404 Not Found — script ID {script_id} or computer ID {computer_id} not found."
        )

    resp.raise_for_status()
    print(f"\n✅ Script triggered — status: {resp.status_code}")
    if resp.content:
        print(f"   Response: {resp.json()}")
