"""
mcp_tools/server.py

Exposes the Teams Bot's ConnectWise Manage and ConnectWise Automate RMM
capabilities as MCP tools. Any MCP-compatible AI client (Claude Desktop,
etc.) can discover and invoke these tools through the /mcp SSE endpoint.

Tool categories
───────────────
  ConnectWise Manage   →  mcp_create_ticket, mcp_add_note,
                          mcp_get_ticket,    mcp_get_tickets_by_company
  ConnectWise Automate →  mcp_find_device,   mcp_run_diagnostics,
                          mcp_reset_outlook, mcp_change_timezone

All RMM tools require a tenant_id parameter so device queries and script
execution are scoped to the correct client's ConnectWise Automate instance.
"""

from __future__ import annotations

import os
import sys

# ── Project root on path so sibling packages resolve correctly ────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP

from config.config import CONFIG
from config.tenant_loader import loader
from services.connectwise_service import (
    add_note,
    create_ticket,
    find_company_by_name,
    get_ticket,
    get_tickets_by_company,
)
from services.rmm_service import (
    change_timezone,
    find_device_by_user,
    reset_outlook,
    run_diagnostics,
)
from services.printer_service import (
    restart_spooler,
    check_printer_status,
    clear_queue,
    list_printers,
)
from services.timezone_service import IANA_TO_WINDOWS
from dialogs.slot_filling import (
    is_active,
    start_slot_filling,
    handle_slot_turn,
)

# ── MCP server instance ───────────────────────────────────────────────────────
mcp = FastMCP("TeamsBotMCP")

# ── In-memory slot-filling session (persists for the lifetime of this process) ─
_sf_session: dict = {}


def _resolve_tenant(tenant_id: str) -> dict:
    """
    Resolve a tenant_id string to its full config dict via TenantLoader.
    Raises ModuleNotFoundError if the tenant_id is not registered.
    """
    return loader.get(tenant_id)


# ═════════════════════════════════════════════════════════════════════════════
# ConnectWise Manage Tools
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def mcp_create_ticket(
    summary: str,
    priority: str,
    tenant_id: str,
    user_name: str = "",
    board: str = "",
) -> dict:
    """
    Create a new service ticket in ConnectWise Manage.

    Args:
        summary:   Short description of the issue (one line).
        priority:  Severity level — High | Medium | Low | urgent
        tenant_id: Tenant ID to scope the ticket to the correct CW company.
        user_name: Display name of the user raising the ticket.
        board:     Target ConnectWise board. Falls back to CW_DEFAULT_BOARD
                   from .env when omitted.

    Returns:
        dict with ticket_id, summary, status, priority, board.
    """
    tenant_ctx     = _resolve_tenant(tenant_id)
    resolved_board = board or CONFIG.CW_DEFAULT_BOARD

    result = create_ticket(
        {
            "summary":   summary,
            "priority":  priority,
            "board":     resolved_board,
            "user_name": user_name,
        },
        tenant_ctx,
    )

    return {
        "ticket_id": result.get("id"),
        "summary":   result.get("summary"),
        "status":    result.get("status",   {}).get("name"),
        "priority":  result.get("priority", {}).get("name"),
        "board":     result.get("board",    {}).get("name"),
    }


@mcp.tool()
def mcp_add_note(ticket_id: int, note_text: str, tenant_id: str) -> dict:
    """
    Append a note to an existing ConnectWise ticket.

    Args:
        ticket_id: Numeric ConnectWise ticket ID.
        note_text: Text content to add as a note.
        tenant_id: Tenant ID to scope to the correct CW instance.

    Returns:
        dict with note_id, ticket_id, and added confirmation.
    """
    tenant_ctx = _resolve_tenant(tenant_id)
    result = add_note(ticket_id, note_text, tenant_ctx)

    return {
        "note_id":   result.get("id"),
        "ticket_id": ticket_id,
        "added":     True,
    }


@mcp.tool()
def mcp_get_ticket(ticket_id: int, tenant_id: str) -> dict:
    """
    Retrieve the current details and status of a ConnectWise ticket.

    Args:
        ticket_id: Numeric ConnectWise ticket ID.
        tenant_id: Tenant ID to scope to the correct CW instance.

    Returns:
        dict with ticket_id, summary, status, priority, board, owner.
    """
    tenant_ctx = _resolve_tenant(tenant_id)
    result = get_ticket(ticket_id, tenant_ctx)

    return {
        "ticket_id": result.get("id"),
        "summary":   result.get("summary"),
        "status":    result.get("status",   {}).get("name"),
        "priority":  result.get("priority", {}).get("name"),
        "board":     result.get("board",    {}).get("name"),
        "owner":     result.get("owner",    {}).get("name"),
    }


