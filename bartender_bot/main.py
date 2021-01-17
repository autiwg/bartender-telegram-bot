import logging
import re

import requests

from bartender_bot.config import settings
from telegram import (
    Update,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler,
    DispatcherHandlerStop,
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


def authorize_user(update: Update, context: CallbackContext):
    try:
        api_key = context.user_data["api_key"]
    except KeyError:
        api_key = receive_api_key(update.effective_chat.id)
    if api_key is None:
        update.message.reply_text(
            "Sorry, you are not logged in. Please use /authenticate to register/log in."
        )
        raise DispatcherHandlerStop
    return api_key


def authenticate(update: Update, context: CallbackContext) -> None:
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
            "You can now authenticate consuming unhealthy amounts of softdrinks, type /drink to get started."
            % update.effective_user.name
        )
        return ConversationHandler.END
    update.message.reply_text("Your provided invite token is invalid.")
    return ConversationHandler.END


def invite(update: Update, context: CallbackContext):
    api_key = authorize_user(update, context)
    res = requests.post(
        "%s/api/v1/invite/" % settings.api_host,
        headers={"Authorization": "Token %s" % api_key},
    )
    if res.status_code == 403:
        logger.info(
            "User %s attempted to generate an invite but is unauthorized"
            % update.effective_user.name
        )
        update.message.reply_text("Sorry, you are not authorized to add other users.")
    elif res.ok:
        invite_token = res.json().get("token")
        logger.info(
            "User %s generated invite code %s"
            % (update.effective_user.name, invite_token)
        )
        if invite_token is None:
            update.message.reply_text(
                "Something went wrong while attempting to create a new invite token."
            )
            return
        update.message.reply_markdown(
            "Here is the freshly generated invite token: `%s`" % invite_token
        )
    else:
        update.message.reply_text(
            "Something weird happened while attempting to get a new invite token, status code: %s"
            % res.status_code
        )


def cancel(update: Update, context: CallbackContext) -> int:
    update.message.reply_text(
        "Okay, we have canceled the registration process."
        "Type /register when you receive an invite token.",
        reply_markup=ReplyKeyboardRemove(),
    )

    return ConversationHandler.END


def drink(update: Update, context: CallbackContext):
    api_key = authorize_user(update, context)

    res = requests.get(
        "%s/api/v1/crate/?billed=false" % settings.api_host,
        headers={"Authorization": "Token %s" % api_key},
    )

    if not res.ok:
        update.message.reply_text(
            "Something weird happened whilst attempting to fetch crates"
        )
        return

    keyboard = InlineKeyboardMarkup.from_column(
        [
            InlineKeyboardButton(
                obj.get("name"), callback_data="transaction:new:%s" % obj.get("id")
            )
            for obj in res.json()
        ]
    )

    update.message.reply_text("Sure, what can I get you?", reply_markup=keyboard)


def get_transaction_keyboard(transaction_id):
    return InlineKeyboardMarkup.from_column(
        [
            InlineKeyboardButton(text, callback_data=data)
            for text, data in (
                ("Delete", "transaction:delete:%s" % transaction_id),
                (
                    "Add another bottle",
                    "transaction:increment:%s" % transaction_id,
                ),
            )
        ]
    )


def new_transaction_handler(update: Update, context: CallbackContext) -> None:
    crate_id = update.callback_query.data.split(":")[-1]
    api_key = authorize_user(update, context)

    res = requests.post(
        "%s/api/v1/transaction/" % settings.api_host,
        json={"amount": 1, "crate": crate_id},
        headers={"Authorization": "Token %s" % api_key},
    )
    update.callback_query.answer()

    if not res.ok:
        update.callback_query.edit_message_text(
            "Failed to create transaction, got error code: %s" % res.status_code
        )
        return

    transaction = res.json()

    keyboard = get_transaction_keyboard(transaction.get("id"))
    logger.info(
        "User %s bought 1 %s (%s) "
        % (
            update.effective_user.name,
            transaction.get("crate_name"),
            transaction.get("id"),
        )
    )
    update.callback_query.edit_message_text(
        "Okay, I've added 1 %s for %s €."
        % (transaction.get("crate_name"), transaction.get("amount_total")),
    )
    update.callback_query.edit_message_reply_markup(keyboard)


def delete_transaction_handler(update: Update, context: CallbackContext) -> None:
    transaction_id = update.callback_query.data.split(":")[-1]

    api_key = authorize_user(update, context)

    res = requests.delete(
        "%s/api/v1/transaction/%s/" % (settings.api_host, transaction_id),
        headers={"Authorization": "Token %s" % api_key},
    )

    update.callback_query.answer()
    if not res.ok:
        update.callback_query.edit_message_text(
            "Failed to delete transaction, got error code: %s" % res.status_code
        )
    else:
        logger.info("User %s deleted their transaction" % (update.effective_user.name,))
        update.callback_query.edit_message_text("Successfully deleted transaction.")


def increment_transaction_handler(update: Update, context: CallbackContext) -> None:
    transaction_id = update.callback_query.data.split(":")[-1]

    api_key = authorize_user(update, context)

    res = requests.post(
        "%s/api/v1/transaction/%s/increment/" % (settings.api_host, transaction_id),
        headers={"Authorization": "Token %s" % api_key},
    )

    update.callback_query.answer()
    transaction = res.json()
    keyboard = get_transaction_keyboard(transaction.get("id"))

    if not res.ok:
        update.callback_query.edit_message_text(
            "Failed to add a drink to the transaction, got error code: %s"
            % res.status_code
        )
    else:
        logger.info(
            "User %s incremented the transaction of 1 %s (%s) "
            % (
                update.effective_user.name,
                transaction.get("crate_name"),
                transaction.get("id"),
            )
        )
        update.callback_query.edit_message_text(
            "Okay, you drank %d bottles of %s for %s €."
            % (
                transaction.get("amount"),
                transaction.get("crate_name"),
                transaction.get("amount_total"),
            ),
            reply_markup=keyboard,
        )


def main():
    """Start the bot."""
    updater = Updater(settings.telegram_token, use_context=True)

    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler(("start", "authenticate"), authenticate))
    dispatcher.add_handler(CommandHandler("invite", invite))
    dispatcher.add_handler(CommandHandler("drink", drink))

    dispatcher.add_handler(
        CallbackQueryHandler(
            new_transaction_handler, pattern=r"^transaction:new:[a-f0-9-]{36}$"
        )
    )
    dispatcher.add_handler(
        CallbackQueryHandler(
            delete_transaction_handler, pattern=r"^transaction:delete:[a-f0-9-]{36}$"
        )
    )
    dispatcher.add_handler(
        CallbackQueryHandler(
            increment_transaction_handler,
            pattern=r"^transaction:increment:[a-f0-9-]{36}$",
        )
    )

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
