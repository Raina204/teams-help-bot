"""
config/tenant_resolver.py
--------------------------
Resolves every inbound bot message to a tenant_ctx dict.

This is the FIRST thing that runs on every message in bot/app.py.
It maps identifiers from the incoming activity (Teams team_id,
Slack workspace_id, etc.) to a tenant_id, then loads that tenant's
full config via TenantLoader.

Usage (in bot/app.py):
    from config.tenant_resolver import TenantResolver

    resolver = TenantResolver()   # once at startup

    async def on_message_activity(self, turn_context: TurnContext):
        tenant_ctx = resolver.resolve(turn_context)
        await self.orchestrator.handle(turn_context, tenant_ctx)

Design rules:
    - resolver.resolve() raises TenantNotFoundError for unknown callers.
      Never silently fall through to a default tenant.
    - tenant_ctx is a plain dict — no classes, no state, no mutation.
    - Every function downstream receives tenant_ctx as an argument.
      Nothing reads it from a global or class attribute.
"""

import logging
from typing import Optional

from botbuilder.core import TurnContext

from config.tenant_loader import TenantLoader, loader as default_loader

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions — catch these specifically in app.py to send the user
# a clean "unrecognised workspace" message instead of a 500 error.
# ---------------------------------------------------------------------------

class TenantNotFoundError(Exception):
    """Raised when an inbound message cannot be mapped to any known tenant."""
    pass


class TenantResolverError(Exception):
    """Raised when the resolver encounters an unexpected structural problem."""
    pass


# ---------------------------------------------------------------------------
# TenantResolver
# ---------------------------------------------------------------------------

