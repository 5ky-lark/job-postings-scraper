"""Kalibrr Philippines job board scraper.

Uses DynamicFetcher (light anti-bot) to scrape job listings from
https://www.kalibrr.com for Philippine-based positions.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote_plus

from scrapling.fetchers import DynamicFetcher

from .base import BaseScraper, Job

# Pre-defined keyword slugs (hyphenated) to keep request volume low.
_DEFAULT_KEYWORDS: list[str] = [
    'software-developer',
    'software-engineer',
    'web-developer',
    'full-stack-developer',
    'frontend-developer',
    'backend-developer',
    'mobile-developer',
    'devops-engineer',
]

_BASE_URL = 'https://www.kalibrr.com'


class KalibrrScraper(BaseScraper):
    """Scrapes job listings from Kalibrr Philippines."""

    def __init__(
        self,
        keywords: list[str] | None = None,
        locations: list[str] | None = None,
        proxy: str | None = None,
    ) -> None:
        super().__init__(
            keywords=keywords or _DEFAULT_KEYWORDS,
            locations=locations or ['Philippines'],
            proxy=proxy,
        )
        self.name = 'kalibrr'

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape(self) -> list[Job]:
        """Scrape Kalibrr for all configured keywords and return jobs."""
        all_jobs: list[Job] = []
        seen_urls: set[str] = set()

        for keyword in self.keywords:
            try:
                jobs = await self._scrape_keyword(keyword)
                for job in jobs:
                    if job.url not in seen_urls:
                        seen_urls.add(job.url)
                        all_jobs.append(job)
                self.logger.info(
                    f'[{keyword}] Found {len(jobs)} jobs '
                    f'({len(all_jobs)} total unique so far)'
                )
            except Exception:
                self.logger.exception(f'Error scraping keyword "{keyword}"')

            await self._random_delay(min_sec=3.0, max_sec=8.0)

        self.logger.info(f'Kalibrr scrape complete — {len(all_jobs)} unique jobs')
        return all_jobs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _scrape_keyword(self, keyword: str) -> list[Job]:
        """Fetch and parse Kalibrr results for a single *keyword*."""
        url = f'{_BASE_URL}/job-board/te/{keyword}/co/Philippines'
        self.logger.info(f'Fetching {url}')

        page = await DynamicFetcher.async_fetch(
            url,
            headless=True,
            network_idle=True,
            disable_resources=True,
            **(
                {'proxy': self._get_proxy_dict()}
                if self._get_proxy_dict()
                else {}
            ),
        )

        if page is None:
            self.logger.warning(f'No response for keyword "{keyword}"')
            return []

        # Try several selector strategies in order of preference.
        jobs = self._strategy_job_links(page)
        if not jobs:
            jobs = self._strategy_font_class(page)
        if not jobs:
            jobs = self._strategy_generic_cards(page)

        return jobs

    # -- Strategy 1: anchor tags whose href contains '/c/' (job links) --

    def _strategy_job_links(self, page: object) -> list[Job]:
        """Parse job cards by finding links whose href matches /c/."""
        cards = page.css("a[href*='/c/']")
        if not cards:
            return []

        jobs: list[Job] = []
        for card in cards:
            href = card.attrib.get('href', '')
            if not href or '/c/' not in href:
                continue

            job_url = href if href.startswith('http') else f'{_BASE_URL}{href}'

            # Title is typically the bold/heading text inside the link.
            title_el = card.css('h2, h3, span.k-font-dm-sans, span')
            title = self._clean_text(
                title_el[0].text if title_el else card.text
            )
            if not title:
                continue

            # Company / location / salary may be siblings or nested.
            company = self._extract_sibling_text(card, 'company')
            location = self._extract_sibling_text(card, 'location')
            salary = self._extract_sibling_text(card, 'salary')
            date_posted = self._extract_sibling_text(card, 'date')

            jobs.append(
                Job(
                    title=title,
                    company=company,
                    location=location or 'Philippines',
                    url=job_url,
                    source='kalibrr',
                    salary=salary,
                    date_posted=date_posted,
                    description=self._extract_description(card),
                )
            )
        return jobs

    # -- Strategy 2: Kalibrr font-class based cards --------------------

    def _strategy_font_class(self, page: object) -> list[Job]:
        """Parse cards using the Kalibrr-specific font class."""
        cards = page.css('.k-font-dm-sans')
        if not cards:
            return []

        jobs: list[Job] = []
        for card in cards:
            link = card.css('a[href]')
            if not link:
                continue
            href = link[0].attrib.get('href', '')
            job_url = href if href.startswith('http') else f'{_BASE_URL}{href}'

            texts = [self._clean_text(el.text) for el in card.css('span, p, h2, h3, div') if self._clean_text(el.text)]
            if len(texts) < 1:
                continue

            title = texts[0]
            company = texts[1] if len(texts) > 1 else ''
            location = texts[2] if len(texts) > 2 else 'Philippines'
            salary = texts[3] if len(texts) > 3 else ''

            jobs.append(
                Job(
                    title=title,
                    company=company,
                    location=location,
                    url=job_url,
                    source='kalibrr',
                    salary=salary,
                    description=self._extract_description(card),
                )
            )
        return jobs

    # -- Strategy 3: generic card-like divs ----------------------------

    def _strategy_generic_cards(self, page: object) -> list[Job]:
        """Last-resort: look for any div that looks like a job card."""
        cards = page.css('div[class*="card"], div[class*="Card"], div[class*="job"]')
        if not cards:
            return []

        jobs: list[Job] = []
        for card in cards:
            link = card.css('a[href]')
            if not link:
                continue
            href = link[0].attrib.get('href', '')
            if '/c/' not in href and '/job' not in href.lower():
                continue

            job_url = href if href.startswith('http') else f'{_BASE_URL}{href}'
            title_el = card.css('h2, h3, a')
            title = self._clean_text(
                title_el[0].text if title_el else ''
            )
            if not title:
                continue

            spans = card.css('span, p')
            span_texts = [self._clean_text(s.text) for s in spans if self._clean_text(s.text)]

            company = span_texts[0] if len(span_texts) > 0 else ''
            location = span_texts[1] if len(span_texts) > 1 else 'Philippines'
            salary = span_texts[2] if len(span_texts) > 2 else ''

            jobs.append(
                Job(
                    title=title,
                    company=company,
                    location=location,
                    url=job_url,
                    source='kalibrr',
                    salary=salary,
                    description=self._extract_description(card),
                )
            )
        return jobs

    # -- Shared helpers ------------------------------------------------

    def _extract_sibling_text(self, element: object, hint: str) -> str:
        """Try to extract text from a sibling/child element matching *hint*."""
        for selector in [
            f'[class*="{hint}"]',
            f'[data-testid*="{hint}"]',
            f'span',
            f'p',
        ]:
            try:
                matches = element.css(selector)
                for match in matches:
                    text = self._clean_text(match.text)
                    if text:
                        return text
            except Exception:
                continue
        return ''

    def _extract_description(self, card: object) -> str:
        """Extract a short description or qualifications snippet from the job card."""
        for selector in [
            'p[class*="description"]',
            'div[class*="description"]',
            'span[class*="description"]',
            'p.k-text-xs',
            'p',
        ]:
            try:
                els = card.css(selector)
                for el in els:
                    text = self._clean_text(el.text)
                    if text and len(text) > 15:
                        return text
            except Exception:
                continue
        return ''