@mcp.tool()
def mcp_find_company(name: str, tenant_id: str) -> list[dict]:
    """
    Search for a company in ConnectWise by name (partial match).

    Use this FIRST when the user mentions a company name but you don't
    have its numeric ID. Returns matching companies with their IDs so
    you can then call mcp_get_tickets_by_company.

    Args:
        name:      Full or partial company name (e.g. "IT By Design", "ITBD").
        tenant_id: Tenant ID to scope to the correct CW instance.

    Returns:
        List of dicts with company_id, name, status.
    """
    tenant_ctx = _resolve_tenant(tenant_id)
    results = find_company_by_name(name, tenant_ctx)
    return [
        {
            "company_id": c.get("id"),
            "name":       c.get("name"),
            "status":     (c.get("status") or {}).get("name"),
        }
        for c in results
    ]


@mcp.tool()
async def mcp_ticket_conversation(user_message: str) -> str:
    """
    Guided ticket creation via slot-filling conversation.

    IMPORTANT: Use this tool for multi-turn ticket creation.
    - Call it with the user's exact message each turn.
    - Relay the tool's response back to the user word-for-word.
    - Do NOT answer slot questions yourself — always pass the user's reply to this tool.
    - Keep calling it until the response starts with "✅ Ticket".

    The tool handles: intent detection, asking one question at a time,
    validation, inline corrections, confirmation, and real CW ticket creation.
    """
    global _sf_session

    if is_active(_sf_session):
        return await handle_slot_turn(_sf_session, user_message)
    else:
        return start_slot_filling(_sf_session, user_message)


@mcp.tool()
def mcp_get_tickets_by_company(
    company_id: int,
    tenant_id: str,
    status: str = "New (not responded)",
) -> list[dict]:
    """
    List tickets for a specific company in ConnectWise.

    If you only have a company name (not ID), call mcp_find_company first.
    Common status values: "New (not responded)", "In Progress",
    "Waiting Customer", "Closed".

    Args:
        company_id: Numeric ConnectWise company ID.
        tenant_id:  Tenant ID to scope to the correct CW instance.
        status:     Ticket status to filter by.

    Returns:
        List of dicts with ticket_id, summary, status, priority.
    """
    tenant_ctx = _resolve_tenant(tenant_id)
    tickets = get_tickets_by_company(company_id, tenant_ctx, status)

    return [
        {
            "ticket_id": t.get("id"),
            "summary":   t.get("summary"),
            "status":    t.get("status",   {}).get("name"),
            "priority":  t.get("priority", {}).get("name"),
        }
        for t in tickets
    ]


# ═════════════════════════════════════════════════════════════════════════════
# ConnectWise Automate RMM Tools
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def mcp_find_device(
    user_name: str,
    tenant_id: str,
    user_email: str = "",
) -> dict:
    """
    Locate a user's managed device in ConnectWise Automate.

    Args:
        user_name:  Username or display name (e.g. john.smith).
        tenant_id:  Tenant ID to scope the device query to the correct
                    ConnectWise Automate instance (e.g. "mock_tenant_a").
        user_email: Optional email — username is derived from it if provided.

    Returns:
        dict with device_id, device_name, os, last_user, customer_id.
    """
    tenant_ctx = _resolve_tenant(tenant_id)
    username   = user_email.split("@")[0] if user_email and "@" in user_email else user_name

    device = find_device_by_user(username=username, tenant_ctx=tenant_ctx)

    return {
        "device_id":   device.get("deviceId"),
        "device_name": device.get("deviceName"),
        "os":          device.get("osName"),
        "last_user":   device.get("lastLoggedOnUserName") or device.get("loggedOnUserName"),
        "customer_id": device.get("customerId"),
    }


