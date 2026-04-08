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


def get_tickets_by_company(company_id: int, status: str = "New") -> list:
    """Retrieves open tickets for a given company."""
    url = f"{CONFIG.CW_SITE}/v4_6_release/apis/3.0/service/tickets"
    params = {
        "conditions": f"company/id={company_id} and status/name='{status}'",
        "pageSize": 25
    }
    response = requests.get(
        url, params=params, headers=_get_headers(), timeout=15
    )
    if not response.ok:
        raise Exception(
            f"HTTP {response.status_code} — {response.text[:500]}"
        )
    return response.json()