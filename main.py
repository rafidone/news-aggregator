"""Automated Bengali news aggregator.

Fetches headlines from Bengali RSS feeds, asks Gemini to pick and summarize the
top 5 stories in Bengali, then delivers each story over Telegram with an inline
keyboard ("Read more" + "Save to favorites") and a persistent navigation menu.

Run one-shot digest:   python main.py
Run the interactive bot: python bot.py
"""

import json
import logging
import os
import re
import sys
import time

import feedparser
import requests
from dotenv import load_dotenv
from google import genai

import db

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACK_MODELS = [
    m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "").split(",") if m.strip()
]
GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "120"))

RSS_FEEDS = [
    "https://www.prothomalo.com/feed",
    "https://bangla.thedailystar.net/rss.xml",
    "https://www.banglanews24.com/rss.xml",
    "https://samakal.com/rss",
]

MAX_ENTRIES_PER_FEED = int(os.getenv("MAX_ENTRIES_PER_FEED", "15"))
TOP_N = int(os.getenv("TOP_N", "5"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
TELEGRAM_MESSAGE_LIMIT = 4096

# Persistent reply-keyboard menu labels (also used as message filters in bot.py)
MENU_TODAY = "📅 আজকের খবর"
MENU_PREVIOUS = "📅 গতকালের খবর"
MENU_FAVORITES = "⭐ আমার ফেভারিট"
REPLY_KEYBOARD = {
    "keyboard": [
        [{"text": MENU_PREVIOUS}, {"text": MENU_FAVORITES}],
        [{"text": MENU_TODAY}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# RSS fetching
# --------------------------------------------------------------------------- #
def fetch_news(feeds=None, max_entries=MAX_ENTRIES_PER_FEED):
    """Fetch the latest entries from each RSS feed.

    Returns a list of dicts: {title, summary, link, source}.
    """
    feeds = feeds or RSS_FEEDS
    articles = []

    for url in feeds:
        try:
            log.info("Fetching feed: %s", url)
            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0 (NewsAggregator/1.0)"},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            log.error("Network error for %s: %s", url, exc)
            continue

        try:
            parsed = feedparser.parse(response.content)
        except Exception as exc:
            log.error("Parse error for %s: %s", url, exc)
            continue

        if getattr(parsed, "bozo", 0) and not parsed.entries:
            log.error("Malformed feed with no entries: %s", url)
            continue

        source = parsed.feed.get("title", url)
        for entry in parsed.entries[:max_entries]:
            articles.append(
                {
                    "title": entry.get("title", "").strip(),
                    "summary": entry.get("summary", "").strip(),
                    "link": entry.get("link", "").strip(),
                    "source": source,
                }
            )
        log.info("  -> %d entries from %s", len(parsed.entries[:max_entries]), source)

    log.info("Total articles fetched: %d", len(articles))
    return articles


# --------------------------------------------------------------------------- #
# Gemini summarization
# --------------------------------------------------------------------------- #
def _build_prompt(articles):
    lines = [
        "নিচে বাংলা সংবাদ সাইট থেকে সংগৃহীত সর্বশেষ শিরোনামগুলোর একটি তালিকা দেওয়া হলো।",
        f"এগুলো থেকে সবচেয়ে গুরুত্বপূর্ণ {TOP_N}টি সংবাদ নির্বাচন করুন।",
        "",
        "শুধুমাত্র একটি JSON array রিটার্ন করুন, কোনো অতিরিক্ত লেখা বা ব্যাখ্যা নয়।",
        "প্রতিটি element নিম্নলিখিত ফরম্যাটে হবে:",
        '{"index": <তালিকায় সংবাদের নম্বর>, "title": "<স্পষ্ট বাংলা শিরোনাম>", '
        '"summary": "<২-৩টি বাক্য/বুলেটের বাংলা সারসংক্ষেপ, প্রতিটি বুলেট নতুন লাইনে \'• \' দিয়ে শুরু>"}',
        "",
        "গুরুত্ব অনুসারে সংবাদগুলো সাজান। লিংক নিজে বানাবেন না।",
        "",
        "সংবাদ তালিকা:",
    ]
    for i, art in enumerate(articles, 1):
        lines.append(
            f"{i}. শিরোনাম: {art['title']}\n"
            f"   সারসংক্ষেপ: {art['summary'][:400]}\n"
            f"   সূত্র: {art['source']}"
        )
    return "\n".join(lines)


def _model_candidates():
    models = [GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]
    seen = []
    for m in models:
        if m and m not in seen:
            seen.append(m)
    return seen


def summarize_news(articles, retries=3):
    """Ask Gemini to select/summarize the top stories. Returns a list of items."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    if not articles:
        raise RuntimeError("No articles available to summarize.")

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = _build_prompt(articles)

    last_error = None
    for model_name in _model_candidates():
        for attempt in range(1, retries + 1):
            try:
                log.info(
                    "Requesting summary from %s (attempt %d)", model_name, attempt
                )
                response = client.interactions.create(
                    model=model_name,
                    input=prompt,
                    timeout=GEMINI_TIMEOUT,
                )
                text = (getattr(response, "output_text", "") or "").strip()
                if text:
                    return _parse_items(text, articles)
                last_error = "Empty response from Gemini."
            except Exception as exc:
                last_error = exc
                log.warning(
                    "Gemini call failed on %s (attempt %d): %s",
                    model_name,
                    attempt,
                    exc,
                )
            time.sleep(2 * attempt)

    raise RuntimeError(f"Gemini summarization failed: {last_error}")


def _strip_code_fence(text):
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_items(text, articles):
    """Parse Gemini's JSON into normalized items, mapping back to source URLs."""
    cleaned = _strip_code_fence(text)
    start, end = cleaned.find("["), cleaned.rfind("]")
    data = None
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            data = None

    items = []
    if isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            source_article = None
            try:
                idx = int(entry.get("index"))
                if 1 <= idx <= len(articles):
                    source_article = articles[idx - 1]
            except (TypeError, ValueError):
                pass
            title = (entry.get("title") or "").strip()
            summary = entry.get("summary")
            if isinstance(summary, list):
                summary = "\n".join(f"• {str(s).strip()}" for s in summary)
            summary = (summary or "").strip()
            items.append(
                {
                    "title": title or (source_article or {}).get("title", ""),
                    "summary": summary,
                    "url": (source_article or {}).get("link", ""),
                    "source": (source_article or {}).get("source", ""),
                }
            )

    if not items:
        # Fallback: keep the raw model text as a single item.
        items = [
            {
                "title": "আজকের নির্বাচিত খবর",
                "summary": text.strip(),
                "url": "",
                "source": "",
            }
        ]
    return items[:TOP_N]


def run_digest(chat_id=TELEGRAM_CHAT_ID):
    """Fetch, summarize, store and deliver today's digest."""
    articles = fetch_news()
    if not articles:
        raise RuntimeError("No news articles could be fetched.")
    items = summarize_news(articles)
    send_digest(chat_id, items)
    return items


# --------------------------------------------------------------------------- #
# Telegram delivery
# --------------------------------------------------------------------------- #
def _telegram(method, payload, token=TELEGRAM_BOT_TOKEN, retries=3):
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set.")
    url = f"https://api.telegram.org/bot{token}/{method}"
    last = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
            last = f"HTTP {resp.status_code}: {resp.text[:300]}"
            log.error("Telegram %s failed: %s", method, last)
        except requests.RequestException as exc:
            last = exc
            log.warning("Telegram %s error (attempt %d): %s", method, attempt, exc)
        time.sleep(2 * attempt)
    raise RuntimeError(f"Telegram {method} failed: {last}")


def send_message(chat_id, text, reply_markup=None, token=TELEGRAM_BOT_TOKEN):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _telegram("sendMessage", payload, token=token)


def send_reply_keyboard(chat_id, token=TELEGRAM_BOT_TOKEN):
    return send_message(
        chat_id,
        "নিচের মেনু থেকে আজকের বা গতকালের খবর এবং আপনার ফেভারিট দেখতে পারেন।",
        reply_markup=REPLY_KEYBOARD,
        token=token,
    )


def _split_message(text, limit=TELEGRAM_MESSAGE_LIMIT):
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


def build_item_keyboard(article_id, url, saved=False, favorite_id=None):
    """Build the inline keyboard for a news item.

    The second button toggles between "save" and "remove". When a
    ``favorite_id`` is known (messages in the favorites list), removal targets
    that favorites row directly; otherwise removal targets the article id.
    """
    rows = []
    if url:
        rows.append([{"text": "📖 মূল সংবাদ পড়ুন", "url": url}])

    if favorite_id is not None:
        rows.append(
            [
                {
                    "text": "❌ ফেভারিট সরান",
                    "callback_data": f"unfav:f:{favorite_id}",
                }
            ]
        )
    elif article_id is not None:
        if saved:
            rows.append(
                [
                    {
                        "text": "❌ ফেভারিট সরান",
                        "callback_data": f"unfav:a:{article_id}",
                    }
                ]
            )
        else:
            rows.append(
                [
                    {
                        "text": "⭐ ফেভারিট করুন",
                        "callback_data": f"fav:{article_id}",
                    }
                ]
            )

    return {"inline_keyboard": rows}


def mark_saved_items(items, user_id):
    """Set ``item['saved']`` for items already favorited by the user."""
    favorites = db.list_favorites(user_id)
    saved_urls = {f["url"] for f in favorites if f.get("url")}
    saved_titles = {f["title"] for f in favorites if not f.get("url")}
    for item in items:
        if item.get("url"):
            item["saved"] = item["url"] in saved_urls
        else:
            item["saved"] = item.get("title", "") in saved_titles
    return items


def format_item(index, item):
    parts = [f"{index}. {item.get('title', '').strip()}"]
    summary = item.get("summary", "").strip()
    if summary:
        parts.append(summary)
    if item.get("source"):
        parts.append(f"সূত্র: {item['source']}")
    return "\n".join(parts)


def send_items(
    chat_id,
    items,
    header=None,
    token=TELEGRAM_BOT_TOKEN,
    show_save=True,
    show_remove=False,
):
    """Send items with inline keyboards.

    ``show_save`` shows the save/remove toggle for regular news. ``show_remove``
    is used when re-sending the favorites list and always shows the remove
    button for each saved item.
    """
    if header:
        send_message(chat_id, header, token=token)
    for index, item in enumerate(items, 1):
        if show_remove:
            article_id = None
            favorite_id = item.get("favorite_id")
            saved = True
        elif show_save:
            article_id = item.get("id")
            favorite_id = None
            saved = bool(item.get("saved"))
        else:
            article_id = None
            favorite_id = None
            saved = False

        send_message(
            chat_id,
            format_item(index, item),
            reply_markup=build_item_keyboard(
                article_id,
                item.get("url"),
                saved=saved,
                favorite_id=favorite_id,
            ),
            token=token,
        )


def send_digest(chat_id=TELEGRAM_CHAT_ID, items=None, digest_date=None):
    """Persist and deliver a digest with buttons and the persistent menu."""
    if items is None:
        items = run_digest(chat_id)
    digest_date = digest_date or db.today_str()

    article_ids = db.save_digest(chat_id, digest_date, items)
    for item, article_id in zip(items, article_ids):
        item["id"] = article_id

    # On a repeated digest (for example after a retry) show already-saved
    # articles in their "remove" state when the chat id is also the user id.
    mark_saved_items(items, chat_id)

    send_items(
        chat_id,
        items,
        header=f"🗞️ আজকের নির্বাচিত খবর — {digest_date}\n"
        f"সবচেয়ে গুরুত্বপূর্ণ {len(items)}টি সংবাদ:",
    )
    send_reply_keyboard(chat_id)
    log.info("Digest delivered to Telegram chat %s (%d items)", chat_id, len(items))
    return items


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main():
    try:
        db.init_db()
        run_digest()
        log.info("Done.")
    except Exception as exc:
        log.error("Run failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
