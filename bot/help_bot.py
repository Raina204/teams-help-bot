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
    """
    Main bot class. Inherits from ActivityHandler which handles the
    low-level Teams protocol. We override two methods:
    - on_message_activity: fires when a user sends any message or clicks a card button
    - on_members_added_activity: fires when the bot is first installed or a user joins
    """

    def __init__(self, conversation_state: ConversationState, user_state: UserState):
        self.conversation_state = conversation_state
        self.user_state = user_state
        # Creates a storage slot for conversation-level data (e.g. pending diagnostics)
        self.conversation_data_accessor = conversation_state.create_property("ConversationData")

    async def on_message_activity(self, turn_context: TurnContext):
        """Called every time a user sends a message or clicks an Adaptive Card button."""
        # Load existing conversation data (or start with empty dict)
        conversation_data = await self.conversation_data_accessor.get(turn_context, {})

        # Pass to the main dialog router which handles all intent logic
        await handle_turn(turn_context, conversation_data)

        # Save any changes made to conversation state during this turn
        await self.conversation_state.save_changes(turn_context)
        await self.user_state.save_changes(turn_context)

    async def on_members_added_activity(
        self, members_added: list[ChannelAccount], turn_context: TurnContext
    ):
        """
        Called when the bot is installed or a new user is added to a conversation.
        We send a welcome card to greet the user automatically.
        """
        from cards.welcome_card import get_welcome_card

        for member in members_added:
            # Skip the bot itself — only greet real users
            if member.id != turn_context.activity.recipient.id:
                name = (member.name or "").split()[0]
                card = CardFactory.adaptive_card(get_welcome_card(name))
                await turn_context.send_activity(MessageFactory.attachment(card))