"""
services/connectwise_service.py
--------------------------------
ConnectWise Manage API integration — multi-tenant aware.

Every function accepts tenant_ctx as its last argument.
Credentials and company scoping are derived from tenant_ctx at
runtime — never from global CONFIG.

Global CONFIG is still used for:
  - CW_SITE      (your ConnectWise instance URL — same for all tenants)
  - CW_DEFAULT_PRIORITY (fallback priority label — same for all tenants)

Per-tenant values come from tenant_ctx:
  - cw_company_id    → scopes every ticket to the correct client company
  - cw_api_key_ref   → resolved via get_secret() to the actual API key
  - cw_client_id     → client ID registered in ConnectWise for this tenant
  - cw_base_url      → optional per-tenant CW URL override
"""

import base64
import requests

from config.config import CONFIG
from config.secrets import get_secret

# ---------------------------------------------------------------------------
# Priority mapping
# ---------------------------------------------------------------------------

PRIORITY_MAP = {
    "High":   "Priority 1 - Emergency Response",
    "Medium": "Priority 3 - Normal Response",
    "Low":    "Priority 4 - Scheduled Maintenance",
    "urgent": "Priority 2 - Quick Response",
}

# ---------------------------------------------------------------------------
# Status aliases (unchanged — company-level, not tenant-level)
# ---------------------------------------------------------------------------

