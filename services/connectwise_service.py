import requests
import base64
from config.config import CONFIG

# Maps simple priority names to exact ConnectWise staging priority names
PRIORITY_MAP = {
    "High":   "Priority 1 - Emergency Response",
    "Medium": "Priority 3 - Normal Response",
    "Low":    "Priority 4 - Scheduled Maintenance",
    "urgent": "Priority 2 - Quick Response",
}


def _get_headers() -> dict:
    """Builds authentication headers for every ConnectWise API call."""
    credentials = f"{CONFIG.CW_COMPANY_ID}+{CONFIG.CW_PUBLIC_KEY}:{CONFIG.CW_PRIVATE_KEY}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "clientId":      CONFIG.CW_CLIENT_ID,
        "Content-Type":  "application/json"
    }


def _map_priority(priority: str) -> str:
    """Converts simple priority (High/Medium/Low) to CW staging priority name."""
    return PRIORITY_MAP.get(priority, CONFIG.CW_DEFAULT_PRIORITY)


def create_ticket(summary: str, priority: str, board: str,
                  ticket_type: str = "", user_name: str = "") -> dict:
    """Creates a new service ticket in ConnectWise Manage."""
    url = f"{CONFIG.CW_SITE}/v4_6_release/apis/3.0/service/tickets"

    # Map simple priority to exact CW priority name
    cw_priority = _map_priority(priority)

    payload = {
        "summary":  summary,
        "board":    {"name": board},
        "company":  {"id": CONFIG.CW_DEFAULT_COMPANY_ID},
        "priority": {"name": cw_priority},
        "initialDescription": f"Ticket created via Teams bot by {user_name}"
    }

    response = requests.post(
        url, json=payload, headers=_get_headers(), timeout=15
    )

    if not response.ok:
        raise Exception(
            f"HTTP {response.status_code} — {response.text[:500]}"
        )

    return response.json()


def add_note(ticket_id: int, note_text: str) -> dict:
    """Adds an internal note to an existing ConnectWise ticket."""
    url = f"{CONFIG.CW_SITE}/v4_6_release/apis/3.0/service/tickets/{ticket_id}/notes"
    payload = {
        "text":                  note_text,
        "detailDescriptionFlag": True,
        "internalAnalysisFlag":  False,
        "resolutionFlag":        False
    }
    response = requests.post(
        url, json=payload, headers=_get_headers(), timeout=15
    )
    if not response.ok:
        raise Exception(
            f"HTTP {response.status_code} — {response.text[:500]}"
        )
    return response.json()


def get_ticket(ticket_id: int) -> dict:
    """Retrieves a single ticket by its ID."""
    url = f"{CONFIG.CW_SITE}/v4_6_release/apis/3.0/service/tickets/{ticket_id}"
    response = requests.get(url, headers=_get_headers(), timeout=15)
    if not response.ok:
        raise Exception(
            f"HTTP {response.status_code} — {response.text[:500]}"
        )
    return response.json()


def find_company_by_name(name: str) -> list[dict]:
    """Searches for companies in ConnectWise by name (partial match)."""
    url = f"{CONFIG.CW_SITE}/v4_6_release/apis/3.0/company/companies"
    params = {
        "conditions": f"name contains '{name}'",
        "fields":     "id,name,status",
        "pageSize":   10,
    }
    response = requests.get(url, params=params, headers=_get_headers(), timeout=15)
    if not response.ok:
        raise Exception(f"HTTP {response.status_code} — {response.text[:500]}")
    return response.json()


# Common status name variants used across ConnectWise environments
_STATUS_ALIASES: dict[str, list[str]] = {
    "new":         ["New (not responded)", "New", "New Request"],
    "open":        ["Open", "In Progress", "Assigned"],
    "inprogress":  ["In Progress", "Working", "Assigned"],
    "closed":      ["Closed", "Completed", "Resolved"],
    "waiting":     ["Waiting Customer", "Waiting on Customer", "Pending Customer"],
}


def get_tickets_by_company(company_id: int, status: str = "New (not responded)") -> list:
    """Retrieves open tickets for a given company, trying status aliases if exact match returns nothing."""
    url = f"{CONFIG.CW_SITE}/v4_6_release/apis/3.0/service/tickets"

    def _fetch(status_name: str) -> list:
        params = {
            "conditions": f"company/id={company_id} and status/name='{status_name}'",
            "pageSize":   50,
        }
        r = requests.get(url, params=params, headers=_get_headers(), timeout=15)
        if not r.ok:
            raise Exception(f"HTTP {r.status_code} — {r.text[:500]}")
        return r.json()

    # Try exact status first
    results = _fetch(status)
    if results:
        return results

    # Try aliases for the normalised key
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