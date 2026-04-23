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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUTTON_PROMPTS: dict[str, str] = {
    "CREATE_TICKET":   "I need to create a new IT support ticket.",
    "RUN_DIAGNOSTICS": "Please run diagnostics on my PC.",
    "RESET_OUTLOOK":   "I need to reset my Outlook.",
    "CHECK_TICKET":    "I want to check the status of a ticket.",
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
    # Specific intents first to prevent broad CREATE_TICKET keywords ("issue", "not
    # working", "help") from firing before more targeted patterns.

    # Printer intents
    ("RESTART_SPOOLER",        ["restart spooler", "restart print spooler", "fix printer", "printer stuck",
                                 "printer not responding", "reset printer", "printer problem", "can't print",
                                 "cannot print", "print queue stuck", "spooler restart"]),
    ("CLEAR_PRINT_QUEUE",      ["clear print queue", "clear queue", "stuck print job", "delete print jobs",
                                 "remove print jobs", "empty print queue", "cancel print jobs"]),
    ("LIST_PRINTERS",          ["list printers", "show printers", "what printers", "available printers",
                                 "installed printers", "my printers", "which printer"]),
    ("PRINTER_STATUS",         ["printer status", "check printer", "is my printer working", "printer not working",
                                 "printer is not working", "print issue", "printing issue", "spooler status"]),

    # RUN_DIAGNOSTICS before RESET_OUTLOOK: "ost" appears inside "diagnostics"
    ("RUN_DIAGNOSTICS",        ["slow", "diagnose", "diagnostics", "check my pc", "memory",
                                 "cpu", "storage", "disk", "performance"]),
    ("RESET_OUTLOOK",          ["outlook", "email", "calendar", "mail", "ost", "fix outlook"]),
    ("CHECK_TICKET",           ["status", "update", "my ticket", "progress", "ticket number"]),
    # CHANGE_TIMEZONE includes timezone abbreviations and common phrasings
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

def _get_user_email(activity) -> str:
    """
    Extract the user UPN from the Teams activity.
    Falls back to a constructed UPN using the tenant domain.
    """
    from_prop = activity.from_property
    if from_prop:
        name = from_prop.name or ""
        if "@" in name:
            return name.lower()
        username = name.replace(" ", ".").lower()
        return f"{username}@itbd.net"
    return "unknown@itbd.net"


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
# Main router
# ---------------------------------------------------------------------------

async def handle_turn(context: TurnContext, conversation_data: dict) -> None:
    """
    Primary message router. Every inbound Teams activity passes through here.

    Routing priority
    ----------------
    1. LLM path        — when OPENAI_API_KEY is set, delegate to LLM service.
    2. Slot filling    — active multi-turn dialog takes precedence.
    3. Timezone reply  — intercept yes/no for pending timezone ticket.
    4. Intent routing  — keyword-based fallback for all other messages.
    """
    if conversation_data is None:
        conversation_data = {}

    await context.send_activity(Activity(type=ActivityTypes.typing))

    activity   = context.activity
    raw_text   = _strip_html(activity.text or "")
    value      = activity.value if isinstance(activity.value, dict) else {}

    full_name, first_name = _get_display_names(activity)
    user_email            = _get_user_email(activity)

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
            await _confirm_timezone_ticket(context, conversation_data, pending_tz)
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
        await _handle_create_ticket(context, conversation_data, raw_text)
    elif intent == "RUN_DIAGNOSTICS":
        await _handle_diagnostics(context, conversation_data, full_name, user_email)
    elif intent == "RESET_OUTLOOK":
        await _handle_outlook_reset_prompt(context)
    elif intent == "CONFIRM_OUTLOOK_RESET":
        await _handle_outlook_reset_confirm(context, full_name, user_email)
    elif intent == "CHECK_TICKET":
        await _handle_check_ticket(context, conversation_data, value)
    elif intent == "CHANGE_TIMEZONE":
        await _handle_timezone_request(
            context, raw_text, full_name, user_email, conversation_data
        )
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
) -> None:
    """Initiate the multi-turn slot-filling flow for ticket creation."""
    reply = start_slot_filling(conversation_data, raw_text)
    await context.send_activity(reply)


async def _handle_diagnostics(
    context: TurnContext,
    conversation_data: dict,
    full_name: str,
    user_email: str,
) -> None:
    """
    Trigger an N-able N-central diagnostic run against the user's device
    and store results in conversation state for optional ticket creation.
    """
    await context.send_activity(
        "Fetching your device details and running diagnostics. "
        "Checking memory, CPU, and storage — this typically takes a few seconds."
    )
    try:
        results = await asyncio.to_thread(rmm.run_diagnostics, full_name, user_email)
        await context.send_activity(_format_diagnostics(results))

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


async def _handle_outlook_reset_prompt(context: TurnContext) -> None:
    """Present a confirmation prompt before executing the Outlook reset."""
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
) -> None:
    """Execute the Outlook reset via N-able N-central after user confirmation."""
    await context.send_activity(
        "Initiating Outlook reset on your device via N-able N-central."
    )
    try:
        result = rmm.reset_outlook(full_name, user_email)
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
) -> None:
    """
    Retrieve and display the status of a ConnectWise ticket.
    Prompts the user if no ticket ID is available.
    """
    ticket_id = value.get("ticketId") or conversation_data.get("lastTicketId")

    if not ticket_id:
        await context.send_activity(
            "Please provide your ticket number and I will look it up.\n\n"
            "Example: check ticket 12345"
        )
        return

    try:
        ticket = cw.get_ticket(int(ticket_id))
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
# Timezone handlers
# ---------------------------------------------------------------------------

async def _handle_timezone_request(
    context: TurnContext,
    user_text: str,
    full_name: str,
    user_email: str,
    conversation_data: dict,
) -> None:
    """
    Use OpenAI to identify the IANA timezone from the user's message,
    return OS-specific change commands, and offer to log a ConnectWise ticket.
    Pending ticket state is stored in conversation_data so it survives
    across turns.
    """
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
) -> None:
    """
    Create a ConnectWise ticket from the pending timezone change details
    and clear the pending state from conversation_data.
    """
    try:
        ticket = cw.create_ticket({
            "summary":     pending_tz["summary"],
            "description": pending_tz["description"],
            "priority":    "Low",
            "board":       "Professional Services",
        })
        conversation_data.pop("pending_timezone_ticket", None)
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
    """
    Format N-able diagnostic results into structured plain-text
    suitable for display in Teams.
    """
    device  = results.get("device", {})
    is_mock = device.get("_mock", False)
    lines   = [f"Diagnostic results for {device.get('name', 'Unknown device')}"]

    if is_mock:
        lines.append("Note: Running in demonstration mode. Results are simulated.")

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

    if is_mock:
        lines.append(
            "\nConnect your N-able N-central instance to retrieve live diagnostic data."
        )

    return "\n".join(lines)