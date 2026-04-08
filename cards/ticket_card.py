def get_ticket_form_card() -> dict:
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "Create a support ticket",
                "weight": "Bolder",
                "size": "Medium"
            },
            {
                "type": "TextBlock",
                "text": "Briefly describe your issue:",
                "wrap": True,
                "spacing": "Medium"
            },
            {
                "type": "Input.Text",
                "id": "ticketSummary",
                "placeholder": "e.g. My Outlook keeps crashing when I open attachments",
                "isMultiline": True,
                "maxLength": 500
            },
            {
                "type": "TextBlock",
                "text": "Priority:",
                "wrap": True,
                "spacing": "Medium"
            },
            {
                "type": "Input.ChoiceSet",
                "id": "ticketPriority",
                "value": "Medium",
                "choices": [
                    {"title": "🔴 High — I cannot work",       "value": "High"},
                    {"title": "🟡 Medium — Impacting my work", "value": "Medium"},
                    {"title": "🟢 Low — Minor issue",          "value": "Low"}
                ]
            }
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Submit ticket",
                "data": {"intent": "SUBMIT_TICKET"}
            },
            {
                "type": "Action.Submit",
                "title": "Cancel",
                "data": {"intent": "MAIN_MENU"}
            }
        ]
    }


def get_ticket_created_card(ticket: dict) -> dict:
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "✅ Ticket created successfully",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Good"
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Ticket #",  "value": str(ticket.get("id", ""))},
                    {"title": "Summary",   "value": ticket.get("summary", "")},
                    {"title": "Priority",  "value": ticket.get("priority", "")},
                    {"title": "Board",     "value": ticket.get("board", {}).get("name", "Service Desk")},
                    {"title": "Status",    "value": ticket.get("status", {}).get("name", "New")}
                ],
                "spacing": "Medium"
            },
            {
                "type": "TextBlock",
                "text": "A technician will pick this up shortly. Reference your ticket number if you need to follow up.",
                "wrap": True,
                "spacing": "Medium",
                "isSubtle": True
            }
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "➕ Add more details",
                "data": {"intent": "ADD_NOTE", "ticketId": ticket.get("id")}
            },
            {
                "type": "Action.Submit",
                "title": "🏠 Main menu",
                "data": {"intent": "MAIN_MENU"}
            }
        ]
    }