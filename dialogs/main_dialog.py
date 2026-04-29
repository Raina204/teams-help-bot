import asyncio
import json
import os
import re

import aiohttp
from botbuilder.core import CardFactory, MessageFactory, TurnContext
from botbuilder.schema import Activity, ActivityTypes, CardAction, SuggestedActions

from cards.welcome_card import get_welcome_card
from dialogs.slot_filling import handle_slot_turn, is_active, start_slot_filling
from services import connectwise_service as cw
from services import llm_service
from services import rmm_service as rmm
from services.timezone_service import get_timezone_command
from services import printer_service as printer
from services import timezone_service as tz
from config import check_allowed, log_action, log_denied, ActionNotAllowedError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUTTON_PROMPTS: dict[str, str] = {
    # ── Ticketing ────────────────────────────────────────────
    "CREATE_TICKET":      "I need to create a new IT support ticket.",
    "CHECK_TICKET":       "I want to check the status of a ticket.",

    # ── PC Diagnostics & Fixes ───────────────────────────────
    "RUN_DIAGNOSTICS":    "Please run diagnostics on my PC.",
    "RESET_OUTLOOK":      "I need to reset my Outlook.",

    # ── Timezone ─────────────────────────────────────────────
    "CHANGE_TIMEZONE":    "I need to change the timezone on my device.",

    # ── Printer & Spooler ────────────────────────────────────
    "PRINTER_STATUS":     "Please check my printer status.",
    "RESTART_SPOOLER":    "My printer is stuck, please restart the print spooler.",
    "CLEAR_PRINT_QUEUE":  "Please clear my print queue.",
    "LIST_PRINTERS":      "Show me all the printers installed on my device.",
}


_TIMEZONE_CONFIRM_YES = {
    "yes", "yeah", "yep", "sure", "ok", "okay",
    "yes please", "create ticket", "log ticket",
    "log a ticket", "yes log a ticket",
}

_TIMEZONE_CONFIRM_NO = {
    "no", "nope", "no thanks", "cancel",
    "never mind", "nah", "don't", "dont",
}


# ---------------------------------------------------------------------------
# Intent patterns
# ---------------------------------------------------------------------------

INTENT_PATTERNS = [
    # Specific intents first to prevent broad CREATE_TICKET keywords ("issue",
    # "not working", "help") from firing before more targeted patterns.

    # Printer intents
    ("RESTART_SPOOLER",        ["restart print spooler", "printer stuck", "cant print",
                     "cannot print", "restart spooler", "fix printer",
                     "printer not responding", "reset printer", "printer problem",
                     "can't print", "I can't print anything"]),
    ("CLEAR_PRINT_QUEUE",      ["clear print queue", "clear queue", "stuck print job",
                                 "delete print jobs", "remove print jobs", "empty print queue",
                                 "cancel print jobs"]),
    ("LIST_PRINTERS",          ["list printers", "show printers", "what printers",
                                 "available printers", "installed printers", "my printers",
                                 "which printer"]),
    ("PRINTER_STATUS",         ["printer status", "check printer", "is my printer working",
                                 "printer not working", "printer is not working", "print issue",
                                 "printing issue", "spooler status"]),

    # RUN_DIAGNOSTICS before RESET_OUTLOOK: "ost" appears inside "diagnostics"
    ("RUN_DIAGNOSTICS",        ["slow", "diagnose", "diagnostics", "check my pc", "memory",
                                 "cpu", "storage", "disk", "performance"]),
    ("RESET_OUTLOOK",          ["outlook", "email", "calendar", "mail", "ost", "fix outlook"]),
    ("CHECK_TICKET",           ["status", "update", "my ticket", "progress", "ticket number"]),
    ("CHANGE_TIMEZONE",        ["timezone", "time zone", "change time", "set time", "clock",
                                 "wrong time", "pst", "est", "cst", "mst", "gmt"]),
    ("CONFIRM_OUTLOOK_RESET",  ["confirm_outlook_reset", "yes reset", "yes, reset"]),
    # MAIN_MENU before CREATE_TICKET so "help" routes here, not to a ticket
    ("MAIN_MENU",              ["menu", "start", "home", "hello", "hi", "hey", "help"]),
    ("CREATE_TICKET",          ["ticket", "issue", "problem", "broken", "not working", "support"]),
]


