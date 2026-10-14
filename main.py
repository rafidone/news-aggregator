"""Automated Bengali news aggregator.

Fetches headlines from Bengali RSS feeds, asks Gemini to pick and summarize the
top 5 stories in Bengali, then delivers the digest over Telegram.

Run manually:  python main.py
"""

import logging
import os
import sys
import time

import feedparser
import requests
from dotenv import load_dotenv
from google import genai

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Steps
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
        except Exception as exc:  # feedparser is usually lenient, but be safe
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


def _build_prompt(articles):
    """Build the Bengali summarization prompt from fetched articles."""
    lines = [
        "নিচে বাংলা সংবাদ সাইট থেকে সংগৃহীত সর্বশেষ শিরোনামগুলোর একটি তালিকা দেওয়া হলো।",
        f"এগুলো থেকে সবচেয়ে গুরুত্বপূর্ণ {TOP_N}টি সংবাদ নির্বাচন করুন এবং বাংলায় একটি সংক্ষিপ্ত সারসংক্ষেপ তৈরি করুন।",
        "",
        "আউটপুট অবশ্যই নিম্নলিখিত ফরম্যাটে বাংলায় হতে হবে:",
        f"- প্রতিটি সংবাদের জন্য: একটি শিরোনাম, ২-৩টি বুলেট পয়েন্টে সারসংক্ষেপ, এবং মূল সংবাদের লিংক।",
        "- গুরুত্ব অনুসারে নিউজগুলো সাজান।",
        "- কোনো ভূমিকা বা অতিরিক্ত ব্যাখ্যা লিখবেন না, শুধু ডাইজেস্ট দিন।",
        "",
        "সংবাদ তালিকা:",
    ]
    for i, art in enumerate(articles, 1):
        lines.append(
            f"{i}. শিরোনাম: {art['title']}\n"
            f"   সারসংক্ষেপ: {art['summary'][:400]}\n"
            f"   সূত্র: {art['source']}\n"
            f"   লিংক: {art['link']}"
        )
    return "\n".join(lines)


def _model_candidates():
    """Ordered, de-duplicated list of models to try (primary first)."""
    models = [GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]
    seen = []
    for m in models:
        if m and m not in seen:
            seen.append(m)
    return seen


def summarize_news(articles, retries=3):
    """Ask Gemini to select and summarize the top news items in Bengali."""
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
                    return text
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


def _split_message(text, limit=TELEGRAM_MESSAGE_LIMIT):
    """Split long text into chunks that fit Telegram's message limit."""
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


def send_telegram(text, token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID, retries=3):
    """Send the digest to the configured Telegram chat, splitting if needed."""
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    for chunk in _split_message(text):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        for attempt in range(1, retries + 1):
            try:
                resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    break
                log.error(
                    "Telegram HTTP %s: %s", resp.status_code, resp.text[:300]
                )
            except requests.RequestException as exc:
                log.warning("Telegram send failed (attempt %d): %s", attempt, exc)
            time.sleep(2 * attempt)
        else:
            raise RuntimeError("Failed to deliver message to Telegram.")

    log.info("Digest delivered to Telegram chat %s", chat_id)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    try:
        articles = fetch_news()
        if not articles:
            raise RuntimeError("No news articles could be fetched.")
        digest = summarize_news(articles)
        send_telegram(digest)
        log.info("Done.")
    except Exception as exc:
        log.error("Run failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
