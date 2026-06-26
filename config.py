"""Configuration module for the job scraper project.

Loads settings from a .env file and exposes them as module-level constants
for use throughout the application.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root
_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Core settings
# ---------------------------------------------------------------------------

DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")
"""Discord webhook URL for sending job notifications."""

DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
"""Discord bot token for the interactive bot (commands like !fetch)."""

def _get_env_int(key: str, default: int) -> int:
    """Helper to safely parse integer env variables, falling back to default if empty/invalid."""
    val = os.getenv(key, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


CHECK_INTERVAL_HOURS: int = _get_env_int("CHECK_INTERVAL_HOURS", 6)
"""How often (in hours) to run the full scraping cycle (main.py scheduler mode)."""

SCRAPE_MODE: str = os.getenv("SCRAPE_MODE", "realtime").lower()
"""Scraping mode: 'realtime' (continuous per-source loops) or 'scheduled' (single interval)."""

# Per-source intervals in minutes (used in realtime mode)
KALIBRR_INTERVAL_MIN: int = _get_env_int("KALIBRR_INTERVAL_MIN", 30)
INDEED_INTERVAL_MIN: int = _get_env_int("INDEED_INTERVAL_MIN", 30)
JOBSTREET_INTERVAL_MIN: int = _get_env_int("JOBSTREET_INTERVAL_MIN", 45)
LINKEDIN_INTERVAL_MIN: int = _get_env_int("LINKEDIN_INTERVAL_MIN", 90)

SOURCE_INTERVALS: dict[str, int] = {
    "kalibrr": KALIBRR_INTERVAL_MIN,
    "indeed": INDEED_INTERVAL_MIN,
    "jobstreet": JOBSTREET_INTERVAL_MIN,
    "linkedin": LINKEDIN_INTERVAL_MIN,
}
"""Per-source scrape intervals in minutes for real-time mode."""

PROXY_URL: str | None = os.getenv("PROXY_URL") or None
"""Optional proxy URL for HTTP requests. None when not set."""

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
"""Logging verbosity level."""

DB_PATH: str = os.getenv("DB_PATH", str(_PROJECT_ROOT / "jobs.db"))
"""Path to the SQLite database file."""

# ---------------------------------------------------------------------------
# Search configuration
# ---------------------------------------------------------------------------

SEARCH_KEYWORDS: list[str] = [
    "software developer",
    "software engineer",
    "web developer",
    "full stack developer",
    "frontend developer",
    "backend developer",
    "full-stack developer",
    "front-end developer",
    "back-end developer",
    "react developer",
    "python developer",
    "java developer",
    "javascript developer",
    "node.js developer",
    "nodejs developer",
    ".net developer",
    "mobile developer",
    "android developer",
    "ios developer",
    "flutter developer",
    "devops engineer",
    "cloud engineer",
    "data engineer",
    "machine learning engineer",
    "AI engineer",
    "QA engineer",
    "test engineer",
    "automation engineer",
    "systems engineer",
    "site reliability engineer",
    "SRE",
    "programmer",
    "coder",
    "vibe coder",
    "application developer",
    "app developer",
    "junior developer",
    "senior developer",
    "lead developer",
    "tech lead",
    "engineering manager",
    "solutions architect",
    "software architect",
    "PHP developer",
    "Laravel developer",
    "Vue.js developer",
    "Angular developer",
    "Ruby developer",
    "Go developer",
    "Golang developer",
    "Rust developer",
    "TypeScript developer",
    "C# developer",
    "C++ developer",
    "game developer",
    "blockchain developer",
    "web3 developer",
    "UI developer",
    "UX engineer",
]
"""Keywords used to search for software developer positions."""

LOCATIONS: list[str] = [
    "Philippines",
    "Manila",
    "Cebu",
    "Davao",
    "Remote",
]
"""Target locations to include in job searches."""

# ---------------------------------------------------------------------------
# Discord embed theming per source
# ---------------------------------------------------------------------------

SOURCE_COLORS: dict[str, int] = {
    "kalibrr": 0x7C3AED,
    "indeed": 0x2557A7,
    "jobstreet": 0xE44D26,
    "linkedin": 0x0077B5,
}
"""Hex colour integers used for Discord embed side-bars, keyed by source."""

SOURCE_ICONS: dict[str, str] = {
    "kalibrr": "🟣",
    "indeed": "🟢",
    "jobstreet": "🟠",
    "linkedin": "🔵",
}
"""Emoji icons displayed alongside source names in embeds."""
