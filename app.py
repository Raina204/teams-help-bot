import json
import logging

from aiohttp import web
from aiohttp.web import Request, Response
from botbuilder.core import (
    BotFrameworkAdapterSettings,
    BotFrameworkAdapter,
    ConversationState,
    UserState,
    MemoryStorage,
)
from botbuilder.schema import Activity

from bot.help_bot import HelpBot
from config.config import CONFIG

# ── Multi-tenant imports ──────────────────────────────────────────────────────
from config import (
    resolver,
    rate_limiter,
    log_denied,
    TenantNotFoundError,
    ActionNotAllowedError,
    RateLimitExceededError,
)
from config.tenant_resolver import TenantResolverError

logger = logging.getLogger(__name__)


# ── Bot Framework adapter ─────────────────────────────────────────────────────
SETTINGS = BotFrameworkAdapterSettings(
    app_id=CONFIG.MICROSOFT_APP_ID,
    app_password=CONFIG.MICROSOFT_APP_PASSWORD,
    channel_auth_tenant=CONFIG.MICROSOFT_APP_TENANT_ID,
)
ADAPTER = BotFrameworkAdapter(SETTINGS)


# ── Global error handler ──────────────────────────────────────────────────────
async def on_error(context, error: Exception):
    """
    Catch-all for unhandled exceptions that escape the turn handler.
    Multi-tenant note: by the time we reach here tenant_ctx may not
    exist, so we log generically without assuming tenant identity.
    """
    logger.error(f"[on_error] Unhandled exception: {error}", exc_info=True)
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


# ── Multi-tenant turn handler ─────────────────────────────────────────────────

async def tenant_aware_turn(turn_context):
    """
    Wraps BOT.on_turn with the full multi-tenant pipeline.
    This runs on every single inbound message before any bot logic.

    Pipeline order:
        1. Resolve tenant  — who is this workspace?
        2. Rate limit      — are they sending too many requests?
        3. Bot logic       — run HelpBot with tenant_ctx injected
        4. Exceptions      — handle all tenant-specific error cases cleanly
    """

    # ── Step 1: Resolve tenant ────────────────────────────────────────────
    # Maps the inbound Teams team_id / Slack workspace_id → tenant config dict.
    # If the workspace isn't registered, we stop immediately and tell the user.
    try:
        tenant_ctx = resolver.resolve(turn_context)
        logger.info(
            f"Tenant resolved: {tenant_ctx['tenant_id']} "
            f"({tenant_ctx['display_name']})"
        )
    except TenantNotFoundError:
        logger.warning(
            f"Unregistered workspace attempted to use bot. "
            f"channel_data={turn_context.activity.channel_data}"
        )
        await turn_context.send_activity(
            "Sorry, your workspace isn't registered with this bot. "
            "Please contact your IT administrator to get set up."
        )
        return
    except TenantResolverError as exc:
        logger.error(f"Resolver structural error: {exc}")
        await turn_context.send_activity(
            "There's a configuration problem with this bot. "
            "Please contact your IT administrator."
        )
        return

    # ── Step 2: Rate limit check ──────────────────────────────────────────
    # Each tenant has a rate_limit_per_minute in their config.
    # This prevents one busy client from hammering the shared APIs
    # (ConnectWise Manage, ConnectWise Automate) and degrading service for all other tenants.
    try:
        rate_limiter.check(tenant_ctx)
    except RateLimitExceededError as exc:
        logger.warning(
            f"Rate limit exceeded — tenant={tenant_ctx['tenant_id']}"
        )
        await turn_context.send_activity(str(exc))
        return

    # ── Step 3: Run bot logic with tenant context ─────────────────────────
    # Pass tenant_ctx into HelpBot so every dialog and service call
    # is automatically scoped to this tenant's credentials and permissions.
    try:
        await BOT.on_turn(turn_context, tenant_ctx)

    # ── Step 4: Handle tenant-aware exceptions ────────────────────────────

    except ActionNotAllowedError as exc:
        # RBAC blocked this action for this tenant.
        # log_denied is called here as a safety net — ideally your
        # orchestrator calls it directly so it has more context (user email etc).
        log_denied(tenant_ctx, user="unknown", action=exc.action)
        logger.warning(
            f"Action denied — tenant={tenant_ctx['tenant_id']} "
            f"action={exc.action}"
        )
        await turn_context.send_activity(
            f"Sorry, that action isn't available for your organisation. "
            f"Please contact your IT administrator if you think this is wrong."
        )

    except Exception as exc:
        # Unexpected error inside bot logic.
        # Log with tenant context so you can filter logs per client.
        logger.error(
            f"Unhandled error in bot turn — "
            f"tenant={tenant_ctx['tenant_id']} "
            f"error={exc}",
            exc_info=True,
        )
        await turn_context.send_activity(
            "Something went wrong. Please try again in a moment."
        )


# ── Route handlers ────────────────────────────────────────────────────────────

async def health_check(req: Request) -> Response:
    """
    GET /
    Simple health check — also reports which tenants are loaded.
    """
    loaded = resolver.registered_tenant_ids
    return web.Response(
        text=json.dumps({
            "status":          "Teams Help Bot is running",
            "version":         "1.0.0",
            "port":            CONFIG.PORT,
            "mcp":             "available at /mcp",
            "tenants_loaded":  len(loaded),
            "tenant_ids":      loaded,
        }),
        content_type="application/json",
    )


async def messages(req: Request) -> Response:
    """
    POST /api/messages
    Every message a user sends in Teams arrives here.
    Now uses tenant_aware_turn instead of BOT.on_turn directly.
    """
    if req.content_type != "application/json":
        return web.Response(status=415, text="Unsupported Media Type")

    body        = await req.json()
    activity    = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")

    # tenant_aware_turn replaces BOT.on_turn as the callback.
    # The adapter calls it with a fully constructed TurnContext.
    response = await ADAPTER.process_activity(
        activity, auth_header, tenant_aware_turn
    )
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
            "status":       "MCP server runs separately",
            "sse_endpoint": "http://localhost:3979",
            "tools": [
                "mcp_create_ticket",        "mcp_add_note",
                "mcp_get_ticket",           "mcp_get_tickets_by_company",
                "mcp_find_device",          "mcp_run_diagnostics",
                "mcp_reset_outlook",
            ],
            "start_command": "python run_mcp.py",
        }),
        content_type="application/json",
    )


# ── App setup ─────────────────────────────────────────────────────────────────
APP = web.Application()
APP.router.add_get("/",              health_check)
APP.router.add_post("/api/messages", messages)
APP.router.add_get("/mcp",           mcp_endpoint)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loaded_tenants = resolver.registered_tenant_ids
    print(f"\n  Teams Help Bot starting  (multi-tenant mode)")
    print(f"   Port:               {CONFIG.PORT}")
    print(f"   Health check:       http://localhost:{CONFIG.PORT}/")
    print(f"   Messaging endpoint: http://localhost:{CONFIG.PORT}/api/messages")
    print(f"   MCP endpoint:       http://localhost:{CONFIG.PORT}/mcp")
    print(f"   Tenants loaded:     {len(loaded_tenants)} → {loaded_tenants}")
    print(f"\n   Waiting for messages...\n")
    web.run_app(APP, host="localhost", port=CONFIG.PORT)