@mcp.tool()
def mcp_run_diagnostics(
    user_name: str,
    tenant_id: str,
    user_email: str = "",
) -> dict:
    """
    Run memory, CPU, and disk utilisation scripts on the user's machine
    via ConnectWise Automate and return parsed results.

    Use this when a user reports slowness, high CPU, or low disk space.

    Args:
        user_name:  Username or display name.
        tenant_id:  Tenant ID to scope to the correct ConnectWise Automate instance.
        user_email: Optional email address of the user.

    Returns:
        dict with device info, memory %, CPU %, and storage breakdown.
    """
    tenant_ctx = _resolve_tenant(tenant_id)
    return run_diagnostics(
        user_name=user_name,
        user_email=user_email,
        tenant_ctx=tenant_ctx,
    )


@mcp.tool()
def mcp_reset_outlook(
    user_name: str,
    tenant_id: str,
    user_email: str = "",
) -> dict:
    """
    Run the Outlook reset script on the user's machine via ConnectWise Automate.

    Closes Outlook, clears the profile cache and OST files, then relaunches.
    Use this when a user reports Outlook not syncing, crashing, or calendar issues.

    Args:
        user_name:  Username or display name.
        tenant_id:  Tenant ID to scope to the correct ConnectWise Automate instance.
        user_email: Optional email address of the user.

    Returns:
        dict with message and device name confirming the reset was triggered.
    """
    tenant_ctx = _resolve_tenant(tenant_id)
    return reset_outlook(
        user_name=user_name,
        user_email=user_email,
        tenant_ctx=tenant_ctx,
    )