# ---------------------------------------------------------------------------
# Triage rules
# ---------------------------------------------------------------------------

TRIAGE_RULES: list[tuple[list[str], str, str, str]] = [
    (["outlook", "email", "calendar", "ost", "mail"],      "Professional Services", "Email Issue",          "Medium"),
    (["slow", "freeze", "crash", "blue screen", "bsod"],   "Professional Services", "Performance",          "High"),
    (["printer", "print", "scan", "scanner"],              "Professional Services", "Hardware",             "Medium"),
    (["vpn", "remote", "rdp", "remote desktop"],           "Professional Services", "Network/Connectivity", "High"),
    (["password", "locked out", "login", "access denied"], "Professional Services", "Account Access",       "High"),
    (["wifi", "internet", "network", "no connection"],     "Professional Services", "Network/Connectivity", "High"),
    (["install", "software", "application", "app"],        "Professional Services", "Software Request",     "Low"),
]


# ---------------------------------------------------------------------------
# Intent and triage helpers
# ---------------------------------------------------------------------------

def detect_intent(text: str) -> str:
    """
    Match free-text input against known keyword patterns and return
    the first matching intent label, or 'UNKNOWN' if none match.
    Uses word-boundary matching for short greetings to prevent
    substring collisions e.g. 'hi' matching inside 'I have an issue'.
    """
    lower = (text or "").lower().strip()
    _WHOLE_WORD_PATTERNS = {"hi", "hey", "hello", "help", "menu", "start", "home"}

    for intent, patterns in INTENT_PATTERNS:
        for pattern in patterns:
            if pattern in _WHOLE_WORD_PATTERNS:
                if re.search(rf"\b{re.escape(pattern)}\b", lower):
                    return intent
            else:
                if pattern in lower:
                    return intent

    return "UNKNOWN"


def triage_ticket(summary: str) -> tuple[str, str, str]:
    """
    Derive (board, ticket_type, priority) from the issue summary.
    Returns a general medium-priority request when no rule matches.
    """
    lower = (summary or "").lower()
    for keywords, board, ticket_type, priority in TRIAGE_RULES:
        if any(keyword in lower for keyword in keywords):
            return board, ticket_type, priority
    return "Professional Services", "General Request", "Medium"


# ---------------------------------------------------------------------------
# User identity helpers
# ---------------------------------------------------------------------------

def _get_user_email(activity, tenant_ctx: dict | None = None) -> str:
    """
    Extract the user UPN from the Teams activity.
    Falls back to a constructed UPN using the tenant domain.
    """
    domain    = (tenant_ctx or {}).get("domain", "itbd.net")
    from_prop = activity.from_property
    if from_prop:
        name = from_prop.name or ""
        if "@" in name:
            return name.lower()
        username = name.replace(" ", ".").lower()
        return f"{username}@{domain}"
    return f"unknown@{domain}"


def _get_display_names(activity) -> tuple[str, str]:
    """Return (full_name, first_name) from the activity sender."""
    from_prop  = activity.from_property
    full_name  = from_prop.name if from_prop else ""
    first_name = full_name.split()[0] if full_name else ""
    return full_name, first_name


