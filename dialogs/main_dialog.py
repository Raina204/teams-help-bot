from botbuilder.core import TurnContext, CardFactory, MessageFactory
from cards.welcome_card import get_welcome_card
from services import connectwise_service as cw
from services import rmm_service as rmm
from dialogs.slot_filling import is_active, start_slot_filling, handle_slot_turn

# ── Intent keyword patterns ────────────────────────────────────────────────────
INTENT_PATTERNS = [
    ("CREATE_TICKET",          ["ticket", "issue", "problem", "broken", "not working", "support", "help"]),
    ("RUN_DIAGNOSTICS",        ["slow", "diagnose", "check my pc", "memory", "cpu", "storage", "disk", "performance"]),
    ("RESET_OUTLOOK",          ["outlook", "email", "calendar", "mail", "ost", "fix outlook"]),
    ("CHECK_TICKET",           ["status", "update", "my ticket", "progress", "ticket number"]),
    ("CONFIRM_OUTLOOK_RESET",  ["confirm_outlook_reset", "yes reset", "yes, reset"]),
    ("MAIN_MENU",              ["menu", "start", "home", "hello", "hi", "hey", "help"]),
]

# ── Triage rules ───────────────────────────────────────────────────────────────
TRIAGE_RULES = [
    (["outlook", "email", "calendar", "ost", "mail"],      "Professional Services", "Email Issue",            "Medium"),
    (["slow", "freeze", "crash", "blue screen", "bsod"],   "Professional Services", "Performance",            "High"),
    (["printer", "print", "scan", "scanner"],              "Professional Services", "Hardware",               "Medium"),
    (["vpn", "remote", "rdp", "remote desktop"],           "Professional Services", "Network/Connectivity",   "High"),
    (["password", "locked out", "login", "access denied"], "Professional Services", "Account Access",         "High"),
    (["wifi", "internet", "network", "no connection"],     "Professional Services", "Network/Connectivity",   "High"),
    (["install", "software", "application", "app"],        "Professional Services", "Software Request",       "Low"),
]


def detect_intent(text: str) -> str:
    """Scans free-text input and returns the closest matching intent."""
    lower = (text or "").lower()
    for intent, patterns in INTENT_PATTERNS:
        if any(p in lower for p in patterns):
            return intent
    return "UNKNOWN"


def triage_ticket(summary: str) -> tuple:
    """Returns (board, ticket_type, priority) based on issue keywords."""
    lower = (summary or "").lower()
    for keywords, board, ticket_type, priority in TRIAGE_RULES:
        if any(k in lower for k in keywords):
            return board, ticket_type, priority
    return "Professional Services", "General Request", "Medium"


def _get_user_email(activity) -> str:
    """
    Extracts the user's real email from the Teams activity.
    Teams passes the UPN (email) in channelData when available.
    Falls back to constructing from display name if not present.

    NOTE: Replace the fallback with a Microsoft Graph API call
    in production to get the real UPN reliably.
    """
    # Try to get real email from Teams channel data
    channel_data = getattr(activity, "channel_data", {}) or {}
    if isinstance(channel_data, dict):
        tenant_id = channel_data.get("tenant", {}).get("id", "")

    # Try from_property aad_object_id (available when bot has Graph permissions)
    from_prop = activity.from_property
    if from_prop:
        # If the name looks like an email address use it directly
        name = from_prop.name or ""
        if "@" in name:
            return name.lower()

        # Build best-guess email from display name
        # e.g. "Aarav Raina" → "aarav.raina@itbd.net"
        # This maps to the correct N-central customer via NABLE_CUSTOMER_MAP
        username = name.replace(" ", ".").lower()

        # Try to infer domain from tenant or use placeholder
        # Replace "itbd.net" with your actual domain for accurate mapping
        return f"{username}@itbd.net"

    return "unknown@itbd.net"