class TenantResolver:
    """
    Builds a lookup map at startup from all loaded tenant configs,
    then resolves each inbound TurnContext to a tenant_ctx dict.

    Supports:
        - Microsoft Teams  (resolves by team_id from channel_data)
        - Slack            (resolves by team_id from channel_data)
        - Direct test injection via resolve_by_team_id() for unit tests
    """

    def __init__(self, tenant_loader: Optional[TenantLoader] = None):
        """
        Args:
            tenant_loader: TenantLoader instance. Defaults to the
                           module-level singleton from tenant_loader.py.
        """
        self._loader = tenant_loader or default_loader

        # Build lookup: team_id (string) -> tenant_id (string)
        self._team_id_map: dict[str, str] = {}

        self._build_lookup_map()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, turn_context: TurnContext) -> dict:
        """
        Main entry point. Call this as the first line of on_message_activity.

        Extracts the team/workspace identifier from the TurnContext activity,
        maps it to a tenant_id, and returns the full tenant config dict.

        Args:
            turn_context: The Bot Framework TurnContext for this message.

        Returns:
            tenant_ctx dict — the full config for the matched tenant.

        Raises:
            TenantNotFoundError: if the team/workspace ID is not registered.
            TenantResolverError: if the activity structure is unexpected.
        """
        team_id = self._extract_team_id(turn_context)
        logger.debug(f"Resolving tenant for team_id: {team_id}")
        return self.resolve_by_team_id(team_id)

    def resolve_by_team_id(self, team_id: str) -> dict:
        """
        Resolve a tenant from a raw team_id string.
        Use this in unit tests instead of constructing a TurnContext.

        Args:
            team_id: Teams team_id or Slack workspace_id string.

        Returns:
            tenant_ctx dict.

        Raises:
            TenantNotFoundError: if team_id is not in the lookup map.
        """
        tenant_id = self._team_id_map.get(team_id)

        if not tenant_id:
            registered = list(self._team_id_map.keys())
            raise TenantNotFoundError(
                f"No tenant registered for team_id '{team_id}'.\n"
                f"Registered team_ids: {registered}\n"
                f"Add this team_id to the correct tenant JSON file in config/tenants/."
            )

        tenant_ctx = self._loader.get(tenant_id)
        logger.info(
            f"Tenant resolved: {tenant_id} "
            f"({tenant_ctx.get('display_name', 'unknown')}) "
            f"for team_id={team_id}"
        )
        return tenant_ctx

    def refresh(self) -> None:
        """
        Reload all tenant configs from disk and rebuild the lookup map.
        Call this if you add or update a tenant JSON file without restarting.
        """
        logger.info("Refreshing tenant resolver — reloading all configs")
        self._loader.reload_all()
        self._build_lookup_map()

    @property
    def registered_team_ids(self) -> list[str]:
        """Return all team_ids currently registered in the lookup map."""
        return list(self._team_id_map.keys())

    @property
    def registered_tenant_ids(self) -> list[str]:
        """Return all tenant_ids currently loaded."""
        return list(set(self._team_id_map.values()))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_lookup_map(self) -> None:
        """
        Iterate all loaded tenant configs and populate self._team_id_map.
        Keyed by ad_tenant_id — the Azure AD / Teams tenant ID present in
        every inbound Teams activity as channel_data["tenant"]["id"].
        Called once at startup and again on refresh().
        """
        self._team_id_map.clear()
        all_tenants = self._loader.get_all()

        for config in all_tenants:
            tenant_id    = config.get("tenant_id")
            ad_tenant_id = config.get("ad_tenant_id")

            if not ad_tenant_id:
                logger.warning(
                    f"Tenant '{tenant_id}' has no ad_tenant_id — "
                    f"it will not be resolvable from inbound messages."
                )
                continue

            if ad_tenant_id in self._team_id_map:
                existing = self._team_id_map[ad_tenant_id]
                raise TenantResolverError(
                    f"Duplicate ad_tenant_id '{ad_tenant_id}' found in both "
                    f"'{existing}' and '{tenant_id}'. "
                    f"Each tenant must have a unique ad_tenant_id."
                )

            self._team_id_map[ad_tenant_id] = tenant_id

        logger.info(
            f"Tenant lookup map built: {len(self._team_id_map)} tenant(s) "
            f"across {len(all_tenants)} configs."
        )

    def _extract_team_id(self, turn_context: TurnContext) -> str:
        """
        Extract the team/workspace identifier from a TurnContext activity.

        Teams:  activity.channel_data["team"]["id"]
        Slack:  activity.channel_data["SlackMessage"]["event"]["team"]
        Direct: falls back to activity.conversation.id for 1:1 bot chats

        Args:
            turn_context: Bot Framework TurnContext.

        Returns:
            team_id string.

        Raises:
            TenantResolverError: if no usable identifier can be extracted.
        """
        activity = turn_context.activity
        channel_id = getattr(activity, "channel_id", "").lower()
        channel_data = getattr(activity, "channel_data", {}) or {}

        # ── Microsoft Teams ──────────────────────────────────────────────
        if channel_id == "msteams":
            # Use the Azure AD tenant ID — present in ALL Teams activities
            # (group messages, DMs, card submits). Stable and org-unique.
            tenant = channel_data.get("tenant") or {}
            if tenant.get("id"):
                return tenant["id"]

            # Fallback: group message has a team object
            team = channel_data.get("team", {})
            if team and team.get("id"):
                return team["id"]

            conversation = getattr(activity, "conversation", None)
            if conversation and getattr(conversation, "id", None):
                return conversation.id

        # ── Slack ────────────────────────────────────────────────────────
        elif channel_id == "slack":
            slack_msg = channel_data.get("SlackMessage", {})
            event = slack_msg.get("event", {})
            if event.get("team"):
                return event["team"]

            # Some Slack payloads put it at the top level
            if channel_data.get("team_id"):
                return channel_data["team_id"]

        # ── Generic fallback (Web chat, Emulator, etc.) ──────────────────
        else:
            # For the Bot Framework Emulator and web channel during dev,
            # use the conversation ID so you can test with a hardcoded mapping
            conversation = getattr(activity, "conversation", None)
            if conversation and getattr(conversation, "id", None):
                logger.debug(
                    f"Channel '{channel_id}' — using conversation.id as team_id"
                )
                return conversation.id

        raise TenantResolverError(
            f"Could not extract a team_id from activity. "
            f"channel_id='{channel_id}', "
            f"channel_data keys={list(channel_data.keys())}"
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
resolver = TenantResolver()