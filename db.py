"""SQLite database manager for job deduplication and persistence.

Uses SHA-256 hashes of job URLs as primary keys so that duplicate listings
across scraping runs are silently ignored.
"""

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from config import DB_PATH


def _url_hash(url: str) -> str:
    """Return the hex SHA-256 digest of *url*.

    Args:
        url: The job listing URL to hash.

    Returns:
        A 64-character lowercase hex string.
    """
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _get_connection() -> sqlite3.Connection:
    """Open a connection to the SQLite database with row-factory enabled.

    Returns:
        A sqlite3.Connection whose rows behave like dicts.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create the ``jobs`` table if it does not already exist.

    The table schema:
        - ``id``          – SHA-256 hash of the URL (TEXT PRIMARY KEY)
        - ``title``       – Job title (TEXT)
        - ``company``     – Employer name (TEXT)
        - ``location``    – Job location (TEXT)
        - ``url``         – Original listing URL (TEXT)
        - ``source``      – Which job board it came from (TEXT)
        - ``salary``      – Salary info, if available (TEXT)
        - ``date_posted`` – Date the listing was posted (TEXT)
        - ``first_seen``  – When we first scraped it (DATETIME, auto-filled)
    """
    with _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id          TEXT PRIMARY KEY,
                title       TEXT,
                company     TEXT,
                location    TEXT,
                url         TEXT,
                source      TEXT,
                salary      TEXT,
                date_posted TEXT,
                first_seen  DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def is_new_job(url: str) -> bool:
    """Check whether a job URL has **not** been recorded yet.

    Args:
        url: The job listing URL to look up.

    Returns:
        ``True`` if the URL is new (not in the database), ``False`` otherwise.
    """
    job_id = _url_hash(url)
    with _get_connection() as conn:
        row = conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row is None


def save_job(job: dict[str, Any]) -> None:
    """Insert a single job record into the database.

    If a row with the same URL hash already exists the insert is silently
    ignored (``INSERT OR IGNORE``).

    Args:
        job: A dict with keys matching the ``jobs`` table columns.  At a
             minimum ``url`` must be present.
    """
    job_id = _url_hash(job["url"])
    with _get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO jobs (id, title, company, location, url, source, salary, date_posted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job["url"],
                job.get("source", ""),
                job.get("salary", ""),
                job.get("date_posted", ""),
            ),
        )
        conn.commit()


def save_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Save multiple jobs and return only the *new* ones.

    Each job is checked against the database; only those whose URL hash does
    not yet exist are inserted.  The returned list contains exclusively the
    newly inserted records.

    Args:
        jobs: A list of job dicts.

    Returns:
        A list of job dicts that were actually new and inserted.
    """
    new_jobs: list[dict[str, Any]] = []
    from utils import matches_resume

    with _get_connection() as conn:
        for job in jobs:
            # Skip job if it doesn't match user's resume skills
            if not matches_resume(job.get("title", "")):
                continue

            job_id = _url_hash(job["url"])
            existing = conn.execute(
                "SELECT 1 FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO jobs (id, title, company, location, url, source, salary, date_posted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        job.get("title", ""),
                        job.get("company", ""),
                        job.get("location", ""),
                        job["url"],
                        job.get("source", ""),
                        job.get("salary", ""),
                        job.get("date_posted", ""),
                    ),
                )
                new_jobs.append(job)

        conn.commit()

    return new_jobs


def get_job_count() -> int:
    """Return the total number of job records in the database.

    Returns:
        An integer count of rows in the ``jobs`` table.
    """
    with _get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM jobs").fetchone()
    return int(row["cnt"])


def get_recent_jobs(hours: int = 24) -> list[dict[str, Any]]:
    """Retrieve jobs first seen within the last *hours* hours.

    Args:
        hours: Look-back window in hours (default 24).

    Returns:
        A list of job dicts ordered by ``first_seen`` descending.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    with _get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, company, location, url, source, salary, date_posted, first_seen
            FROM jobs
            WHERE first_seen >= ?
            ORDER BY first_seen DESC
            """,
            (cutoff,),
        ).fetchall()

    return [dict(row) for row in rows]
