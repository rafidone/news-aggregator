# Bengali News Aggregator Bot

A Telegram bot that fetches the latest Bengali news, summarizes top stories with Google's Gemini AI, and delivers them in a clean, interactive format. It supports daily digests, history browsing, and personal favorites.

## Key Features

- **AI-Powered Summaries** – Automatically selects and summarizes the top news using Google Gemini with automatic fallback model support.
- **Interactive Inline Buttons** – Every article comes with "📖 মূল সংবাদ পড়ুন" (Read More) and a favorite toggle button.
- **Today's News** – Fetch or generate today's digest on-demand from the reply keyboard.
- **Yesterday's History** – Browse previously sent digests using "📅 গতকালের খবর".
- **Favorite Bookmarking** – Save articles with "⭐ ফেভারিট করুন" and manage them with "❌ ফেভারিট সরান".
- **Persistent Menu** – Easy navigation with a bottom reply keyboard.
- **Background Service** – Runs continuously via systemd for instant button responses.
- **Local Scheduling** – Automated daily digests with cron.

## Tech Stack

- **Python 3.12+**
- **[python-telegram-bot-style API](https://core.telegram.org/bots/api)** (using `requests` for direct Bot API calls)
- **[Google Gemini API](https://ai.google.dev/)** (`google-genai`)
- **SQLite** for digest history and favorites
- **[feedparser](https://feedparser.readthedocs.io/)** for RSS aggregation
- **[python-dotenv](https://pypi.org/project/python-dotenv/)** for configuration

## News Sources

- Prothom Alo
- The Daily Star (Bangla)
- Banglanews24.com
- Samakal

## Project Structure

```
news-aggregator/
├── bot.py        # Long-polling Telegram bot (handles buttons & menu)
├── main.py       # RSS fetching, Gemini summarization, digest delivery
├── db.py         # SQLite models for digests and favorites
├── deploy/
│   └── news-bot.service  # Systemd unit file
├── requirements.txt
├── .env.example
└── README.md
```

## Setup & Installation

### 1. Clone the Repository

```bash
git clone https://github.com/rafidone/news-aggregator.git
cd news-aggregator
```

### 2. Create a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your values:

| Variable | Description |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Your chat ID (can get from [@userinfobot](https://t.me/userinfobot)) |
| `GEMINI_API_KEY` | API key from [Google AI Studio](https://aistudio.google.com/apikey) |
| `GEMINI_MODEL` | Primary Gemini model (default: `gemini-3.5-flash`) |
| `GEMINI_FALLBACK_MODELS` | Comma-separated fallback models |
| `GEMINI_TIMEOUT` | Request timeout in seconds |

### 5. Run Locally

**Run the bot (for interactive buttons):**

```bash
python bot.py
```

**Send a one-time digest:**

```bash
python main.py
```

## Deployment

### Systemd Service (Recommended for the interactive bot)

1. Copy the service file:
   ```bash
   sudo cp deploy/news-bot.service /etc/systemd/system/news-bot.service
   ```

2. Reload and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now news-bot.service
   ```

3. Check status/logs:
   ```bash
   sudo systemctl status news-bot.service
   journalctl -u news-bot.service -f
   ```

### Cron Job (For automated daily digests)

Add to your crontab (`crontab -e`) to send digests at 10:00 AM Asia/Dhaka:

```cron
0 10 * * * cd /path/to/news-aggregator && /path/to/news-aggregator/.venv/bin/python main.py >> cron.log 2>&1
```

## Usage

Once the bot is running, open your Telegram chat with it and use the bottom menu:

- **📅 আজকের খবর** – View or generate today's digest
- **📅 গতকালের খবর** – Browse yesterday's (or most recent past) digest
- **⭐ আমার ফেভারিট** – View your saved articles

Tap **⭐ ফেভারিট করুন** on any article to save it, or **❌ ফেভারিট সরান** to remove it from favorites.

## Security Notes

- All secrets are loaded from environment variables via `.env`. The `.env` file is gitignored.
- Never commit API tokens, bot tokens, or chat IDs.
- Use `.env.example` as a template with placeholder values.

## License

This project is open source. Feel free to use and modify it as needed.