_STATUS_ALIASES: dict[str, list[str]] = {
    "new":        ["New (not responded)", "New", "New Request"],
    "open":       ["Open", "In Progress", "Assigned"],
    "inprogress": ["In Progress", "Working", "Assigned"],
    "closed":     ["Closed", "Completed", "Resolved"],
    "waiting":    ["Waiting Customer", "Waiting on Customer", "Pending Customer"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_headers(tenant_ctx: dict) -> dict:
    """
    Build authentication headers scoped to this tenant's ConnectWise account.

    Uses tenant_ctx to resolve:
      - cw_company_id  : the client's ConnectWise company identifier
      - cw_api_key_ref : reference name resolved to actual key via get_secret()
      - cw_client_id   : the registered client ID for this tenant

    Args:
        tenant_ctx: Resolved tenant config dict.

    Returns:
        Dict of HTTP headers for the ConnectWise API request.
    """
    if not tenant_ctx.get("cw_company_id"):
        raise ValueError(
            "tenant_ctx is missing 'cw_company_id' — the tenant was not resolved "
            "before calling this function. Ensure user_tenant_id is injected into "
            "tool call args so execute_tool() can load the correct tenant config."
        )

    company_id  = tenant_ctx.get("cw_auth_company") or tenant_ctx["cw_company_id"]
    client_id   = tenant_ctx["cw_client_id"]

    # Resolve the API key reference to the actual key at runtime.
    # For mock tenants, get_secret() reads from .env.mock.
    # For real tenants, it reads from .env.real or Azure Key Vault.
    api_key = get_secret(tenant_ctx["cw_api_key_ref"])

    # ConnectWise Basic auth format: "CompanyID+PublicKey:PrivateKey"
    # For API key auth the key is split on ":" in the env var.
    # e.g. MOCK_A_CW_KEY=public_key:private_key
    if ":" in api_key:
        public_key, private_key = api_key.split(":", 1)
    else:
        # Fallback: treat the whole value as public key, use empty private key
        public_key, private_key = api_key, ""

    credentials = f"{company_id}+{public_key}:{private_key}"
    encoded     = base64.b64encode(credentials.encode()).decode()

    return {
        "Authorization": f"Basic {encoded}",
        "clientId":      client_id,
        "Content-Type":  "application/json",
    }


def _get_base_url(tenant_ctx: dict) -> str:
    """
    Return the ConnectWise API base URL for this tenant.
    Uses per-tenant cw_base_url if set, otherwise falls back to global CONFIG.CW_SITE.

    Args:
        tenant_ctx: Resolved tenant config dict.

    Returns:
        Base URL string e.g. 'https://api-na.myconnectwise.net'.
    """
    return tenant_ctx.get("cw_base_url") or CONFIG.CW_SITE


def _map_priority(priority: str) -> str:
    """Convert simple priority label to ConnectWise staging priority name."""
    return PRIORITY_MAP.get(priority, CONFIG.CW_DEFAULT_PRIORITY)


# ---------------------------------------------------------------------------
# Public API — all functions require tenant_ctx as the last argument
# ---------------------------------------------------------------------------

def _lookup_company_id(identifier: str, tenant_ctx: dict) -> int | None:
    """
    Resolve a ConnectWise company string identifier to its numeric ID.
    Returns None if the company cannot be found.
    """
    base_url = _get_base_url(tenant_ctx)
    url      = f"{base_url}/v4_6_release/apis/3.0/company/companies"
    params   = {
        "conditions": f"identifier='{identifier}'",
        "fields":     "id,identifier,name",
        "pageSize":   1,
    }
    try:
        r = requests.get(url, params=params, headers=_get_headers(tenant_ctx), timeout=10)
        if r.ok and r.json():
            return r.json()[0]["id"]
    except Exception:
        pass
    return None


def create_ticket(
    data: dict,
    tenant_ctx: dict,
) -> dict:
    """
    Create a new service ticket in ConnectWise Manage, scoped to this
    tenant's company.

    Args:
        data: Ticket fields dict. Supported keys:
                  summary     (str, required)
                  description (str, optional)
                  priority    (str, optional) — High / Medium / Low / urgent
                  board       (str, optional) — board name
                  ticket_type (str, optional)
                  user_name   (str, optional) — display name of requesting user
        tenant_ctx: Resolved tenant config dict.

    Returns:
        ConnectWise ticket response dict (contains 'id', 'summary', etc.)

    Raises:
        Exception: on non-2xx HTTP response or company not found.
    """
    base_url   = _get_base_url(tenant_ctx)
    url        = f"{base_url}/v4_6_release/apis/3.0/service/tickets"
    identifier = tenant_ctx["cw_company_id"]

    # Use the pre-configured numeric ID if available — avoids a lookup API call
    # and handles staging environments where the identifier field is null.
    company_num_id = tenant_ctx.get("cw_company_num_id")

    if not company_num_id:
        company_num_id = _lookup_company_id(identifier, tenant_ctx)

    if not company_num_id:
        raise Exception(
            f"ConnectWise company '{identifier}' not found in "
            f"{base_url}. "
            f"Check that cw_company_id in the tenant config matches the "
            f"exact identifier shown in ConnectWise > Company > Companies, "
            f"or set cw_company_num_id to the numeric company ID directly."
        )

    cw_priority = _map_priority(data.get("priority", "Medium"))
    user_name   = data.get("user_name", "")

    payload = {
        "summary":  data.get("summary", ""),
        "board":    {"name": data.get("board", "Professional Services")},
        "company":  {"id": company_num_id},
        "priority": {"name": cw_priority},
        "initialDescription": (
            data.get("description")
            or f"Ticket created via Teams bot by {user_name}"
        ),
    }

    response = requests.post(
        url, json=payload, headers=_get_headers(tenant_ctx), timeout=15
    )
    if not response.ok:
        raise Exception(
            f"ConnectWise create_ticket failed "
            f"[tenant={tenant_ctx['tenant_id']}] "
            f"HTTP {response.status_code} — {response.text[:500]}"
        )
    return response.json()


def add_note(
    ticket_id: int,
    note_text: str,
    tenant_ctx: dict,
) -> dict:
    """
    Add an internal note to an existing ConnectWise ticket.

    Args:
        ticket_id:  Numeric ConnectWise ticket ID.
        note_text:  Text content of the note.
        tenant_ctx: Resolved tenant config dict.

    Returns:
        ConnectWise note response dict.

    Raises:
        Exception: on non-2xx HTTP response.
    """
    base_url = _get_base_url(tenant_ctx)
    url      = (
        f"{base_url}/v4_6_release/apis/3.0/service/tickets/{ticket_id}/notes"
    )
    payload = {
        "text":                  note_text,
        "detailDescriptionFlag": True,
        "internalAnalysisFlag":  False,
        "resolutionFlag":        False,
    }
    response = requests.post(
        url, json=payload, headers=_get_headers(tenant_ctx), timeout=15
    )
    if not response.ok:
        raise Exception(
            f"ConnectWise add_note failed "
            f"[tenant={tenant_ctx['tenant_id']}] "
            f"HTTP {response.status_code} — {response.text[:500]}"
        )
    return response.json()


def get_ticket(
    ticket_id: int,
    tenant_ctx: dict,
) -> dict:
    """
    Retrieve a single ConnectWise ticket by ID, scoped to this tenant.

    Args:
        ticket_id:  Numeric ConnectWise ticket ID.
        tenant_ctx: Resolved tenant config dict.

    Returns:
        ConnectWise ticket dict.

    Raises:
        Exception: on non-2xx HTTP response.
    """
    base_url = _get_base_url(tenant_ctx)
    url      = f"{base_url}/v4_6_release/apis/3.0/service/tickets/{ticket_id}"

    response = requests.get(
        url, headers=_get_headers(tenant_ctx), timeout=15
    )
    if not response.ok:
        raise Exception(
            f"ConnectWise get_ticket failed "
            f"[tenant={tenant_ctx['tenant_id']}] "
            f"HTTP {response.status_code} — {response.text[:500]}"
        )
    return response.json()


def find_company_by_name(
    name: str,
    tenant_ctx: dict,
) -> list[dict]:
    """
    Search for companies in ConnectWise by name (partial match).
    Scoped to this tenant's ConnectWise instance.

    Args:
        name:       Partial company name to search for.
        tenant_ctx: Resolved tenant config dict.

    Returns:
        List of matching company dicts.

    Raises:
        Exception: on non-2xx HTTP response.
    """
    base_url = _get_base_url(tenant_ctx)
    url      = f"{base_url}/v4_6_release/apis/3.0/company/companies"
    params   = {
        "conditions": f"name contains '{name}'",
        "fields":     "id,name,status",
        "pageSize":   10,
    }
    response = requests.get(
        url, params=params, headers=_get_headers(tenant_ctx), timeout=15
    )
    if not response.ok:
        raise Exception(
            f"ConnectWise find_company_by_name failed "
            f"[tenant={tenant_ctx['tenant_id']}] "
            f"HTTP {response.status_code} — {response.text[:500]}"
        )
    return response.json()


def get_tickets_by_company(
    company_id: int,
    tenant_ctx: dict,
    status: str = "New (not responded)",
) -> list[dict]:
    """
    Retrieve open tickets for a company, trying status aliases if the
    exact status name returns no results.

    Args:
        company_id: Numeric ConnectWise company ID.
        tenant_ctx: Resolved tenant config dict.
        status:     Ticket status filter (default: 'New (not responded)').

    Returns:
        List of ticket dicts. Empty list if none found.

    Raises:
        Exception: on non-2xx HTTP response.
    """
    base_url = _get_base_url(tenant_ctx)
    url      = f"{base_url}/v4_6_release/apis/3.0/service/tickets"

    def _fetch(status_name: str) -> list:
        params = {
            "conditions": (
                f"company/id={company_id} and "
                f"status/name='{status_name}'"
            ),
            "pageSize": 50,
        }
        r = requests.get(
            url, params=params, headers=_get_headers(tenant_ctx), timeout=15
        )
        if not r.ok:
            raise Exception(
                f"ConnectWise get_tickets_by_company failed "
                f"[tenant={tenant_ctx['tenant_id']}] "
                f"HTTP {r.status_code} — {r.text[:500]}"
            )
        return r.json()

    # Try exact status first
    results = _fetch(status)
    if results:
        return results

    # Fall back through known aliases for this status
    key = status.lower().replace(" ", "").replace("(", "").replace(")", "")
    for alias_key, variants in _STATUS_ALIASES.items():
        if alias_key in key or key in alias_key:
            for variant in variants:
                if variant == status:
                    continue
                results = _fetch(variant)
                if results:
                    return results

    return []