import json
from aiohttp import web
from aiohttp.web import Request, Response
from botbuilder.core import (
    BotFrameworkAdapterSettings,
    BotFrameworkAdapter,
    ConversationState,
    UserState,
    MemoryStorage
)
from botbuilder.schema import Activity
from bot.help_bot import HelpBot
from config.config import CONFIG



# ── Bot Framework adapter ─────────────────────────────────────────────────────
SETTINGS = BotFrameworkAdapterSettings(
    app_id=CONFIG.MICROSOFT_APP_ID,
    app_password=CONFIG.MICROSOFT_APP_PASSWORD
)
ADAPTER = BotFrameworkAdapter(SETTINGS)


# ── Global error handler ──────────────────────────────────────────────────────
async def on_error(context, error: Exception):
    print(f"\n[on_error] Unhandled exception: {error}")
    await context.send_activity(
        "Something went wrong on my end. Please try again in a moment."
    )

ADAPTER.on_turn_error = on_error


# ── State storage ─────────────────────────────────────────────────────────────
MEMORY             = MemoryStorage()
CONVERSATION_STATE = ConversationState(MEMORY)
USER_STATE         = UserState(MEMORY)

# ── Bot instance ──────────────────────────────────────────────────────────────
BOT = HelpBot(CONVERSATION_STATE, USER_STATE)


# ── Route handlers ────────────────────────────────────────────────────────────

async def health_check(req: Request) -> Response:
    """
    GET /
    Simple health check endpoint.
    """
    return web.Response(
        text=json.dumps({
            "status":  "Teams Help Bot is running",
            "version": "1.0.0",
            "port":    CONFIG.PORT,
            "mcp":     "available at /mcp"
        }),
        content_type="application/json"
    )


async def messages(req: Request) -> Response:
    """
    POST /api/messages
    Every message a user sends in Teams arrives here.
    """
    if req.content_type != "application/json":
        return web.Response(status=415, text="Unsupported Media Type")

    body        = await req.json()
    activity    = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")

    response = await ADAPTER.process_activity(activity, auth_header, BOT.on_turn)
    if response:
        return web.json_response(data=response.body, status=response.status)
    return web.Response(status=201)


async def mcp_endpoint(_req: Request) -> Response:
    """
    GET /mcp
    Returns info about the MCP server. The MCP SSE server runs
    separately on port 3979 (start with: python run_mcp.py).
    """
    return web.Response(
        text=json.dumps({
            "status": "MCP server runs separately",
            "sse_endpoint": f"http://localhost:3979",
            "tools": [
                "mcp_create_ticket", "mcp_add_note",
                "mcp_get_ticket", "mcp_get_tickets_by_company",
                "mcp_find_device", "mcp_run_diagnostics",
                "mcp_reset_outlook",
            ],
            "start_command": "python run_mcp.py",
        }),
        content_type="application/json"
    )


# ── App setup ─────────────────────────────────────────────────────────────────
APP = web.Application()
APP.router.add_get("/",              health_check)
APP.router.add_post("/api/messages", messages)
APP.router.add_get("/mcp",           mcp_endpoint)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n Teams Help Bot starting...")
    print(f"   Port:               {CONFIG.PORT}")
    print(f"   Health check:       http://localhost:{CONFIG.PORT}/")
    print(f"   Messaging endpoint: http://localhost:{CONFIG.PORT}/api/messages")
    print(f"   MCP endpoint:       http://localhost:{CONFIG.PORT}/mcp")
    print(f"\n   Waiting for messages...\n")
    web.run_app(APP, host="localhost", port=CONFIG.PORT)