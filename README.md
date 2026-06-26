# Software Developer Job Posting Scraper

Scrapes software developer job postings from 4 Philippine job boards and notifies a Discord channel via webhook.

## Features

* **Multi-Source Scraping**: Fetches listings from Kalibrr PH, Indeed PH, JobStreet PH, and LinkedIn.
* **Anti-Bot Bypass**: Uses Scrapling (`StealthyFetcher`/`DynamicFetcher`) to automatically bypass Cloudflare Turnstile, headless detection, and WAF protections.
* **Real-time Staggered Scheduling**: Runs scrapers continuously at staggered intervals per source (Kalibrr: 30m, Indeed: 30m, JobStreet: 45m, LinkedIn: 90m) to minimize CPU/RAM usage and avoid rate limits.
* **SQLite Job Deduplication**: Prevents duplicate postings by hashing job URLs and tracking seen entries.
* **Discord Integration**: 
  * Rich embeds with source color coding and details sent to a Discord webhook.
  * Interactive Discord bot with instant manual scrape command (`!fetch`).
* **Docker Containerization**: Easily deployable to cloud hosts (VPS, Railway, etc.) using Docker and docker-compose.

## Usage

### Prerequisites
* Python 3.11+
* Chrome or Chromium browser (for scrapling fetchers)

### Configuration
1. Rename `.env.example` to `.env`.
2. Edit the `.env` file and insert your tokens and webhook URL:
   ```env
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN
   DISCORD_BOT_TOKEN=YOUR_DISCORD_BOT_TOKEN
   ```

### Running Locally
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   playwright install-deps chromium
   patchright install chromium
   ```
2. Run the Discord bot (scheduled loop + commands):
   ```bash
   python bot.py
   ```
3. Run the standalone scheduler (webhook notifications only):
   ```bash
   python main.py
   ```
4. Run a single scraping run and exit:
   ```bash
   python main.py --once
   ```
5. Send a test message to your Discord webhook:
   ```bash
   python main.py --test
   ```

### Docker Deployment
Build and run the container:
```bash
docker-compose up -d
```