@mcp.tool()
def mcp_change_timezone(
    user_name:        str,
    user_email:       str,
    tenant_id:        str,
    iana_timezone:    str,
    windows_timezone: str = "",
) -> dict:
    """
    Remotely change the Windows system timezone on the user's device
    via ConnectWise Automate RMM.

    This changes the actual device clock — not just Outlook or Teams calendar.
    The change takes effect immediately with no restart required.

    Args:
        user_name:        Display name of the user (e.g. John Smith).
        user_email:       Email address used to find the user's device.
        tenant_id:        Tenant ID to scope to the correct ConnectWise Automate instance.
        iana_timezone:    IANA timezone name e.g. Asia/Tokyo, America/New_York.
        windows_timezone: Windows timezone name. Resolved automatically if omitted.

    Returns:
        dict with success, device name, timezone applied, and confirmation message.
    """
    resolved_windows_tz = windows_timezone or IANA_TO_WINDOWS.get(iana_timezone, "")

    if not resolved_windows_tz:
        return {
            "success": False,
            "error": (
                f"No Windows timezone mapping found for '{iana_timezone}'. "
                "Provide the windows_timezone parameter explicitly."
            ),
        }

    tenant_ctx = _resolve_tenant(tenant_id)
    return change_timezone(
        user_name=user_name,
        user_email=user_email,
        timezone_iana=iana_timezone,
        windows_timezone=resolved_windows_tz,
        tenant_ctx=tenant_ctx,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Printer Tools
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def mcp_restart_printer(user_email: str, tenant_id: str) -> dict:
    """
    Restart the Windows print spooler service on the user's device
    via ConnectWise Automate.

    Use this when a user can't print, has a stuck queue, or the spooler
    service has stopped.

    Args:
        user_email: Email address used to locate the user's device.
        tenant_id:  Tenant ID to scope to the correct ConnectWise Automate instance.

    Returns:
        dict with success, output, hostname, and mock flag.
    """
    tenant_ctx = _resolve_tenant(tenant_id)
    return restart_spooler(user_email, tenant_ctx)


@mcp.tool()
def mcp_check_printer_status(user_email: str, tenant_id: str) -> dict:
    """
    Check the print spooler service state and list printer status on the
    user's device via ConnectWise Automate.

    Args:
        user_email: Email address used to locate the user's device.
        tenant_id:  Tenant ID to scope to the correct ConnectWise Automate instance.

    Returns:
        dict with success, output, and mock flag.
    """
    tenant_ctx = _resolve_tenant(tenant_id)
    return check_printer_status(user_email, tenant_ctx)


@mcp.tool()
def mcp_clear_print_queue(user_email: str, tenant_id: str) -> dict:
    """
    Clear all stuck or pending print jobs from the queue on the user's
    device via ConnectWise Automate.

    Args:
        user_email: Email address used to locate the user's device.
        tenant_id:  Tenant ID to scope to the correct ConnectWise Automate instance.

    Returns:
        dict with success, output, and mock flag.
    """
    tenant_ctx = _resolve_tenant(tenant_id)
    return clear_queue(user_email, tenant_ctx)


@mcp.tool()
def mcp_list_printers(user_email: str, tenant_id: str) -> dict:
    """
    List all printers installed on the user's device via ConnectWise Automate.

    Args:
        user_email: Email address used to locate the user's device.
        tenant_id:  Tenant ID to scope to the correct ConnectWise Automate instance.

    Returns:
        dict with success, printers list, output, and mock flag.
    """
    tenant_ctx = _resolve_tenant(tenant_id)
    return list_printers(user_email, tenant_ctx)


# ═════════════════════════════════════════════════════════════════════════════
# OpenAI tool definitions + dispatcher  (used by llm_service and orchestrator)
# ═════════════════════════════════════════════════════════════════════════════

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_ticket",
            "description": "Create a new IT support ticket in ConnectWise Manage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary":     {"type": "string", "description": "One-line summary of the issue."},
                    "description": {"type": "string", "description": "Detailed description of the issue."},
                    "priority":    {"type": "string", "enum": ["High", "Medium", "Low", "urgent"],
                                   "description": "Ticket priority."},
                },
                "required": ["summary", "priority"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_note",
            "description": (
                "Add a note or update to an existing ConnectWise ticket. "
                "Use this when the user wants to follow up on a ticket, "
                "provide more information, or update the ticket with new details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "Numeric ConnectWise ticket ID."},
                    "note_text": {"type": "string",  "description": "Text content to add as a note."},
                },
                "required": ["ticket_id", "note_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "triage_ticket",
            "description": "Triage an existing ConnectWise ticket to set the correct board and type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "Numeric ConnectWise ticket ID."},
                },
                "required": ["ticket_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_user_device",
            "description": "Find the user's managed device in ConnectWise Automate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name":  {"type": "string", "description": "Display name of the user."},
                    "user_email": {"type": "string", "description": "Email address of the user."},
                },
                "required": ["user_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_outlook_reset",
            "description": "Reset the Outlook profile on the user's device via ConnectWise Automate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name":          {"type": "string", "description": "Display name of the user."},
                    "user_email":         {"type": "string", "description": "Email address of the user."},
                    "machine_identifier": {"type": "string", "description": "Device name or ID (optional)."},
                },
                "required": ["user_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_utilization_scan",
            "description": "Run a CPU, memory, and/or storage diagnostic scan on the user's device via ConnectWise Automate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name":          {"type": "string", "description": "Display name of the user."},
                    "user_email":         {"type": "string", "description": "Email address of the user."},
                    "machine_identifier": {"type": "string", "description": "Device name or ID (optional)."},
                    "scan_type":          {"type": "string", "enum": ["all", "cpu", "memory", "storage"],
                                         "description": "Which scan to run."},
                },
                "required": ["user_name", "scan_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "change_device_timezone",
            "description": (
                "Remotely change the Windows system timezone on the user's device "
                "via ConnectWise Automate RMM."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "iana_timezone":    {"type": "string",
                                        "description": "IANA timezone name e.g. Asia/Tokyo."},
                    "windows_timezone": {"type": "string",
                                        "description": "Windows timezone name e.g. Tokyo Standard Time."},
                    "user_name":        {"type": "string", "description": "Display name of the user."},
                    "user_email":       {"type": "string", "description": "Email address of the user."},
                },
                "required": ["iana_timezone", "user_name", "user_email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "restart_printer",
            "description": (
                "Restart the Windows print spooler service on the user's device "
                "via ConnectWise Automate. Use this when a user can't print, "
                "has a stuck print queue, or reports the spooler has stopped."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name":  {"type": "string", "description": "Display name of the user."},
                    "user_email": {"type": "string", "description": "Email address of the user."},
                },
                "required": ["user_name", "user_email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_printer_status",
            "description": (
                "Check the print spooler service state and list printer status "
                "on the user's device via ConnectWise Automate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name":  {"type": "string", "description": "Display name of the user."},
                    "user_email": {"type": "string", "description": "Email address of the user."},
                },
                "required": ["user_name", "user_email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_print_queue",
            "description": (
                "Clear all stuck or pending print jobs from the queue "
                "on the user's device via ConnectWise Automate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name":  {"type": "string", "description": "Display name of the user."},
                    "user_email": {"type": "string", "description": "Email address of the user."},
                },
                "required": ["user_name", "user_email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_printers",
            "description": (
                "List all printers installed on the user's device "
                "via ConnectWise Automate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name":  {"type": "string", "description": "Display name of the user."},
                    "user_email": {"type": "string", "description": "Email address of the user."},
                },
                "required": ["user_name", "user_email"],
            },
        },
    },
]


def execute_tool(name: str, args: dict) -> str:
    """
    Dispatch an LLM tool call to the appropriate service function.

    tenant_ctx is resolved from args["user_tenant_id"] which the orchestrator
    injects before every tool call. All RMM service calls are scoped to that
    tenant so device queries and script execution never cross client boundaries.
    """
    import json as _json

    user_name  = args.get("user_name", "")
    user_email = args.get("user_email", "")
    tenant_id  = args.get("user_tenant_id", "")

    # Resolve tenant context — falls back to empty dict if tenant_id is missing
    # so CW-only tools (create_ticket, triage_ticket) still work without RMM.
    try:
        tenant_ctx = loader.get(tenant_id) if tenant_id else {}
    except Exception:
        tenant_ctx = {}

    try:
        if name == "create_ticket":
            result = create_ticket(
                {
                    "summary":     args.get("summary", ""),
                    "description": args.get("description", ""),
                    "priority":    args.get("priority", "Medium"),
                    "board":       CONFIG.CW_DEFAULT_BOARD,
                    "user_name":   user_name,
                },
                tenant_ctx,
            )
            return _json.dumps({
                "ticket_id": result.get("id"),
                "summary":   result.get("summary"),
                "status":    (result.get("status") or {}).get("name"),
            })

        if name == "add_note":
            result = add_note(
                ticket_id=int(args.get("ticket_id", 0)),
                note_text=args.get("note_text", ""),
                tenant_ctx=tenant_ctx,
            )
            return _json.dumps({
                "note_id":   result.get("id"),
                "ticket_id": args.get("ticket_id"),
                "added":     True,
            })

        if name == "triage_ticket":
            ticket = get_ticket(int(args.get("ticket_id", 0)), tenant_ctx)
            return _json.dumps({
                "ticket_id": ticket.get("id"),
                "status":    (ticket.get("status") or {}).get("name"),
                "priority":  (ticket.get("priority") or {}).get("name"),
            })

        if name == "lookup_user_device":
            username = user_email.split("@")[0] if user_email and "@" in user_email else user_name
            computer = find_device_by_user(username=username, tenant_ctx=tenant_ctx)
            return _json.dumps({
                "device_id":   computer.get("Id"),
                "device_name": computer.get("ComputerName"),
                "os":          computer.get("OperatingSystem") or computer.get("OS"),
                "last_user":   computer.get("LastLoggedInUser"),
            })

        if name == "run_outlook_reset":
            result = reset_outlook(
                user_name=user_name,
                user_email=user_email,
                tenant_ctx=tenant_ctx,
            )
            return _json.dumps(result)

        if name == "run_utilization_scan":
            result = run_diagnostics(
                user_name=user_name,
                user_email=user_email,
                tenant_ctx=tenant_ctx,
            )
            return _json.dumps(result)

        if name == "change_device_timezone":
            iana_tz = args.get("iana_timezone", "")
            if not IANA_TO_WINDOWS.get(iana_tz) and not args.get("windows_timezone"):
                return _json.dumps({"error": f"No Windows mapping for '{iana_tz}'."})
            result = change_timezone(
                user_name=user_name,
                user_email=user_email,
                timezone_iana=iana_tz,
                tenant_ctx=tenant_ctx,
            )
            return _json.dumps(result)

        if name == "restart_printer":
            result = restart_spooler(user_email, tenant_ctx)
            return _json.dumps(result)

        if name == "check_printer_status":
            result = check_printer_status(user_email, tenant_ctx)
            return _json.dumps(result)

        if name == "clear_print_queue":
            result = clear_queue(user_email, tenant_ctx)
            return _json.dumps(result)

        if name == "list_printers":
            result = list_printers(user_email, tenant_ctx)
            return _json.dumps(result)

        return _json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as exc:
        return _json.dumps({"error": str(exc), "tool": name})
