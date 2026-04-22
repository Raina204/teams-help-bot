from __future__ import annotations
import json
import logging
import traceback
import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

import openai
from openai import AsyncOpenAI

from mcp_tools.server import TOOL_DEFINITIONS, execute_tool

log = logging.getLogger(__name__)

MAX_ITERATIONS = 8

SYSTEM_PROMPT = """You are an IT helpdesk assistant embedded in Microsoft Teams.
You help users resolve IT problems by creating tickets, running scripts, and triaging issues.

RULES — follow these strictly:
1. When a user reports ANY IT problem, call create_ticket first. Wait for the result,
   then call triage_ticket using the ticket_id returned. Do NOT call them at the same time.
2. If you need to run RMM scripts but don't have a machine_identifier, call lookup_user_device first.
3. If the user mentions Outlook issues (not syncing, crashing, calendar), also call run_outlook_reset.
4. If the user says their PC or computer is slow, also call run_utilization_scan with scan_type="all".
5. Always confirm every action to the user with the ticket number and what was done.
6. Keep replies short, friendly, and jargon-free. The user is non-technical.
7. If a tool returns an error field, tell the user clearly and suggest they email support@company.com.

TIMEZONE CHANGES — follow these steps exactly:
8. When a user asks to change timezone, identify the IANA and Windows timezone names.
9. Call apply_timezone_change with iana_timezone and windows_timezone.
10. Report back the result — confirm the timezone is now updated on their account.
11. Ask if they want a ConnectWise ticket logged for this change.

COMMON TIMEZONE MAPPINGS (IANA → Windows):
  America/New_York    → Eastern Standard Time
  America/Chicago     → Central Standard Time
  America/Denver      → Mountain Standard Time
  America/Los_Angeles → Pacific Standard Time
  Europe/London       → GMT Standard Time
  Europe/Paris        → W. Europe Standard Time
  Asia/Tokyo          → Tokyo Standard Time
  Asia/Kolkata        → India Standard Time
  Asia/Dubai          → Arabian Standard Time
  Asia/Singapore      → Singapore Standard Time
  Asia/Karachi        → Pakistan Standard Time
  Australia/Sydney    → AUS Eastern Standard Time
  UTC                 → UTC

TONE: Calm, helpful, professional. Never say "I cannot" — always offer an alternative."""


@dataclass
class UserContext:
    user_id:   str
    user_name: str
    tenant_id: str
    message:   str
    user_email: str = ""  
    history:   list = field(default_factory=list)


@dataclass
class McpResponse:
    text:          str
    card:          dict | None = None
    actions_taken: list[str]   = field(default_factory=list)


def _get_client() -> AsyncOpenAI:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    return AsyncOpenAI(api_key=api_key)


class McpOrchestrator:

    @staticmethod
    async def process(ctx: UserContext) -> McpResponse:
        client = _get_client()
        model  = "gpt-4o"

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    f"{SYSTEM_PROMPT}\n\n"
                    f"Current user: {ctx.user_name} "
                    f"(Teams ID: {ctx.user_id}, tenant: {ctx.tenant_id})"
                ),
            },
            *ctx.history,
            {"role": "user", "content": ctx.message},
        ]

        final_text    = ""
        card: dict | None = None
        actions_taken: list[str] = []

        # --------------------------------------------------------------
        # Timezone shortcut — inject explicit instructions so the LLM
        # always responds with commands rather than refusing.
        # --------------------------------------------------------------
        _TIMEZONE_KEYWORDS = [
            "timezone", "time zone", "set timezone", "change timezone",
            "set my timezone", "change my timezone", "wrong time",
            "clock wrong", "clock is wrong", "utc", "est", "pst",
            "cst", "gmt", "tokyo time", "new york time", "london time",
            "india time", "set my time",
        ]
        _msg_lower = ctx.message.lower()
        if any(kw in _msg_lower for kw in _TIMEZONE_KEYWORDS):
            messages.append({
                "role": "system",
                "content": (
                    "The user is asking about a timezone change. "
                    "You MUST respond with the exact OS commands as instructed in your system prompt. "
                    "Do NOT say you are unable to change timezone settings. "
                    "Provide the Windows tzutil command, the macOS systemsetup command, "
                    "and the Linux timedatectl command. "
                    "Then ask if they want a ConnectWise ticket logged for this change."
                ),
            })

        for iteration in range(MAX_ITERATIONS):
            log.info(
                "mcp.llm_call — iteration=%d messages=%d user=%s model=%s",
                iteration, len(messages), ctx.user_name, model,
            )

            try:
                response = await client.chat.completions.create(
                    model               = model,
                    messages            = messages,
                    tools               = TOOL_DEFINITIONS,
                    tool_choice         = "auto",
                    parallel_tool_calls = False,
                    max_tokens          = 1024,
                    temperature         = 0.2,
                )
            except openai.AuthenticationError:
                raise
            except openai.RateLimitError:
                raise
            except openai.APIConnectionError:
                raise
            except openai.APITimeoutError:
                raise
            except openai.OpenAIError as exc:
                log.error("mcp.openai_error: %s — %s", type(exc).__name__, exc)
                raise

            choice  = response.choices[0]
            message = choice.message

            log.info(
                "mcp.llm_response — finish_reason=%s tool_calls=%s content_preview=%r",
                choice.finish_reason,
                bool(message.tool_calls),
                (message.content or "")[:60],
            )

            if message.content:
                final_text = message.content

            if choice.finish_reason != "tool_calls" or not message.tool_calls:
                break

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id":       tc.id,
                        "type":     "function",
                        "function": {
                            "name":      tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            }
            if message.content is not None:
                assistant_msg["content"] = message.content

            messages.append(assistant_msg)

            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name

                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as exc:
                    log.error(
                        "mcp.tool_args_parse_error — tool=%s raw=%r error=%s",
                        fn_name, tool_call.function.arguments, exc,
                    )
                    fn_args = {}

                log.info("mcp.tool_call — name=%s args=%s", fn_name, fn_args)

                fn_args["user_email"]     = ctx.user_email
                fn_args["user_tenant_id"] = ctx.tenant_id

                try:
                    result_str: str = await asyncio.to_thread(
                        execute_tool, fn_name, fn_args
                    )
                except Exception as exc:
                    log.error(
                        "mcp.tool_execution_error — tool=%s error=%s\n%s",
                        fn_name, exc, traceback.format_exc(),
                    )
                    result_str = json.dumps({
                        "error":   str(exc),
                        "tool":    fn_name,
                        "message": "Tool execution failed — tell the user and suggest contacting support.",
                    })

                actions_taken.append(fn_name)

                messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call.id,
                    "content":      result_str,
                })

        else:
            log.warning("mcp.max_iterations_reached — max=%d", MAX_ITERATIONS)

        log.info(
            "mcp.done — actions=%s has_card=%s reply_length=%d",
            actions_taken, bool(card), len(final_text),
        )

        return McpResponse(
            text=final_text or "Done — I've completed those actions for you.",
            card=card,
            actions_taken=actions_taken,
        )