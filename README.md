# Bengali News Aggregator Telegram Bot | news-aggregator | telegram-bot | python | gemini-api

A smart, interactive **Bengali news aggregator** Telegram bot built with **Python**, **Telegram Bot API**, **Google Gemini API**, and **SQLite**. It fetches top Bengali headlines, summarizes them using AI, and delivers a clean, interactive news experience with favorites, history, and on-demand updates.

## Key Features

- **AI-Powered Bengali News Summaries** – Uses Google Gemini to curate and summarize the top stories in Bengali.
- **Interactive Inline Buttons** – Every article includes "📖 Read Article", "⭐ Save Favorite", and "❌ Remove Favorite".
- **Today's News On-Demand** – Instantly view or generate today's top news from the menu.
- **Yesterday's News History** – Browse previously sent digests anytime.
- **Favorites Management** – Save, view, and remove favorite articles with one tap.
- **Persistent Reply Menu** – Clean, English-language navigation at the bottom of the chat.
- **24/7 Background Bot** – Runs as a systemd service for instant responses.
- **Automated Daily Digest** – Schedule with cron to send fresh news every morning.
- **SQLite Storage** – Lightweight local database for history and per-user favorites.

## Tech Stack

- **[Python](https://www.python.org/)** – Core language
- **[Telegram Bot API](https://core.telegram.org/bots/api)** – Messaging and inline interactions
- **[Google Gemini API](https://ai.google.dev/)** – AI summarization via `google-genai`
- **[SQLite](https://www.sqlite.org/)** – Local storage
- **[feedparser](https://feedparser.readthedocs.io/)** – RSS feed aggregation
- **[requests](https://pypi.org/project/requests/)** – HTTP requests
- **[python-dotenv](https://pypi.org/project/python-dotenv/)** – Environment configuration

## News Sources

- [Prothom Alo](https://www.prothomalo.com/)
- [The Daily Star (Bangla)](https://bangla.thedailystar.net/)
- [Banglanews24.com](https://www.banglanews24.com/)
- [Samakal](https://samakal.com/)

## Project Structure

```text
news-aggregator/
├── bot.py        # Long-polling Telegram bot (menu, buttons, callbacks)
├── main.py       # RSS fetching, Gemini summarization, digest delivery
├── db.py         # SQLite schema and data access for digests & favorites
├── deploy/
│   └── news-bot.service  # systemd service unit
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

### 2. Create and Activate a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

```bash
cp .env.example .env
```

Update `.env` with your credentials:

| Variable | Required | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Yes | Default chat ID for digests |
| `GEMINI_API_KEY` | Yes | API key from [Google AI Studio](https://aistudio.google.com/apikey) |
| `GEMINI_MODEL` | No | Primary model (default: `gemini-3.5-flash`) |
| `GEMINI_FALLBACK_MODELS` | No | Comma-separated fallback models |
| `GEMINI_TIMEOUT` | No | Timeout in seconds (default: `120`) |

### 5. Run the Bot

**Start the interactive Telegram bot:**

```bash
python bot.py
```

**Send a one-time news digest:**

```bash
python main.py
```

## Deployment

### Run as a systemd Service

```bash
sudo cp deploy/news-bot.service /etc/systemd/system/news-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now news-bot.service
```

Monitor logs:

```bash
sudo systemctl status news-bot.service
journalctl -u news-bot.service -f
```

### Automate with Cron

Add this to `crontab -e` to send a daily digest at 10:00 AM Asia/Dhaka:

```cron
0 10 * * * cd /home/youruser/news-aggregator && /home/youruser/news-aggregator/.venv/bin/python main.py >> cron.log 2>&1
```

## How to Use

1. Start the bot and send `/start`.
2. Use the bottom menu:
   - **📅 Today's News** – View or generate today's Bengali news digest
   - **📅 Yesterday's News** – View the most recent previous digest
   - **⭐ My Favorites** – Access your saved articles
3. Tap **⭐ Save Favorite** on any article to bookmark it.
4. Tap **❌ Remove Favorite** to remove it from your favorites list.
5. Tap **📖 Read Article** to open the full story in your browser.

## Security

- All secrets are stored in `.env` and are excluded from version control via `.gitignore`.
- Only placeholder values are present in `.env.example`.
- Never commit tokens, API keys, or chat IDs.

## Keywords

`news-aggregator`, `telegram-bot`, `python`, `gemini-api`, `google-gemini`, `bengali-news`, `bangla-news`, `rss-aggregator`, `ai-news-summary`, `sqlite`, `news-bot`, `telegram-news-bot`

## License

This project is open-source. Feel free to fork, modify, and use it for your own purposes.