def _strip_html(text: str) -> str:
    """Remove HTML tags Teams injects when rich text input is enabled."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


# ---------------------------------------------------------------------------
# RBAC guard helper
# ---------------------------------------------------------------------------

async def _guard(
    action: str,
    tenant_ctx: dict,
    user: str,
    context: TurnContext,
) -> bool:
    """
    Check whether this tenant is allowed to perform `action`.
    Sends a user-facing message and logs the denial if blocked.

    Returns True if allowed, False if blocked.

    Usage:
        if not await _guard("RESTART_PRINTER", tenant_ctx, user_email, context):
            return
    """
    try:
        check_allowed(action, tenant_ctx)
        return True
    except ActionNotAllowedError as exc:
        log_denied(tenant_ctx, user=user, action=action)
        await context.send_activity(
            f"Sorry, **{action.replace('_', ' ').title()}** isn't available "
            f"for your organisation. Contact your IT administrator if you "
            f"think this is wrong."
        )
        return False


# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------

async def handle_turn(
    context: TurnContext,
    conversation_data: dict,
    tenant_ctx: dict = None,
) -> None:
    """
    Primary message router. Every inbound Teams activity passes through here.

    Args:
        context:           Bot Framework TurnContext.
        conversation_data: Per-conversation state dict (from ConversationState).
        tenant_ctx:        Resolved tenant config dict. Contains scoped
                           credentials, site IDs, and allowed_actions for
                           this specific client. Never None — guaranteed by
                           HelpBot.on_turn() before this is called.

    Routing priority
    ----------------
    1. LLM path        — when OPENAI_API_KEY is set, delegate to LLM service.
    2. Slot filling    — active multi-turn dialog takes precedence.
    3. Timezone reply  — intercept yes/no for pending timezone ticket.
    4. Intent routing  — keyword-based fallback for all other messages.
    """

    if tenant_ctx is None:
      tenant_ctx = {
        "tenant_id":  "default",
        "user_email": (context.activity.from_property.email or ""),
        "allowed_actions": [
            "CHANGE_TIMEZONE",
            "RUN_DIAGNOSTICS",
            "RESET_OUTLOOK",
            "RESTART_SPOOLER",
            "CHECK_PRINTER_STATUS",
            "CLEAR_PRINT_QUEUE",
            "LIST_PRINTERS",
            "CREATE_TICKET",
        ],
    }

    if conversation_data is None:
        conversation_data = {}

    await context.send_activity(Activity(type=ActivityTypes.typing))

    activity   = context.activity
    raw_text   = _strip_html(activity.text or "")
    value      = activity.value if isinstance(activity.value, dict) else {}

    full_name, first_name = _get_display_names(activity)
    user_email            = _get_user_email(activity, tenant_ctx)

    button_intent     = value.get("intent", "")
    effective_message = (
        _BUTTON_PROMPTS.get(button_intent, raw_text) if button_intent else raw_text
    ) or "Hello"

    # ------------------------------------------------------------------
    # 1. LLM path
    # ------------------------------------------------------------------
    if os.environ.get("OPENAI_API_KEY"):
        history = conversation_data.get("llm_messages", [])

        reply = llm_service.process_message(
            user_message         = effective_message,
            conversation_history = history,
            user_name            = full_name,
            user_email           = user_email,
            tenant_id            = tenant_ctx.get("tenant_id", ""),
        )

        history.append({"role": "user",      "content": effective_message})
        history.append({"role": "assistant", "content": reply})
        conversation_data["llm_messages"] = history[-20:]

        await context.send_activity(reply)
        return

    # ------------------------------------------------------------------
    # 2. Slot filling
    # ------------------------------------------------------------------
    if is_active(conversation_data):
        reply = await handle_slot_turn(conversation_data, raw_text)
        await context.send_activity(reply)
        return

    # ------------------------------------------------------------------
    # 3. Pending timezone ticket confirmation
    # ------------------------------------------------------------------
    pending_tz = conversation_data.get("pending_timezone_ticket")
    normalised = raw_text.lower().strip()

    if pending_tz:
        if normalised in _TIMEZONE_CONFIRM_YES:
            await _confirm_timezone_ticket(
                context, conversation_data, pending_tz, tenant_ctx, user_email
            )
            return

        if normalised in _TIMEZONE_CONFIRM_NO:
            conversation_data.pop("pending_timezone_ticket", None)
            await context.send_activity(
                "Understood. Let me know if there is anything else I can help with."
            )
            return

        conversation_data.pop("pending_timezone_ticket", None)

    # ------------------------------------------------------------------
    # 4. Intent routing
    # ------------------------------------------------------------------
    intent = button_intent or detect_intent(raw_text)

    if intent in ("MAIN_MENU", "UNKNOWN"):
        await _handle_main_menu(context, first_name)

    elif intent == "CREATE_TICKET":
        await _handle_create_ticket(
            context, conversation_data, raw_text, tenant_ctx, user_email
        )

    elif intent == "RUN_DIAGNOSTICS":
        await _handle_diagnostics(
            context, conversation_data, full_name, user_email, tenant_ctx
        )

    elif intent == "RESET_OUTLOOK":
        await _handle_outlook_reset_prompt(context, tenant_ctx, user_email)

    elif intent == "CONFIRM_OUTLOOK_RESET":
        await _handle_outlook_reset_confirm(
            context, full_name, user_email, tenant_ctx
        )

    elif intent == "CHECK_TICKET":
        await _handle_check_ticket(
            context, conversation_data, value, tenant_ctx, user_email
        )

    elif intent == "CHANGE_TIMEZONE":
        await _handle_timezone_request(
            context, raw_text, full_name, user_email, conversation_data, tenant_ctx
        )

    # ── Printer intents ───────────────────────────────────────────────────
    elif intent == "RESTART_SPOOLER":
        await _handle_restart_printer(context, user_email, tenant_ctx)

    elif intent == "CLEAR_PRINT_QUEUE":
        await _handle_clear_print_queue(context, user_email, tenant_ctx)

    elif intent == "LIST_PRINTERS":
        await _handle_list_printers(context, user_email, tenant_ctx)

    elif intent == "PRINTER_STATUS":
        await _handle_printer_status(context, user_email, tenant_ctx)

    else:
        await _handle_main_menu(context, first_name)


# ---------------------------------------------------------------------------
# Intent handlers
# ---------------------------------------------------------------------------

async def _handle_main_menu(context: TurnContext, first_name: str) -> None:
    """Render the welcome Adaptive Card as the main menu."""
    card = CardFactory.adaptive_card(get_welcome_card(first_name))
    await context.send_activity(MessageFactory.attachment(card))


async def _handle_create_ticket(
    context: TurnContext,
    conversation_data: dict,
    raw_text: str,
    tenant_ctx: dict,
    user_email: str,
) -> None:
    """
    Initiate the multi-turn slot-filling flow for ticket creation.
    Scoped to this tenant's ConnectWise company via tenant_ctx.
    """
    if not await _guard("CREATE_TICKET", tenant_ctx, user_email, context):
        return

    reply = start_slot_filling(conversation_data, raw_text)
    await context.send_activity(reply)


async def _handle_diagnostics(
    context: TurnContext,
    conversation_data: dict,
    full_name: str,
    user_email: str,
    tenant_ctx: dict,
) -> None:
    """
    Trigger a ConnectWise Automate diagnostic run against the user's device.
    Scoped to this tenant's CWA client via tenant_ctx.
    """
    if not await _guard("RUN_DIAGNOSTICS", tenant_ctx, user_email, context):
        return

    await context.send_activity(
        "Fetching your device details and running diagnostics. "
        "Checking memory, CPU, and storage — this typically takes a few seconds."
    )
    try:
        results = await asyncio.to_thread(
            rmm.run_diagnostics, full_name, user_email, tenant_ctx
        )
        await context.send_activity(_format_diagnostics(results))

        log_action(tenant_ctx, user_email, "RUN_DIAGNOSTICS", results)

        follow_up = MessageFactory.text(
            "Would you like me to log a support ticket with these diagnostic results?"
        )
        follow_up.suggested_actions = SuggestedActions(actions=[
            CardAction(type="imBack", title="Yes, log a ticket",
                       value="Yes log a ticket with diagnostic results"),
            CardAction(type="imBack", title="No, thank you", value="No thanks"),
        ])
        await context.send_activity(follow_up)
        conversation_data["pendingDiagnostics"] = results

    except Exception as exc:
        await context.send_activity(
            f"Diagnostics could not be completed: {exc}\n\n"
            "Please ensure your device is online and enrolled in N-able N-central. "
            "Contact your IT administrator if the issue persists."
        )


async def _handle_outlook_reset_prompt(
    context: TurnContext,
    tenant_ctx: dict,
    user_email: str,
) -> None:
    """
    Check RBAC first, then present a confirmation prompt before
    executing the Outlook reset.
    """
    if not await _guard("RESET_OUTLOOK", tenant_ctx, user_email, context):
        return

    message = MessageFactory.text(
        "The Outlook reset will perform the following actions:\n\n"
        "- Close Outlook completely\n"
        "- Clear the Outlook profile cache\n"
        "- Remove cached OST files\n"
        "- Relaunch Outlook automatically\n\n"
        "You may be prompted to re-enter your password once the reset completes. "
        "Do you want to proceed?"
    )
    message.suggested_actions = SuggestedActions(actions=[
        CardAction(type="imBack", title="Yes, reset Outlook",
                   value="CONFIRM_OUTLOOK_RESET"),
        CardAction(type="imBack", title="Cancel", value="menu"),
    ])
    await context.send_activity(message)


async def _handle_outlook_reset_confirm(
    context: TurnContext,
    full_name: str,
    user_email: str,
    tenant_ctx: dict,
) -> None:
    """
    Execute the Outlook reset via N-able N-central after user confirmation.
    Scoped to this tenant's N-central credentials via tenant_ctx.
    """
    await context.send_activity(
        "Initiating Outlook reset on your device via N-able N-central."
    )
    try:
        result = rmm.reset_outlook(full_name, user_email, tenant_ctx)

        log_action(tenant_ctx, user_email, "RESET_OUTLOOK", result)

        await context.send_activity(
            f"{result['message']}\n\n"
            "If Outlook does not relaunch automatically, please open it manually."
        )
    except Exception as exc:
        await context.send_activity(
            f"The Outlook reset could not be completed: {exc}\n\n"
            "Please ensure your device is online and enrolled in N-able N-central."
        )


async def _handle_check_ticket(
    context: TurnContext,
    conversation_data: dict,
    value: dict,
    tenant_ctx: dict,
    user_email: str,
) -> None:
    """
    Retrieve and display a ConnectWise ticket.
    Scoped to this tenant's CW company via tenant_ctx.
    """
    if not await _guard("CHECK_STATUS", tenant_ctx, user_email, context):
        return

    ticket_id = value.get("ticketId") or conversation_data.get("lastTicketId")

    if not ticket_id:
        await context.send_activity(
            "Please provide your ticket number and I will look it up.\n\n"
            "Example: check ticket 12345"
        )
        return

    try:
        # tenant_ctx scopes the CW call to this tenant's cw_company_id
        ticket = cw.get_ticket(int(ticket_id), tenant_ctx)

        log_action(tenant_ctx, user_email, "CHECK_STATUS", {"success": True, "ticket_id": ticket_id})

        await context.send_activity(
            f"Ticket #{ticket['id']}\n\n"
            f"Summary      : {ticket.get('summary', 'N/A')}\n"
            f"Status       : {ticket.get('status', {}).get('name', 'Unknown')}\n"
            f"Priority     : {ticket.get('priority', {}).get('name', 'Unknown')}\n"
            f"Last updated : {ticket.get('_info', {}).get('lastUpdated', 'Unknown')}"
        )
    except Exception as exc:
        await context.send_activity(
            f"Could not retrieve ticket {ticket_id}: {exc}"
        )


# ---------------------------------------------------------------------------
# Printer handlers (all scoped to tenant_ctx)
# ---------------------------------------------------------------------------

async def _handle_restart_printer(
    context: TurnContext,
    user_email: str,
    tenant_ctx: dict,
) -> None:
    """Restart the print spooler. Scoped to this tenant's printer sites."""
    if not await _guard("RESTART_PRINTER", tenant_ctx, user_email, context):
        return

    from services import printer_service as ps

    await context.send_activity(
        "Restarting the print spooler on your device. This will take a few seconds."
    )
    try:
        result = await asyncio.to_thread(
            ps.restart_spooler, user_email, tenant_ctx
        )
        log_action(tenant_ctx, user_email, "RESTART_PRINTER", result)
        await context.send_activity(
            result.get("output", "Print spooler restarted successfully.")
        )
    except Exception as exc:
        await context.send_activity(
            f"Could not restart the print spooler: {exc}\n\n"
            "Please contact your IT administrator if the issue persists."
        )


