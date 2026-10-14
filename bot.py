"""Interactive Telegram bot for the Bengali news aggregator.

Runs a continuous long-polling loop (``getUpdates``) so that button clicks are
processed instantly:

* inline "⭐ ফেভারিট করুন" callback buttons on each news item are saved to the
  user's favorites (keyed by their Telegram user id) and acknowledged;
* the persistent reply keyboard provides "📅 গতকালের খবর" and "⭐ আমার ফেভারিট".

The one-shot digest (``main.py``) can keep running from cron / GitHub Actions;
this worker just listens for user interactions.

Run:  python bot.py
"""

import os
import signal
import sys

import requests

import db
import main

log = main.log

try:
    TOKEN = main.TELEGRAM_BOT_TOKEN
except AttributeError:  # pragma: no cover - defensive
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

MENU_PREVIOUS = main.MENU_PREVIOUS
MENU_FAVORITES = main.MENU_FAVORITES
REPLY_KEYBOARD = main.REPLY_KEYBOARD

FAVORITE_PREFIX = "fav:"
LONG_POLL_TIMEOUT = int(os.getenv("LONG_POLL_TIMEOUT", "25"))
POLL_REQUEST_TIMEOUT = int(os.getenv("POLL_REQUEST_TIMEOUT", str(LONG_POLL_TIMEOUT + 15)))

WELCOME_TEXT = (
    "🗞️ বাংলা সংবাদ সংগ্রাহকে স্বাগতম!\n\n"
    "নিচের মেনু ব্যবহার করে আপনি:\n"
    f"• {MENU_PREVIOUS} — গতকালের সংবাদ দেখতে পারবেন\n"
    f"• {MENU_FAVORITES} — আপনার সংরক্ষিত সংবাদ দেখতে পারবেন\n\n"
    "যেকোনো সংবাদের নিচে “⭐ ফেভারিট করুন” চাপলে সেটি এখানে সংরক্ষিত হবে।"
)

EMPTY_PREVIOUS_TEXT = "📭 গতকালের কোনো সংবাদ পাওয়া যায়নি। আজকের ডাইজেস্ট পাঠানোর পরে আবার দেখুন।"
EMPTY_FAVORITES_TEXT = "⭐ আপনি এখনো কোনো সংবাদ ফেভারিটে সংরক্ষণ করেননি।"

_running = True


# --------------------------------------------------------------------------- #
# Telegram API helpers
# --------------------------------------------------------------------------- #
def _api(method, payload=None, timeout=None):
    """Call a Telegram Bot API method and return the parsed JSON response."""
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set.")
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    resp = requests.post(
        url,
        json=payload or {},
        timeout=timeout or main.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        log.warning("Telegram %s returned not-ok: %s", method, data)
    return data


def get_updates(offset=None):
    """Long-poll for new updates. Returns the list of update objects."""
    payload = {
        "timeout": LONG_POLL_TIMEOUT,
        "allowed_updates": ["message", "callback_query"],
    }
    if offset is not None:
        payload["offset"] = offset
    try:
        data = _api("getUpdates", payload, timeout=POLL_REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        log.warning("getUpdates failed: %s", exc)
        return []
    return data.get("result", [])


def answer_callback(callback_id, text=None, show_alert=False):
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True
    try:
        _api("answerCallbackQuery", payload)
    except requests.RequestException as exc:
        log.warning("answerCallbackQuery failed: %s", exc)


def edit_markup(chat_id, message_id, reply_markup):
    try:
        _api(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup,
            },
        )
    except requests.RequestException as exc:
        log.warning("editMessageReplyMarkup failed: %s", exc)


# --------------------------------------------------------------------------- #
# Update handlers
# --------------------------------------------------------------------------- #
def handle_callback(callback):
    """Handle an inline keyboard button press."""
    data = callback.get("data", "")
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    user_id = (callback.get("from") or {}).get("id") or chat_id

    if not data.startswith(FAVORITE_PREFIX):
        answer_callback(callback_id)
        return

    try:
        article_id = int(data[len(FAVORITE_PREFIX) :])
    except ValueError:
        answer_callback(callback_id, "⚠️ অজানা রিকোয়েস্ট।")
        return

    article = db.get_article(article_id)
    if not article:
        answer_callback(callback_id, "⚠️ সংবাদটি আর পাওয়া যাচ্ছে না।")
        return

    if db.add_favorite(user_id, article):
        answer_callback(callback_id, "⭐ ফেভারিটে সংরক্ষণ করা হয়েছে।")
    else:
        answer_callback(callback_id, "✅ এটি আগেই ফেভারিটে আছে।")

    if chat_id and message_id is not None:
        edit_markup(
            chat_id,
            message_id,
            main.build_item_keyboard(article_id, article.get("url"), saved=True),
        )


def handle_message(message):
    """Handle a plain text message / reply-keyboard press."""
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or not text:
        return

    if text in ("/start", "/help"):
        main.send_message(chat_id, WELCOME_TEXT, reply_markup=REPLY_KEYBOARD)
        return

    if text == MENU_PREVIOUS:
        digest = db.get_previous_digest(chat_id)
        if not digest or not digest["items"]:
            main.send_message(chat_id, EMPTY_PREVIOUS_TEXT, reply_markup=REPLY_KEYBOARD)
            return
        main.send_items(
            chat_id,
            digest["items"],
            header=f"📅 {digest['date']} তারিখের নির্বাচিত খবর:",
        )
        return

    if text == MENU_FAVORITES:
        favorites = db.list_favorites(chat_id)
        if not favorites:
            main.send_message(chat_id, EMPTY_FAVORITES_TEXT, reply_markup=REPLY_KEYBOARD)
            return
        main.send_items(
            chat_id,
            favorites,
            header=f"⭐ আপনার সংরক্ষিত সংবাদ ({len(favorites)}টি):",
            show_save=False,
        )
        return

    # Unknown input: gently re-show the menu.
    main.send_message(chat_id, WELCOME_TEXT, reply_markup=REPLY_KEYBOARD)


# --------------------------------------------------------------------------- #
# Polling loop
# --------------------------------------------------------------------------- #
def _handle_stop(signum, _frame):
    global _running
    _running = False
    log.info("Shutdown signal received (%s); stopping bot...", signum)


def run():
    global _running
    if not TOKEN:
        log.error("TELEGRAM_BOT_TOKEN is not set; cannot start the bot.")
        sys.exit(1)

    db.init_db()
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    log.info("Bot started; polling for updates (long-poll %ss).", LONG_POLL_TIMEOUT)
    offset = None
    while _running:
        for update in get_updates(offset):
            offset = update["update_id"] + 1
            try:
                if "callback_query" in update:
                    handle_callback(update["callback_query"])
                elif "message" in update:
                    handle_message(update["message"])
            except Exception as exc:  # keep the loop alive on bad updates
                log.exception("Error handling update %s: %s", update.get("update_id"), exc)
    log.info("Bot stopped.")


if __name__ == "__main__":
    run()
