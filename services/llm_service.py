"""
services/llm_service.py

LLM bridge — connects the Teams bot to OpenAI (gpt-4o)
using the tool definitions from mcp_tools/server.py.
"""

import os
import json
from openai import OpenAI
from mcp_tools.server import TOOL_DEFINITIONS, execute_tool


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set in .env.\n"
                "Get a key from platform.openai.com and add:\n"
                "  OPENAI_API_KEY=sk-..."
            )
        _client = OpenAI(api_key=api_key)
    return _client


_SYSTEM_PROMPT = """\
You are an IT helpdesk assistant for ITBD, embedded directly in Microsoft Teams.

You help employees with:
  • Creating ConnectWise support tickets for IT issues
  • Checking the status of existing tickets
  • Adding notes to open tickets
  • Running PC health diagnostics (memory, CPU, storage) via ConnectWise Automate
  • Resetting Outlook profiles when Outlook is broken
  • Restarting the Windows print spooler service when printing is not working
  • Checking printer and spooler status
  • Clearing a stuck print queue
  • Listing installed printers on a device
  • Changing the system timezone on Windows, macOS, or Linux

How to behave:
  • Be concise and friendly. Employees have real IT problems to solve.
  • To create a ticket you need: a short summary and a brief description.
    Ask for both in ONE message if you do not have them yet.
  • Never ask for information you already have (user name and email are
    provided automatically from their Teams profile).
  • For diagnostics: run them immediately, no confirmation needed.
  • For Outlook reset: it closes and wipes Outlook's cache — always
    warn the user and confirm before calling reset_outlook.
  • For printer issues (can't print, stuck jobs, spooler errors): restart
    the print spooler first — it resolves most printer problems. No
    confirmation needed.
  • For timezone changes: ask which timezone the user wants and which OS
    they are on (Windows, macOS, or Linux) if not already clear from context.
    Then run the change immediately — no further confirmation needed.
  • After creating a ticket, always show the ticket number clearly.
  • If you cannot help, direct the user to contact IT support directly.
"""


def process_message(
    user_message:         str,
    conversation_history: list,
    user_name:            str = "",
    user_email:           str = "",
    tenant_id:            str = "",
) -> str:
    try:
        client = _get_client()
    except RuntimeError as exc:
        return str(exc)

    system_content = _SYSTEM_PROMPT
    if user_name or user_email:
        system_content += f"\nCurrent user: {user_name}  |  email: {user_email}"

    messages = [{"role": "system", "content": system_content}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    for iteration in range(6):
        response = client.chat.completions.create(
            model       = "gpt-4o",
            messages    = messages,
            tools       = TOOL_DEFINITIONS,
            tool_choice = "auto",
        )

        choice = response.choices[0]

        if choice.finish_reason == "stop":
            return choice.message.content or "I could not generate a response."

        if choice.finish_reason == "tool_calls":
            messages.append(choice.message)

            for tool_call in choice.message.tool_calls:
                args = json.loads(tool_call.function.arguments)
                args["user_tenant_id"] = tenant_id
                args["user_email"]     = args.get("user_email") or user_email
                result = execute_tool(tool_call.function.name, args)
                print(
                    f"[llm_service] iter={iteration} "
                    f"tool={tool_call.function.name!r} "
                    f"result_preview={result[:100]!r}"
                )
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call.id,
                    "content":      result,
                })
            continue

        return choice.message.content or "I could not generate a response."

    return "I ran into an issue processing your request. Please try again."