async def _handle_clear_print_queue(
    context: TurnContext,
    user_email: str,
    tenant_ctx: dict,
) -> None:
    """Clear stuck print jobs. Scoped to this tenant's printer sites."""
    if not await _guard("CLEAR_PRINT_QUEUE", tenant_ctx, user_email, context):
        return

    from services import printer_service as ps

    await context.send_activity("Clearing the print queue on your device.")
    try:
        result = await asyncio.to_thread(
            ps.clear_queue, user_email, tenant_ctx
        )
        log_action(tenant_ctx, user_email, "CLEAR_PRINT_QUEUE", result)
        await context.send_activity(
            result.get("output", "Print queue cleared successfully.")
        )
    except Exception as exc:
        await context.send_activity(
            f"Could not clear the print queue: {exc}"
        )


async def _handle_list_printers(
    context: TurnContext,
    user_email: str,
    tenant_ctx: dict,
) -> None:
    """List available printers. Scoped to this tenant's printer_sites."""
    if not await _guard("LIST_PRINTERS", tenant_ctx, user_email, context):
        return

    from services import printer_service as ps

    try:
        result = await asyncio.to_thread(
            ps.list_printers, user_email, tenant_ctx
        )
        log_action(tenant_ctx, user_email, "LIST_PRINTERS", result)
        printers = result.get("printers", [])
        if printers:
            printer_list = "\n".join(f"  - {p}" for p in printers)
            await context.send_activity(
                f"Printers available at your site:\n\n{printer_list}"
            )
        else:
            await context.send_activity(
                "No printers found for your site. "
                "Contact your IT administrator to get printers configured."
            )
    except Exception as exc:
        await context.send_activity(
            f"Could not retrieve printer list: {exc}"
        )


