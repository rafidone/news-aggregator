"""Interactive Telegram bot for the Bengali news aggregator.

Runs a continuous long-polling loop (``getUpdates``) so that button clicks are
processed instantly:

* inline "⭐ Save Favorite" callback buttons on each news item are saved to the
  user's favorites (keyed by their Telegram user id) and acknowledged;
* the persistent reply keyboard provides "📅 Today's News", "📅 Yesterday's News"
  and "⭐ My Favorites".

The one-shot digest (``main.py``) can keep running from cron / GitHub Actions;
this worker just listens for user interactions.

Run:  python bot.py
"""

import os
import re
import signal
import sys
import threading

import requests

import db
import main

log = main.log

try:
    TOKEN = main.TELEGRAM_BOT_TOKEN
except AttributeError:  # pragma: no cover - defensive
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

MENU_TODAY = main.MENU_TODAY
MENU_PREVIOUS = main.MENU_PREVIOUS
MENU_FAVORITES = main.MENU_FAVORITES
REPLY_KEYBOARD = main.REPLY_KEYBOARD

FAVORITE_PREFIX = "fav:"
UNFAVORITE_PREFIX = "unfav:"
LONG_POLL_TIMEOUT = int(os.getenv("LONG_POLL_TIMEOUT", "25"))
POLL_REQUEST_TIMEOUT = int(os.getenv("POLL_REQUEST_TIMEOUT", str(LONG_POLL_TIMEOUT + 15)))

WELCOME_TEXT = (
    "🗞️ Welcome to the Bengali News Aggregator!\n\n"
    "Use the menu below:\n"
    f"• {MENU_TODAY} — View today's news\n"
    f"• {MENU_PREVIOUS} — View yesterday's news\n"
    f"• {MENU_FAVORITES} — View your saved favorites\n\n"
    "Tap “⭐ Save Favorite” below any article to save it here."
)

TODAY_GENERATING_TEXT = (
    "⏳ Generating today's news. This may take a few minutes while Gemini "
    "summarizes the stories; you'll receive them shortly."
)
TODAY_BUSY_TEXT = "⏳ Today's news is already being generated. You'll receive it shortly."
TODAY_ERROR_TEXT = "⚠️ Failed to generate today's news. Please try again in a moment."

EMPTY_PREVIOUS_TEXT = "📭 No news found for yesterday. Check again after today's digest has been sent."
EMPTY_FAVORITES_TEXT = "⭐ You haven't saved any favorites yet. Tap “⭐ Save Favorite” on an article to add one."

_generating_chats = set()
_generating_lock = threading.Lock()

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
def _user_id(obj, fallback=None):
    """Return the Telegram user id, falling back to the chat id in private chats."""
    return (obj.get("from") or {}).get("id") or fallback


def _article_from_message(message):
    """Rebuild an article from the news message that owns the clicked button.

    This keeps the favorite button usable even when the message was sent by a
    different runner (for example the GitHub Actions workflow) whose SQLite ids
    do not exist in this bot's local database.
    """
    lines = (message.get("text") or "").strip().splitlines()
    title = ""
    source = ""
    summary_lines = []

    if lines:
        title = re.sub(r"^\d+\.\s*", "", lines[0]).strip()
        for line in lines[1:]:
            if line.startswith("সূত্র:"):
                source = line.split(":", 1)[1].strip()
            else:
                summary_lines.append(line)

    url = ""
    for row in ((message.get("reply_markup") or {}).get("inline_keyboard") or []):
        for button in row:
            if button.get("url"):
                url = button["url"]
                break
        if url:
            break

    return {
        "title": title,
        "summary": "\n".join(summary_lines).strip(),
        "url": url,
        "source": source,
    }


def _resolve_article(article_id, message):
    """Look up an article locally, falling back to the message contents.

    A callback id can belong to an article from another database copy, so only
    trust the local row when the message's URL/title agree with it.
    """
    article = db.get_article(article_id)
    from_message = _article_from_message(message)

    if not article:
        return from_message

    message_url = from_message.get("url", "")
    article_url = article.get("url", "")
    if message_url and article_url and message_url != article_url:
        return from_message

    message_title = from_message.get("title", "")
    article_title = article.get("title", "")
    if message_title and article_title:
        if message_title not in article_title and article_title not in message_title:
            return from_message

    return article


def _parse_callback_target(data, prefix):
    """Parse ``<prefix><id>``, ``<prefix>a:<id>`` or ``<prefix>f:<id>``."""
    rest = data[len(prefix) :].strip()
    kind = "article"
    if rest.startswith("f:"):
        kind = "favorite"
        rest = rest[2:]
    elif rest.startswith("a:"):
        rest = rest[2:]
    try:
        return kind, int(rest)
    except ValueError:
        return None


def _send_today_digest(chat_id, user_id):
    """Resend today's stored digest from SQLite. Returns True if found."""
    digest = db.get_digest(chat_id, db.today_str())
    if not digest or not digest["items"]:
        return False

    main.mark_saved_items(digest["items"], user_id)
    main.send_items(
        chat_id,
        digest["items"],
        header=f"📅 Today's News — {digest['date']}:",
    )
    log.info(
        "Today's digest sent to chat=%s: date=%s items=%d",
        chat_id,
        digest["date"],
        len(digest["items"]),
    )
    return True


def _claim_generation(chat_id):
    with _generating_lock:
        if chat_id in _generating_chats:
            return False
        _generating_chats.add(chat_id)
        return True


def _release_generation(chat_id):
    with _generating_lock:
        _generating_chats.discard(chat_id)


