import logging
import re

import requests

from bartender_bot.config import settings
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    ConversationHandler,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

logger = logging.getLogger(__name__)


def receive_api_key(telegram_id: int):
    res = requests.post(
        "%s/api/v1/token/" % settings.api_host, json={"telegram_id": telegram_id}
    )

    if not res.ok:
        return None
    return res.json()["token"]


def start(update: Update, context: CallbackContext) -> None:
    # Attempt to fetch the user's api_key
    api_key = receive_api_key(update.message.chat_id)
    greeting = "<b>Welcome, %s!\n</b>" % update.effective_user.name
    if api_key:
        context.user_data["api_key"] = api_key
        update.message.reply_html(greeting)
    else:
        update.message.reply_html(
            "%s\nYou do not seem to have an account with us yet. "
            "If you believe this is an error, contact %s.\n"
            "If you have received an invite code, use it by running /register."
            % (greeting, settings.admin_user)
        )


def register(update: Update, context: CallbackContext) -> int:
    logger.info("User %s started the registration flow" % update.effective_user.name)
    update.message.reply_text("Please reply with your invite token.")
    return 0


def register_submit_token(update: Update, context: CallbackContext) -> int:
    token = update.message.text.strip()
    chat_id = update.message.chat_id
    logger.info("User %s submitted token %s" % (update.effective_user.name, token))
    # Validate the token
    if not re.match(r"[a-f0-9]{8}", token):
        update.message.reply_text(
            "Your provided invite code does not follow a valid format."
        )
        return ConversationHandler.END
    res = requests.post(
        "%s/api/v1/user/accept_invite/" % settings.api_host,
        json={"telegram_id": chat_id, "invite": token},
    )
    if not res.ok:
        update.message.reply_text("Your provided token was rejected.")
        return ConversationHandler.END
    # Attempt to fetch a token
    api_key = receive_api_key(chat_id)
    if api_key:
        context.user_data["api_key"] = api_key
        logger.info("User %s successfully registered" % update.effective_user.name)
        update.message.reply_html(
            "<b>Welcome to the Auti WG, %s!</b>\n"
            "You can now start consuming unhealthy amounts of softdrinks, type /drink to get started."
            % update.effective_user.name
        )
        return ConversationHandler.END
    update.message.reply_text("Your provided invite token is invalid.")
    return ConversationHandler.END


def cancel(update: Update, context: CallbackContext) -> int:
    update.message.reply_text(
        "Okay, we have canceled the registration process."
        "Type /register when you receive an invite token.",
        reply_markup=ReplyKeyboardRemove(),
    )

    return ConversationHandler.END


def main():
    """Start the bot."""
    updater = Updater(settings.telegram_token, use_context=True)

    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))

    dispatcher.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("register", register)],
            states={
                0: [
                    MessageHandler(
                        Filters.text & ~Filters.command, register_submit_token
                    )
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    updater.start_polling()

    updater.idle()


if __name__ == "__main__":
    main()
