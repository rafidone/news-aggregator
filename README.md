<div align="center">

# 🗞️ Bengali News Aggregator Bot

**AI-powered Bengali news digests on Telegram — curated, summarized, and delivered automatically.**

[![Daily News Digest](https://github.com/rafidone/news-aggregator/actions/workflows/run_news.yml/badge.svg?branch=main)](https://github.com/rafidone/news-aggregator/actions/workflows/run_news.yml)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Google Gemini](https://img.shields.io/badge/AI-Google%20Gemini-8E75B2?logo=googlegemini&logoColor=white)](https://ai.google.dev/)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![SQLite](https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#license)

<br />

[Overview](#-overview) • [Features](#-features) • [Tech Stack](#-tech-stack) • [Quick Start](#-quick-start) • [Deployment](#-deployment) • [Security](#-security)

</div>

---

## 📌 Overview

**Bengali News Aggregator Bot** is a production-ready Telegram bot that collects top headlines from trusted Bengali news sources, uses **Google Gemini** to generate concise summaries, and delivers them with a clean interactive interface. Users can browse today's news, revisit yesterday's digest, and manage personal favorites — all from Telegram.

## ✨ Features

| Feature | Description |
| --- | --- |
| 🤖 **AI Summarization** | Curates and summarizes top Bengali stories using Google Gemini with fallback model support |
| 📅 **Today's News** | View or generate today's digest on-demand from the menu |
| 📅 **Yesterday's News** | Instantly access the most recent previous digest |
| ⭐ **Favorites** | Save, view, and remove favorite articles with one tap |
| 🔘 **Interactive Buttons** | Inline actions: **Read Article**, **Save Favorite**, **Remove Favorite** |
| ⌨️ **Persistent Menu** | Easy navigation with an always-available reply keyboard |
| ⏰ **Automated Delivery** | Daily digest via GitHub Actions (cloud) and/or local cron |
| 🖥️ **Background Service** | Runs 24/7 as a systemd service for instant callback responses |
| 💾 **Local Storage** | SQLite stores digest history and per-user favorites |

## 🧰 Tech Stack

- **Language:** Python 3.12+
- **Bot Platform:** Telegram Bot API
- **AI Engine:** Google Gemini (`google-genai`)
- **Database:** SQLite
- **Data Sources:** RSS feeds (Prothom Alo, The Daily Star Bangla, Banglanews24, Samakal)
- **Automation:** GitHub Actions, cron, systemd
- **Config:** `python-dotenv`

## 📰 News Sources

- [Prothom Alo](https://www.prothomalo.com/)
- [The Daily Star (Bangla)](https://bangla.thedailystar.net/)
- [Banglanews24.com](https://www.banglanews24.com/)
- [Samakal](https://samakal.com/)

## 📁 Project Structure

```text
news-aggregator/
├── .github/workflows/
│   └── run_news.yml      # Scheduled cloud digest (GitHub Actions)
├── deploy/
│   └── news-bot.service  # systemd unit for the interactive bot
├── bot.py                # Long-polling bot (menus, callbacks, favorites)
├── main.py               # RSS fetch, Gemini summary, digest delivery
├── db.py                 # SQLite schema & data access
├── requirements.txt
├── .env.example
└── README.md
```

## 🚀 Quick Start

### 1) Clone the repository

```bash
git clone https://github.com/rafidone/news-aggregator.git
cd news-aggregator
```

### 2) Set up a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows
```

### 3) Install dependencies

```bash
pip install -r requirements.txt
```

### 4) Configure environment variables

```bash
cp .env.example .env
```

Update `.env` with your values:

| Variable | Required | Description |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | ✅ | Default chat ID for scheduled digests |
| `GEMINI_API_KEY` | ✅ | API key from [Google AI Studio](https://aistudio.google.com/apikey) |
| `GEMINI_MODEL` | ❌ | Primary model (default: `gemini-3.5-flash`) |
| `GEMINI_FALLBACK_MODELS` | ❌ | Comma-separated fallback models |
| `GEMINI_TIMEOUT` | ❌ | Timeout in seconds (default: `120`) |

### 5) Run locally

```bash
# Interactive bot (buttons, menus, favorites)
python bot.py

# One-time digest
python main.py
```

## ⚙️ Deployment

### GitHub Actions (Cloud Scheduler)

The workflow runs daily at **10:00 AM Asia/Dhaka (04:00 UTC)** and sends the digest via GitHub's cloud runners — no local machine required.

**Required repository secrets:**
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GEMINI_API_KEY`

### systemd Service (Interactive Bot)

```bash
sudo cp deploy/news-bot.service /etc/systemd/system/news-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now news-bot.service
```

Check status/logs:

```bash
sudo systemctl status news-bot.service
journalctl -u news-bot.service -f
```

### cron (Local Daily Digest)

```cron
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
HOME=/home/youruser
0 10 * * * cd /home/youruser/news-aggregator && . /home/youruser/news-aggregator/.env && /home/youruser/news-aggregator/.venv/bin/python main.py >> /home/youruser/news-aggregator/cron.log 2>&1
```

## 📱 Usage

1. Start a chat with your bot and send `/start`.
2. Use the menu:
   - **📅 Today's News** – View or generate today's digest
   - **📅 Yesterday's News** – Browse the previous digest
   - **⭐ My Favorites** – View saved articles
3. Use inline buttons:
   - **📖 Read Article** – Open the full story
   - **⭐ Save Favorite** – Bookmark an article
   - **❌ Remove Favorite** – Remove from favorites

## 🔒 Security

- Secrets are stored in `.env` (gitignored) or GitHub Actions secrets.
- `.env.example` contains placeholders only — never commit real credentials.
- `.gitignore` excludes `.env`, local databases, logs, and virtual environments.

## 🏷️ Topics

`news` • `news-aggregator` • `telegram-bot` • `python` • `gemini-api` • `sqlite` • `bengali-news` • `automation` • `bot`

## 📄 License

This project is licensed under the **MIT License**. You are free to use, modify, and distribute it.
