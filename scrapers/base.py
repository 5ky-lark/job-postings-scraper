"""Base scraper module with shared Job dataclass and abstract BaseScraper class."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from abc import ABC, abstractmethod
import logging
import asyncio
import random


@dataclass
class Job:
    """Represents a single job listing scraped from any source."""

    title: str
    company: str
    location: str
    url: str
    source: str  # 'kalibrr', 'indeed', 'jobstreet', 'linkedin'
    salary: str = ''
    date_posted: str = ''
    description: str = ''

    def to_dict(self) -> dict:
        """Convert the Job instance to a plain dictionary."""
        return asdict(self)


class BaseScraper(ABC):
    """Base class for all job scrapers.

    Provides shared configuration, logging, delay utilities, and text
    cleaning helpers.  Subclasses must implement the ``scrape`` method.
    """

    def __init__(
        self,
        keywords: list[str],
        locations: list[str],
        proxy: str | None = None,
    ) -> None:
        self.keywords = keywords
        self.locations = locations
        self.proxy = proxy
        self.logger = logging.getLogger(self.__class__.__name__)
        self.name: str = 'base'  # Override in subclasses

    @abstractmethod
    async def scrape(self) -> list[Job]:
        """Scrape job listings. Must be implemented by subclasses."""
        pass

    async def _random_delay(
        self, min_sec: float = 3.0, max_sec: float = 8.0
    ) -> None:
        """Sleep for a random duration between *min_sec* and *max_sec*."""
        delay = random.uniform(min_sec, max_sec)
        self.logger.debug(f'Waiting {delay:.1f}s...')
        await asyncio.sleep(delay)

    def _clean_text(self, text: str | None) -> str:
        """Strip and collapse whitespace in *text*."""
        if not text:
            return ''
        return ' '.join(text.strip().split())

    def _get_proxy_dict(self) -> dict | None:
        """Return a proxy dict suitable for Scrapling fetchers, or None."""
        if self.proxy:
            return {'server': self.proxy}
        return None
