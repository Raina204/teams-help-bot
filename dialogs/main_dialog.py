from botbuilder.core import TurnContext, CardFactory, MessageFactory
from cards.welcome_card import get_welcome_card
from cards.ticket_card import get_ticket_form_card, get_ticket_created_card
from services import connectwise_service as cw
from services import rmm_service as rmm

# ── Intent keyword patterns ───────────────────────────────────────────────────
# When a user types free text instead of clicking a button, we scan their
# message against these patterns to figure out what they want.
INTENT_PATTERNS = [
    ("CREATE_TICKET",          ["ticket", "issue", "problem", "broken", "not working", "support", "help"]),
    ("RUN_DIAGNOSTICS",        ["slow", "diagnose", "check my pc", "memory", "cpu", "storage", "disk", "performance"]),
    ("RESET_OUTLOOK",          ["outlook", "email", "calendar", "mail", "ost", "fix outlook"]),
    ("CHECK_TICKET",           ["status", "update", "my ticket", "progress", "ticket number"]),
    ("CONFIRM_OUTLOOK_RESET",  ["confirm_outlook_reset", "yes reset", "yes, reset"]),
    ("MAIN_MENU",              ["menu", "start", "home", "hello", "hi", "hey", "help"]),
]

# ── Triage rules ──────────────────────────────────────────────────────────────
# These run automatically before creating a ticket to assign board, type,
# and priority based on keywords in the user's issue description.
TRIAGE_RULES = [
    (["outlook", "email", "calendar", "ost", "mail"],      "Service Desk", "Email Issue",            "Medium"),
    (["slow", "freeze", "crash", "blue screen", "bsod"],   "Service Desk", "Performance",            "High"),
    (["printer", "print", "scan", "scanner"],              "Service Desk", "Hardware",               "Medium"),
    (["vpn", "remote", "rdp", "remote desktop"],           "Service Desk", "Network/Connectivity",   "High"),
    (["password", "locked out", "login", "access denied"], "Service Desk", "Account Access",         "High"),
    (["wifi", "internet", "network", "no connection"],     "Service Desk", "Network/Connectivity",   "High"),
    (["install", "software", "application", "app"],        "Service Desk", "Software Request",       "Low"),
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
    return "Service Desk", "General Request", "Medium"


async def handle_turn(context: TurnContext, conversation_data: dict):
    """
    Main router — every message from the user passes through here.
    Determines intent from button clicks or free text, then calls
    the appropriate handler block.
    """
    # Always send typing indicator immediately so the user knows the bot is working
    await context.send_activity({"type": "typing"})

    activity   = context.activity
    value      = activity.value or {}

    # Intent comes from a card button click (value.intent) or free text detection
    intent     = value.get("intent") or detect_intent(activity.text)

    # Extract user details from the Teams activity
    from_prop  = activity.from_property
    full_name  = from_prop.name if from_prop else ""
    first_name = full_name.split()[0] if full_name else ""

    # Build a best-guess email from the display name
    # This will be replaced with a real Graph API call in a later phase
    user_email = f"{full_name.replace(' ', '.').lower()}@placeholder.com"

    # ── Route by intent ───────────────────────────────────────────────────────

    if intent in ("MAIN_MENU", "UNKNOWN"):
        card = CardFactory.adaptive_card(get_welcome_card(first_name))
        await context.send_activity(MessageFactory.attachment(card))

    elif intent == "CREATE_TICKET":
        card = CardFactory.adaptive_card(get_ticket_form_card())
        await context.send_activity(MessageFactory.attachment(card))

    elif intent == "SUBMIT_TICKET":
        summary  = (value.get("ticketSummary") or "").strip()
        priority = value.get("ticketPriority") or "Medium"

        if not summary:
            await context.send_activity(
                "Please enter a description of your issue before submitting."
            )
            card = CardFactory.adaptive_card(get_ticket_form_card())
            await context.send_activity(MessageFactory.attachment(card))
            return

        board, ticket_type, _ = triage_ticket(summary)
        await context.send_activity(
            f"🔍 I have categorised your issue as **{ticket_type}** "
            f"with **{priority}** priority. Creating your ticket now..."
        )

        try:
            ticket = cw.create_ticket(
                summary=summary,
                priority=priority,
                board=board,
                ticket_type=ticket_type,
                user_name=full_name
            )
            card = CardFactory.adaptive_card(get_ticket_created_card(ticket))
            await context.send_activity(MessageFactory.attachment(card))
        except Exception as e:
            await context.send_activity(
                f"⚠️ I could not create the ticket right now.\n\n"
                f"Error: {str(e)}\n\n"
                f"Please contact your helpdesk directly."
            )

    elif intent == "RUN_DIAGNOSTICS":
        await context.send_activity(
            "Running diagnostics on your machine — checking memory, CPU, and storage. "
            "This usually takes about 30 seconds. Hold tight ⏳"
        )
        try:
            results = rmm.run_diagnostics(full_name, user_email)
            await context.send_activity(_format_diagnostics(results))
            await context.send_activity({
                "type": "message",
                "text": "Would you like me to log a support ticket with these results?",
                "suggestedActions": {
                    "actions": [
                        {"type": "imBack", "title": "✅ Yes, log a ticket", "value": "Yes log a ticket with diagnostic results"},
                        {"type": "imBack", "title": "❌ No thanks",         "value": "No thanks"}
                    ]
                }
            })
            conversation_data["pendingDiagnostics"] = results
        except Exception as e:
            await context.send_activity(
                f"⚠️ Could not run diagnostics: {str(e)}\n\n"
                "Make sure your device is online and enrolled in the RMM."
            )

    elif intent == "RESET_OUTLOOK":
        await context.send_activity({
            "type": "message",
            "text": (
                "⚠️ **Outlook reset** will:\n\n"
                "• Close Outlook completely\n"
                "• Clear your Outlook profile cache\n"
                "• Relaunch Outlook automatically\n\n"
                "You may need to re-enter your password. Continue?"
            ),
            "suggestedActions": {
                "actions": [
                    {"type": "imBack", "title": "✅ Yes, reset Outlook", "value": "CONFIRM_OUTLOOK_RESET"},
                    {"type": "imBack", "title": "❌ Cancel",             "value": "menu"}
                ]
            }
        })

    elif intent == "CONFIRM_OUTLOOK_RESET":
        await context.send_activity("Starting Outlook reset on your machine 🔄")
        try:
            result = rmm.reset_outlook(full_name, user_email)
            await context.send_activity(
                f"✅ {result['message']}\n\n"
                "If Outlook does not open automatically, launch it manually."
            )
        except Exception as e:
            await context.send_activity(
                f"⚠️ Could not run the Outlook reset: {str(e)}"
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
                await context.send_activity(f"⚠️ Could not retrieve ticket: {str(e)}")

    else:
        # Fallback — show the menu for anything unrecognised
        await context.send_activity("I am not sure what you need — here is what I can help with:")
        card = CardFactory.adaptive_card(get_welcome_card(first_name))
        await context.send_activity(MessageFactory.attachment(card))


def _format_diagnostics(results: dict) -> str:
    """Formats the RMM diagnostic results into a readable Teams message."""
    lines = [f"📊 **Diagnostic results for {results['device']['name']}**\n"]

    m = results.get("memory", {})
    pct = m.get("usedPercent", 0)
    icon = "🔴" if pct > 85 else "🟡" if pct > 60 else "🟢"
    lines.append(f"{icon} **Memory:** {pct}% used ({m.get('usedGB')} GB / {m.get('totalGB')} GB)")

    c = results.get("cpu", {})
    load = c.get("loadPercent", 0)
    icon = "🔴" if load > 85 else "🟡" if load > 60 else "🟢"
    lines.append(f"{icon} **CPU:** {load}% load")

    for drive in results.get("storage", []):
        pct = drive.get("usedPercent", 0)
        icon = "🔴" if pct > 90 else "🟡" if pct > 75 else "🟢"
        lines.append(
            f"{icon} **Drive {drive.get('name')}:** "
            f"{pct}% used ({drive.get('freeGB')} GB free)"
        )

    lines.append(f"\n🖥️ **OS:** {results['device'].get('os', 'Unknown')}")
    return "\n".join(lines)