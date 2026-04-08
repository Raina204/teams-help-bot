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
# The adapter is the bridge between your aiohttp web server and Azure Bot Service.
# It verifies that every incoming request genuinely comes from Microsoft,
# decodes the activity, and routes it to your bot class.
SETTINGS = BotFrameworkAdapterSettings(
    app_id=CONFIG.MICROSOFT_APP_ID,
    app_password=CONFIG.MICROSOFT_APP_PASSWORD
)
ADAPTER = BotFrameworkAdapter(SETTINGS)


# ── Global error handler ──────────────────────────────────────────────────────
# If anything throws an unhandled exception inside the bot, this catches it,
# logs it to the console, and sends a friendly message to the user
# instead of silently dying.
async def on_error(context, error: Exception):
    print(f"\n[on_error] Unhandled exception: {error}")
    await context.send_activity(
        "Something went wrong on my end. Please try again in a moment."
    )

ADAPTER.on_turn_error = on_error


# ── State storage ─────────────────────────────────────────────────────────────
# MemoryStorage keeps state in RAM — perfect for local development.
# When you deploy to Azure App Service, swap this for Azure Blob Storage
# so state persists across restarts.
MEMORY             = MemoryStorage()
CONVERSATION_STATE = ConversationState(MEMORY)
USER_STATE         = UserState(MEMORY)

# ── Bot instance ──────────────────────────────────────────────────────────────
BOT = HelpBot(CONVERSATION_STATE, USER_STATE)


# ── Route handlers ────────────────────────────────────────────────────────────

async def health_check(req: Request) -> Response:
    """
    GET /
    Simple health check endpoint. Azure App Service pings this to confirm
    the server is running. Also useful for you to verify the server started.
    """
    return web.Response(
        text=json.dumps({
            "status":  "Teams Help Bot is running",
            "version": "1.0.0",
            "port":    CONFIG.PORT
        }),
        content_type="application/json"
    )


async def messages(req: Request) -> Response:
    """
    POST /api/messages
    Every message a user sends in Teams arrives here as a JSON POST request
    from Azure Bot Service. The adapter authenticates and processes it.
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


# ── App setup ─────────────────────────────────────────────────────────────────
APP = web.Application()
APP.router.add_get("/",             health_check)
APP.router.add_post("/api/messages", messages)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n🤖 Teams Help Bot starting...")
    print(f"   Port:            {CONFIG.PORT}")
    print(f"   Health check:    http://localhost:{CONFIG.PORT}/")
    print(f"   Messaging endpoint: http://localhost:{CONFIG.PORT}/api/messages")
    print(f"\n   Waiting for messages...\n")
    web.run_app(APP, host="localhost", port=CONFIG.PORT)