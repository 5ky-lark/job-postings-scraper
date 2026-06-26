"""Job scraper package.

Re-exports the core dataclass and all site-specific scraper classes.
"""

from .base import Job, BaseScraper
from .kalibrr import KalibrrScraper
from .indeed import IndeedScraper
from .jobstreet import JobStreetScraper
from .linkedin import LinkedInScraper

__all__ = [
    'Job',
    'BaseScraper',
    'KalibrrScraper',
    'IndeedScraper',
    'JobStreetScraper',
    'LinkedInScraper',
]
