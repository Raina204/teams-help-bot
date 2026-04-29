def get_welcome_card(user_name: str = "") -> dict:
    greeting = f"Hi {user_name}!" if user_name else "Hi there!"
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": f" {greeting}",
                "weight": "Bolder",
                "size": "Large",
                "wrap": True
            },
            {
                "type": "TextBlock",
                "text": "I am your IT support bot. I can log tickets, run diagnostics on your machine, and fix common issues automatically.",
                "wrap": True,
                "spacing": "Small"
            },
            {
                "type": "TextBlock",
                "text": "What would you like to do?",
                "wrap": True,
                "spacing": "Medium",
                "weight": "Bolder"
            }
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Log a support ticket",
                "data": {"intent": "CREATE_TICKET"}
            },
            {
                "type": "Action.Submit",
                "title": "Run PC diagnostics",
                "data": {"intent": "RUN_DIAGNOSTICS"}
            },
            {
                "type": "Action.Submit",
                "title": "Fix my Outlook",
                "data": {"intent": "RESET_OUTLOOK"}
            },
            {
                "type": "Action.Submit",
                "title": "Check my ticket status",
                "data": {"intent": "CHECK_TICKET"}
            },
            {
                "type": "Action.Submit",
                "title": "Change Timezone",
                "data": {"intent": "CHANGE_TIMEZONE"}
            },
            {
                "type": "Action.Submit",
                "title": "Printer Issues",
                "data": {"intent": "PRINTER_STATUS"}
            },
            {
                "type": "Action.Submit",
                "title": "Restart Printer Spooler",
                "data": {"intent": "RESTART_SPOOLER"}
            },
        ]
    }