async def _handle_printer_status(
    context: TurnContext,
    user_email: str,
    tenant_ctx: dict,
) -> None:
    """Check printer status. Scoped to this tenant's printer_sites."""
    if not await _guard("CHECK_PRINTER_STATUS", tenant_ctx, user_email, context):
        return

    from services import printer_service as ps

    try:
        result = await asyncio.to_thread(
            ps.check_printer_status, user_email, tenant_ctx
        )
        log_action(tenant_ctx, user_email, "CHECK_PRINTER_STATUS", result)
        await context.send_activity(
            result.get("output", "Printer status retrieved successfully.")
        )
    except Exception as exc:
        await context.send_activity(
            f"Could not retrieve printer status: {exc}"
        )


# ---------------------------------------------------------------------------
# Timezone handlers
# ---------------------------------------------------------------------------

async def _handle_timezone_request(
    context: TurnContext,
    user_text: str,
    full_name: str,
    user_email: str,
    conversation_data: dict,
    tenant_ctx: dict = None,
) -> None:
    """
    Use OpenAI to identify the IANA timezone from the user's message,
    validate it against this tenant's allowed_timezones, return OS-specific
    change commands, and offer to log a ConnectWise ticket.
    """

    if tenant_ctx is None:
        tenant_ctx = {
            "tenant_id":  "default",
            "user_email": (context.activity.from_property.email or ""),
        }
    if not await _guard("CHANGE_TIMEZONE", tenant_ctx, user_email, context):
        return

    system_prompt = (
        "You are a timezone assistant integrated into an IT support bot. "
        "Your sole task is to extract the IANA timezone name from the user's message. "
        "Return ONLY valid JSON — no markdown, no backticks, no additional text.\n\n"
        "When the timezone is identified:\n"
        '{"found": true, "timezone_iana": "America/New_York", '
        '"timezone_display": "Eastern Time (New York)", "utc_offset": "UTC-5 / UTC-4 DST"}\n\n'
        "When the timezone cannot be identified:\n"
        '{"found": false, "message": "A brief, friendly explanation of the issue."}'
    )

    try:
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}",
        }
        payload = {
            "model":       "gpt-4o",
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_text},
            ],
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            ) as resp:
                data = await resp.json()

        raw    = data["choices"][0]["message"]["content"]
        clean  = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)

    except Exception as exc:
        await context.send_activity(
            f"Timezone lookup failed: {exc}\n\n"
            "Please try again or contact your IT administrator."
        )
        return

    if not parsed.get("found"):
        await context.send_activity(
            f"{parsed.get('message', 'Could not identify the requested timezone.')}\n\n"
            "Please try phrasing your request differently. For example:\n"
            "  - Set my timezone to Tokyo\n"
            "  - Change to Eastern time\n"
            "  - Set timezone to UTC"
        )
        return

    iana    = parsed["timezone_iana"]
    display = parsed["timezone_display"]
    offset  = parsed.get("utc_offset", "")

    # ── Tenant timezone policy check ──────────────────────────────────────
    # Some tenants restrict which timezones can be set (e.g. US-only clients).
    allowed_timezones = tenant_ctx.get("allowed_timezones", [])
    if allowed_timezones and iana not in allowed_timezones:
        await context.send_activity(
            f"Sorry, **{display}** ({iana}) isn't in the list of permitted timezones "
            f"for your organisation.\n\n"
            f"Permitted timezones: {', '.join(allowed_timezones)}\n\n"
            f"Contact your IT administrator if you need a different timezone."
        )
        log_denied(tenant_ctx, user=user_email, action="CHANGE_TIMEZONE")
        return

    win_cmd = get_timezone_command(iana, "windows").get("command", "N/A")
    mac_cmd = get_timezone_command(iana, "macos").get("command",   "N/A")
    lin_cmd = get_timezone_command(iana, "linux").get("command",   "N/A")

    response_text = (
        f"Timezone: {display}  |  {offset}\n"
        f"IANA identifier: {iana}\n\n"
        f"Windows  (PowerShell or Command Prompt — run as Administrator)\n"
        f"  {win_cmd}\n\n"
        f"macOS  (Terminal)\n"
        f"  {mac_cmd}\n\n"
        f"Linux  (Terminal)\n"
        f"  {lin_cmd}\n\n"
        f"The change takes effect immediately. No restart is required.\n\n"
        f"Would you like me to log a ConnectWise ticket for this timezone change?"
    )

    message = MessageFactory.text(response_text)
    message.suggested_actions = SuggestedActions(actions=[
        CardAction(type="imBack", title="Yes, log a ticket", value="yes"),
        CardAction(type="imBack", title="No, thank you",     value="no thanks"),
    ])
    await context.send_activity(message)

    conversation_data["pending_timezone_ticket"] = {
        "summary": f"Timezone change request — {display}",
        "description": (
            f"User: {full_name} ({user_email})\n"
            f"Requested timezone: {display} ({iana}, {offset})\n\n"
            f"Windows command : {win_cmd}\n"
            f"macOS command   : {mac_cmd}\n"
            f"Linux command   : {lin_cmd}"
        ),
    }