async def handle_turn(context: TurnContext, conversation_data: dict):
    """
    Main router — every message from the user passes through here.
    Determines intent from button clicks or free text, then calls
    the appropriate handler block.
    """
    await context.send_activity({"type": "typing"})

    activity   = context.activity
    value      = activity.value or {}

    # ── Slot-filling in progress — route all turns there first ────────────────
    if is_active(conversation_data):
        reply = await handle_slot_turn(conversation_data, activity.text or "")
        await context.send_activity(reply)
        return

    intent     = value.get("intent") or detect_intent(activity.text)

    from_prop  = activity.from_property
    full_name  = from_prop.name if from_prop else ""
    first_name = full_name.split()[0] if full_name else ""

    # ── KEY CHANGE — get real email for N-able customer routing ───────────────
    # N-able uses the email domain to find the correct customer organisation.
    # aarav.raina@itbd.net → looks up NABLE_CUSTOMER_MAP → finds customer 1118
    user_email = _get_user_email(activity)

    # ── Route by intent ────────────────────────────────────────────────────────

    if intent in ("MAIN_MENU", "UNKNOWN"):
        card = CardFactory.adaptive_card(get_welcome_card(first_name))
        await context.send_activity(MessageFactory.attachment(card))

    elif intent == "CREATE_TICKET":
        reply = start_slot_filling(conversation_data, activity.text or "")
        await context.send_activity(reply)

    elif intent == "RUN_DIAGNOSTICS":
        await context.send_activity(
            "Running diagnostics on your machine via N-able N-central — "
            "checking memory, CPU, and storage. "
            "This usually takes about 30 seconds. Hold tight ⏳"
        )
        try:
            # ── CHANGE — pass user_email so N-able finds correct customer ─────
            results = rmm.run_diagnostics(full_name, user_email)
            await context.send_activity(_format_diagnostics(results))
            await context.send_activity({
                "type": "message",
                "text": "Would you like me to log a support ticket with these results?",
                "suggestedActions": {
                    "actions": [
                        {"type": "imBack", "title": "✅ Yes, log a ticket",
                         "value": "Yes log a ticket with diagnostic results"},
                        {"type": "imBack", "title": "❌ No thanks",
                         "value": "No thanks"}
                    ]
                }
            })
            conversation_data["pendingDiagnostics"] = results

        except Exception as e:
            await context.send_activity(
                f"⚠️ Could not run diagnostics: {str(e)}\n\n"
                "Make sure your device is online and enrolled in N-able N-central.\n"
                "If the issue persists contact your IT administrator."
            )

    elif intent == "RESET_OUTLOOK":
        await context.send_activity({
            "type": "message",
            "text": (
                "⚠️ **Outlook reset** will:\n\n"
                "• Close Outlook completely\n"
                "• Clear your Outlook profile cache\n"
                "• Remove cached OST files\n"
                "• Relaunch Outlook automatically\n\n"
                "You may need to re-enter your password. Continue?"
            ),
            "suggestedActions": {
                "actions": [
                    {"type": "imBack", "title": "✅ Yes, reset Outlook",
                     "value": "CONFIRM_OUTLOOK_RESET"},
                    {"type": "imBack", "title": "❌ Cancel",
                     "value": "menu"}
                ]
            }
        })

    elif intent == "CONFIRM_OUTLOOK_RESET":
        await context.send_activity(
            "Starting Outlook reset on your machine via N-able N-central 🔄"
        )
        try:
            # ── CHANGE — pass user_email so N-able finds correct customer ─────
            result = rmm.reset_outlook(full_name, user_email)
            await context.send_activity(
                f"✅ {result['message']}\n\n"
                "If Outlook does not open automatically, launch it manually."
            )
        except Exception as e:
            await context.send_activity(
                f"⚠️ Could not run the Outlook reset: {str(e)}\n\n"
                "Make sure your device is online and enrolled in N-able N-central."
            )

    elif intent == "CHECK_TICKET":
        ticket_id = value.get("ticketId") or conversation_data.get("lastTicketId")
        if not ticket_id:
            await context.send_activity(
                "Please provide your ticket number and I will look it up.\n\n"
                "Type: **check ticket 12345** (replace with your number)"
            )
        else:
            try:
                ticket = cw.get_ticket(int(ticket_id))
                await context.send_activity(
                    f"📋 **Ticket #{ticket['id']}**\n\n"
                    f"**Summary:** {ticket.get('summary', '')}\n"
                    f"**Status:** {ticket.get('status', {}).get('name', 'Unknown')}\n"
                    f"**Priority:** {ticket.get('priority', {}).get('name', 'Unknown')}\n"
                    f"**Last updated:** {ticket.get('_info', {}).get('lastUpdated', 'Unknown')}"
                )
            except Exception as e:
                await context.send_activity(
                    f"⚠️ Could not retrieve ticket: {str(e)}"
                )

    else:
        await context.send_activity(
            "I am not sure what you need — here is what I can help with:"
        )
        card = CardFactory.adaptive_card(get_welcome_card(first_name))
        await context.send_activity(MessageFactory.attachment(card))


def _format_diagnostics(results: dict) -> str:
    """
    Formats N-able diagnostic results into a readable Teams message.
    Shows a demo mode notice when running in mock mode.
    """
    is_mock = results.get("device", {}).get("_mock", False)
    header  = f"📊 **Diagnostic results for {results['device']['name']}**"

    if is_mock:
        header += "\n_⚠️ Running in demo mode — results are simulated_"

    lines = [header, ""]

    m    = results.get("memory", {})
    pct  = m.get("usedPercent", 0)
    icon = "🔴" if pct > 85 else "🟡" if pct > 60 else "🟢"
    lines.append(
        f"{icon} **Memory:** {pct}% used "
        f"({m.get('usedGB')} GB / {m.get('totalGB')} GB)"
    )

    c    = results.get("cpu", {})
    load = c.get("loadPercent", 0)
    icon = "🔴" if load > 85 else "🟡" if load > 60 else "🟢"
    lines.append(f"{icon} **CPU:** {load}% load")

    for drive in results.get("storage", []):
        dp   = drive.get("usedPercent", 0)
        icon = "🔴" if dp > 90 else "🟡" if dp > 75 else "🟢"
        lines.append(
            f"{icon} **Drive {drive.get('name')}:** "
            f"{dp}% used ({drive.get('freeGB')} GB free)"
        )

    lines.append(f"\n🖥️ **OS:** {results['device'].get('os', 'Unknown')}")

    if is_mock:
        lines.append(
            "\n_Connect to N-able N-central to see real diagnostics._"
        )

    return "\n".join(lines)