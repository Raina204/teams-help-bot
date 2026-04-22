from botbuilder.core import (
    ActivityHandler,
    TurnContext,
    ConversationState,
    UserState,
    CardFactory,
    MessageFactory
)
from botbuilder.schema import ChannelAccount
from dialogs.main_dialog import handle_turn


class HelpBot(ActivityHandler):

    def __init__(self, conversation_state: ConversationState, user_state: UserState):
        self.conversation_state = conversation_state
        self.user_state = user_state
        self.conversation_data_accessor = conversation_state.create_property("ConversationData")

    async def on_message_activity(self, turn_context: TurnContext):
        """Called every time a user sends a message or clicks an Adaptive Card button."""
        conversation_data = await self.conversation_data_accessor.get(turn_context, {})

        await handle_turn(turn_context, conversation_data)

        await self.conversation_state.save_changes(turn_context)
        await self.user_state.save_changes(turn_context)

    async def on_members_added_activity(
        self, members_added: list[ChannelAccount], turn_context: TurnContext
    ):
        """Send a welcome card when the bot is first installed."""
        from cards.welcome_card import get_welcome_card

        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                name = (member.name or "").split()[0]
                card = CardFactory.adaptive_card(get_welcome_card(name))
                await turn_context.send_activity(MessageFactory.attachment(card))