def _generate_today_digest(chat_id, user_id):
    """Generate today's digest in the background and deliver it."""
    try:
        # Cron or another request may have populated the database meanwhile.
        if _send_today_digest(chat_id, user_id):
            return
        log.info("Generating today's digest on demand for chat=%s", chat_id)
        main.run_digest(chat_id)
    except Exception:
        log.exception("Failed to generate today's digest for chat=%s", chat_id)
        try:
            main.send_message(
                chat_id,
                TODAY_ERROR_TEXT,
                reply_markup=REPLY_KEYBOARD,
            )
        except Exception:
            log.exception("Failed to send digest error message to chat=%s", chat_id)
    finally:
        _release_generation(chat_id)


def handle_callback(callback):
    """Handle an inline keyboard button press."""
    data = callback.get("data", "")
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    user_id = _user_id(callback, chat_id)

    if data.startswith(FAVORITE_PREFIX):
        target = _parse_callback_target(data, FAVORITE_PREFIX)
        if not target:
            answer_callback(callback_id, "⚠️ Unknown request.")
            return
        _, article_id = target

        article = _resolve_article(article_id, message)
        if not article or not article.get("title"):
            answer_callback(callback_id, "⚠️ Article no longer available.")
            return

        if db.add_favorite(user_id, article):
            log.info("Favorite saved: user=%s article=%s", user_id, article_id)
            answer_callback(callback_id, "⭐ Saved to favorites.")
        else:
            log.info("Favorite already exists: user=%s article=%s", user_id, article_id)
            answer_callback(callback_id, "✅ Already in favorites.")

        favorite_id = db.get_favorite_id(user_id, article)
        if chat_id and message_id is not None:
            edit_markup(
                chat_id,
                message_id,
                main.build_item_keyboard(
                    article_id,
                    article.get("url"),
                    saved=True,
                    favorite_id=favorite_id,
                ),
            )
        return

    if data.startswith(UNFAVORITE_PREFIX):
        target = _parse_callback_target(data, UNFAVORITE_PREFIX)
        if not target:
            answer_callback(callback_id, "⚠️ Unknown request.")
            return
        kind, target_id = target

        if kind == "favorite":
            removed = db.remove_favorite_by_id(user_id, target_id)
            article = _article_from_message(message)
            log.info(
                "Favorite remove by row: user=%s favorite=%s removed=%s",
                user_id,
                target_id,
                removed,
            )
            if chat_id and message_id is not None:
                edit_markup(
                    chat_id,
                    message_id,
                    main.build_item_keyboard(None, article.get("url")),
                )
        else:
            article = _resolve_article(target_id, message)
            if not article or not article.get("title"):
                answer_callback(callback_id, "⚠️ Article no longer available.")
                return

            # Match the favorite by the article shown in the message. This is
            # safe even when the callback id came from another database copy.
            favorite_id = db.get_favorite_id(user_id, article)
            if favorite_id is not None:
                removed = db.remove_favorite_by_id(user_id, favorite_id)
            else:
                removed = False

            log.info(
                "Favorite remove by article: user=%s article=%s removed=%s",
                user_id,
                target_id,
                removed,
            )
            if chat_id and message_id is not None:
                edit_markup(
                    chat_id,
                    message_id,
                    main.build_item_keyboard(
                        target_id,
                        article.get("url"),
                        saved=False,
                    ),
                )

        if removed:
            answer_callback(callback_id, "❌ Removed from favorites.")
        else:
            answer_callback(callback_id, "ℹ️ Not in favorites.")
        return

    answer_callback(callback_id)


def handle_message(message):
    """Handle a plain text message / reply-keyboard press."""
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or not text:
        return
    user_id = _user_id(message, chat_id)

    if text in ("/start", "/help"):
        main.send_message(chat_id, WELCOME_TEXT, reply_markup=REPLY_KEYBOARD)
        return

    if text == MENU_TODAY:
        if _send_today_digest(chat_id, user_id):
            return
        if not _claim_generation(chat_id):
            main.send_message(chat_id, TODAY_BUSY_TEXT, reply_markup=REPLY_KEYBOARD)
            return
        main.send_message(chat_id, TODAY_GENERATING_TEXT, reply_markup=REPLY_KEYBOARD)
        threading.Thread(
            target=_generate_today_digest,
            args=(chat_id, user_id),
            name=f"digest-{chat_id}",
            daemon=True,
        ).start()
        return

    if text == MENU_PREVIOUS:
        digest = db.get_previous_digest(chat_id)
        if not digest or not digest["items"]:
            log.info("Previous digest requested by chat=%s: no history found", chat_id)
            main.send_message(chat_id, EMPTY_PREVIOUS_TEXT, reply_markup=REPLY_KEYBOARD)
            return
        log.info(
            "Previous digest sent to chat=%s: date=%s items=%d",
            chat_id,
            digest["date"],
            len(digest["items"]),
        )
        main.mark_saved_items(digest["items"], user_id)
        main.send_items(
            chat_id,
            digest["items"],
            header=f"📅 Yesterday's News — {digest['date']}:",
        )
        return

    if text == MENU_FAVORITES:
        favorites = db.list_favorites(user_id)
        if not favorites:
            log.info("Favorites requested by user=%s: none saved", user_id)
            main.send_message(chat_id, EMPTY_FAVORITES_TEXT, reply_markup=REPLY_KEYBOARD)
            return
        log.info("Favorites sent to user=%s: %d item(s)", user_id, len(favorites))
        main.send_items(
            chat_id,
            favorites,
            header=f"⭐ My Favorites ({len(favorites)}):",
            show_save=False,
            show_remove=True,
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
