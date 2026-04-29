import logging

from botbuilder.core import (
    ActivityHandler,
    TurnContext,
    ConversationState,
    UserState,
    CardFactory,
    MessageFactory,
)
from botbuilder.schema import ChannelAccount

from dialogs.main_dialog import handle_turn
from config import log_denied, ActionNotAllowedError

logger = logging.getLogger(__name__)


class HelpBot(ActivityHandler):

    def __init__(
        self,
        conversation_state: ConversationState,
        user_state: UserState,
    ):
        self.conversation_state = conversation_state
        self.user_state = user_state
        self.conversation_data_accessor = conversation_state.create_property(
            "ConversationData"
        )

    # ── Main turn entry point ─────────────────────────────────────────────────

    async def on_turn(self, turn_context: TurnContext, tenant_ctx: dict):
        """
        Override on_turn (not on_message_activity) so tenant_ctx
        is available for ALL activity types — messages, members added,
        card submits, etc.

        Called by tenant_aware_turn() in app.py after the resolver
        and rate limiter have already run successfully.

        Args:
            turn_context: Bot Framework TurnContext for this message.
            tenant_ctx:   Resolved tenant config dict. Contains all
                          scoping IDs, allowed_actions, and secret refs
                          for this specific client. Never None here —
                          app.py guarantees it before calling us.
        """
        # Attach tenant_ctx to turn_context so dialogs can read it
        # without needing it passed as a function argument everywhere.
        # Access it anywhere downstream with:
        #   tenant_ctx = turn_context.turn_state.get("tenant_ctx")
        turn_context.turn_state["tenant_ctx"] = tenant_ctx

        logger.debug(
            f"HelpBot.on_turn — "
            f"tenant={tenant_ctx['tenant_id']} "
            f"activity_type={turn_context.activity.type}"
        )

        # Delegate to the standard ActivityHandler routing.
        # This calls on_message_activity, on_members_added_activity, etc.
        await super().on_turn(turn_context)

        # Save state after every turn regardless of activity type.
        await self.conversation_state.save_changes(turn_context)
        await self.user_state.save_changes(turn_context)

    # ── Message handler ───────────────────────────────────────────────────────

    async def on_message_activity(self, turn_context: TurnContext):
        """
        Called every time a user sends a message or clicks an Adaptive Card button.

        tenant_ctx is retrieved from turn_state (set in on_turn above)
        and passed into handle_turn so every dialog and service call
        is scoped to this tenant automatically.
        """
        tenant_ctx = turn_context.turn_state.get("tenant_ctx")
        conversation_data = await self.conversation_data_accessor.get(
            turn_context, {}
        )

        # Extract user identity for audit logging.
        # from_property is the Teams user object on the activity.
        user = getattr(turn_context.activity.from_property, "name", "unknown")

        logger.info(
            f"Message received — "
            f"tenant={tenant_ctx['tenant_id']} "
            f"user={user}"
        )

        try:
            # handle_turn now receives tenant_ctx so all downstream
            # service calls (ConnectWise Manage, ConnectWise Automate, printer, timezone)
            # use this tenant's scoped credentials and site IDs.
            await handle_turn(turn_context, conversation_data, tenant_ctx)

        except ActionNotAllowedError as exc:
            # Catch RBAC denials that bubble up from dialogs.
            # log_denied records the blocked action with tenant + user identity.
            log_denied(tenant_ctx, user=user, action=exc.action)
            await turn_context.send_activity(
                "Sorry, that action isn't available for your organisation. "
                "Please contact your IT administrator if you think this is wrong."
            )

        except Exception as exc:
            logger.error(
                f"Error in handle_turn — "
                f"tenant={tenant_ctx['tenant_id']} "
                f"user={user} "
                f"error={exc}",
                exc_info=True,
            )
            await turn_context.send_activity(
                "Something went wrong. Please try again in a moment."
            )

    # ── Welcome handler ───────────────────────────────────────────────────────

    async def on_members_added_activity(
        self,
        members_added: list[ChannelAccount],
        turn_context: TurnContext,
    ):
        """
        Send a personalised welcome card when the bot is first installed
        in a workspace, or when a new member is added to the conversation.

        tenant_ctx is available here too — use it if you want to
        customise the welcome card per client (e.g. show their company name).
        """
        from cards.welcome_card import get_welcome_card

        tenant_ctx = turn_context.turn_state.get("tenant_ctx")

        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                first_name = (member.name or "").split()[0]

                logger.info(
                    f"New member — "
                    f"tenant={tenant_ctx['tenant_id'] if tenant_ctx else 'unknown'} "
                    f"user={first_name}"
                )

                card = CardFactory.adaptive_card(
                    get_welcome_card(first_name)
                )
                await turn_context.send_activity(
                    MessageFactory.attachment(card)
                )