async def _confirm_timezone_ticket(
    context: TurnContext,
    conversation_data: dict,
    pending_tz: dict,
    tenant_ctx: dict,
    user_email: str,
) -> None:
    """
    Create a ConnectWise ticket from the pending timezone change details.
    Scoped to this tenant's cw_company_id via tenant_ctx.
    """
    try:
        # tenant_ctx carries cw_company_id + cw_api_key_ref so the ticket
        # is created under the correct client company in ConnectWise.
        ticket = cw.create_ticket(
            {
                "summary":     pending_tz["summary"],
                "description": pending_tz["description"],
                "priority":    "Low",
                "board":       "Professional Services",
            },
            tenant_ctx,
        )
        conversation_data.pop("pending_timezone_ticket", None)

        log_action(
            tenant_ctx, user_email, "CREATE_TICKET",
            {"success": True, "ticket_id": ticket.get("id")}
        )

        await context.send_activity(
            f"Ticket #{ticket['id']} has been created for the timezone change request. "
            f"A technician will follow up to confirm the change has been applied."
        )
    except Exception as exc:
        await context.send_activity(
            f"The ticket could not be created: {exc}\n\n"
            "Please try again or contact your IT administrator."
        )


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _format_diagnostics(results: dict) -> str:
    """Format ConnectWise Automate diagnostic results into a structured Teams message."""
    device  = results.get("device", {})
    is_mock = results.get("mock", False)
    lines   = [f"Diagnostic results for **{device.get('name', 'Unknown device')}**"]

    if is_mock:
        lines.append("Note: Running in demonstration mode — results are simulated.")

    lines.append("")

    memory   = results.get("memory", {})
    mem_pct  = memory.get("usedPercent", 0)
    mem_flag = "HIGH" if mem_pct > 85 else "MODERATE" if mem_pct > 60 else "OK"
    lines.append(
        f"Memory   : {mem_pct}% used "
        f"({memory.get('usedGB')} GB / {memory.get('totalGB')} GB)  [{mem_flag}]"
    )

    cpu      = results.get("cpu", {})
    cpu_load = cpu.get("loadPercent", 0)
    cpu_flag = "HIGH" if cpu_load > 85 else "MODERATE" if cpu_load > 60 else "OK"
    lines.append(f"CPU      : {cpu_load}% load  [{cpu_flag}]")

    for drive in results.get("storage", []):
        drive_pct  = drive.get("usedPercent", 0)
        drive_flag = "CRITICAL" if drive_pct > 90 else "LOW" if drive_pct > 75 else "OK"
        lines.append(
            f"Drive {drive.get('name', '?')}  : "
            f"{drive_pct}% used ({drive.get('freeGB')} GB free)  [{drive_flag}]"
        )

    lines.append(f"\nOperating system : {device.get('os', 'Unknown')}")

    return "\n".join(lines)