"""
mcp_tools/server.py

Exposes the Teams Bot's ConnectWise and N-able N-central capabilities
as MCP tools. Any MCP-compatible AI client (Claude Desktop, etc.) can
discover and invoke these tools through the /mcp SSE endpoint.

Tool categories
───────────────
  ConnectWise  →  mcp_create_ticket, mcp_add_note,
                  mcp_get_ticket,    mcp_get_tickets_by_company
  N-able RMM   →  mcp_find_device,   mcp_run_diagnostics,
                  mcp_reset_outlook
"""

from __future__ import annotations

import os
import sys

# ── Project root on path so sibling packages resolve correctly ────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP

from config.config import CONFIG
from services.connectwise_service import (
    add_note,
    create_ticket,
    find_company_by_name,
    get_ticket,
    get_tickets_by_company,
)
from services.rmm_service import (
    find_device_by_user,
    reset_outlook,
    run_diagnostics,
)
from dialogs.slot_filling import (
    is_active,
    start_slot_filling,
    handle_slot_turn,
)

# ── MCP server instance ───────────────────────────────────────────────────────
mcp = FastMCP("TeamsBotMCP")

# ── In-memory slot-filling session (persists for the lifetime of this process) ─
_sf_session: dict = {}


# ═════════════════════════════════════════════════════════════════════════════
# ConnectWise Tools
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def mcp_create_ticket(
    summary: str,
    priority: str,
    user_name: str = "",
    board: str = "",
) -> dict:
    """
    Create a new service ticket in ConnectWise Manage.

    Args:
        summary:   Short description of the issue (one line).
        priority:  Severity level — High | Medium | Low | urgent
        user_name: Display name of the user raising the ticket.
        board:     Target ConnectWise board. Falls back to CW_DEFAULT_BOARD
                   from .env when omitted.

    Returns:
        dict with ticket_id, summary, status, priority, board.
    """
    resolved_board = board or CONFIG.CW_DEFAULT_BOARD

    result = create_ticket(
        summary=summary,
        priority=priority,
        board=resolved_board,
        user_name=user_name,
    )

    return {
        "ticket_id": result.get("id"),
        "summary":   result.get("summary"),
        "status":    result.get("status",   {}).get("name"),
        "priority":  result.get("priority", {}).get("name"),
        "board":     result.get("board",    {}).get("name"),
    }


@mcp.tool()
def mcp_add_note(ticket_id: int, note_text: str) -> dict:
    """
    Append a note to an existing ConnectWise ticket.

    Args:
        ticket_id: Numeric ConnectWise ticket ID.
        note_text: Text content to add as a note.

    Returns:
        dict with note_id, ticket_id, and added confirmation.
    """
    result = add_note(ticket_id=ticket_id, note_text=note_text)

    return {
        "note_id":   result.get("id"),
        "ticket_id": ticket_id,
        "added":     True,
    }


@mcp.tool()
def mcp_get_ticket(ticket_id: int) -> dict:
    """
    Retrieve the current details and status of a ConnectWise ticket.

    Args:
        ticket_id: Numeric ConnectWise ticket ID.

    Returns:
        dict with ticket_id, summary, status, priority, board, owner.
    """
    result = get_ticket(ticket_id=ticket_id)

    return {
        "ticket_id": result.get("id"),
        "summary":   result.get("summary"),
        "status":    result.get("status",   {}).get("name"),
        "priority":  result.get("priority", {}).get("name"),
        "board":     result.get("board",    {}).get("name"),
        "owner":     result.get("owner",    {}).get("name"),
    }


@mcp.tool()
def mcp_find_company(name: str) -> list[dict]:
    """
    Search for a company in ConnectWise by name (partial match).

    Use this FIRST when the user mentions a company name but you don't
    have its numeric ID. Returns matching companies with their IDs so
    you can then call mcp_get_tickets_by_company.

    Args:
        name: Full or partial company name (e.g. "IT By Design", "ITBD").

    Returns:
        List of dicts with company_id, name, status.
    """
    results = find_company_by_name(name)
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
    status: str = "New (not responded)",
) -> list[dict]:
    """
    List tickets for a specific company in ConnectWise.

    If you only have a company name (not ID), call mcp_find_company first.
    Common status values: "New (not responded)", "In Progress", "Waiting Customer", "Closed".
    If the requested status returns no results, variants are tried automatically.

    Args:
        company_id: Numeric ConnectWise company ID.
        status:     Ticket status to filter by. Defaults to 'New (not responded)'.

    Returns:
        List of dicts with ticket_id, summary, status, priority.
    """
    tickets = get_tickets_by_company(company_id=company_id, status=status)

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
# N-able N-central RMM Tools
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def mcp_find_device(user_name: str, user_email: str = "") -> dict:
    """
    Locate a user's managed device in N-able N-central.

    Args:
        user_name:  Username or display name (e.g. john.smith).
        user_email: Email address used to resolve the correct N-central
                    customer from NABLE_CUSTOMER_MAP in .env.

    Returns:
        dict with device_id, device_name, os, last_user, customer_id.
    """
    device = find_device_by_user(username=user_name, user_email=user_email)

    return {
        "device_id":   device.get("deviceId"),
        "device_name": device.get("longName"),
        "os":          device.get("supportedOsLabel") or device.get("supportedOs"),
        "last_user":   device.get("lastLoggedInUser"),
        "customer_id": device.get("customerId"),
    }


@mcp.tool()
def mcp_run_diagnostics(user_name: str, user_email: str = "") -> dict:
    """
    Run memory, CPU, and disk utilisation scripts on the user's machine
    via N-able N-central and return parsed results.

    Use this when a user reports slowness, high CPU, or low disk space.

    Args:
        user_name:  Username or display name.
        user_email: Email address used to resolve the correct N-central customer.

    Returns:
        dict with device info, memory %, CPU %, and storage breakdown.
    """
    return run_diagnostics(user_name=user_name, user_email=user_email)


@mcp.tool()
def mcp_reset_outlook(user_name: str, user_email: str = "") -> dict:
    """
    Execute the Outlook reset/refresh automation script on the user's
    machine through N-able N-central.

    Use this when the user reports Outlook freezing, crashing, or failing
    to sync email.

    Args:
        user_name:  Username or display name.
        user_email: Email address used to resolve the correct N-central customer.

    Returns:
        dict with device name and script execution status/message.
    """
    return reset_outlook(user_name=user_name, user_email=user_email)