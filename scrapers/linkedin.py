"""LinkedIn Jobs guest-view scraper.

Uses StealthyFetcher with real_chrome=True for maximum stealth when
scraping the public (no-login) LinkedIn job search pages.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote_plus, urlencode

from scrapling.fetchers import StealthyFetcher

from .base import BaseScraper, Job

# Intentionally small keyword set — LinkedIn is aggressive about blocking.
_DEFAULT_KEYWORDS: list[str] = [
    'software developer',
    'software engineer',
    'web developer',
    'full stack developer',
]

_BASE_URL = 'https://www.linkedin.com'


class LinkedInScraper(BaseScraper):
    """Scrapes job listings from LinkedIn's public guest search."""

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
        self.name = 'linkedin'

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape(self) -> list[Job]:
        """Scrape LinkedIn guest job search for all keywords and return jobs."""
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
                self.logger.exception(
                    f'Error scraping keyword "{keyword}" — LinkedIn may be blocking'
                )

            # Extra-long delays for LinkedIn.
            await self._random_delay(min_sec=10.0, max_sec=20.0)

        self.logger.info(
            f'LinkedIn scrape complete — {len(all_jobs)} unique jobs'
        )
        return all_jobs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _scrape_keyword(self, keyword: str) -> list[Job]:
        """Fetch and parse LinkedIn guest results for a single *keyword*."""
        params = {
            'keywords': keyword,
            'location': 'Philippines',
            'f_TPR': 'r604800',   # posted in last 7 days
            'sortBy': 'DD',       # sort by date
            'position': '1',
            'pageNum': '0',
        }
        url = f'{_BASE_URL}/jobs/search/?{urlencode(params)}'
        self.logger.info(f'Fetching {url}')

        proxy_kwargs: dict = {}
        if self._get_proxy_dict():
            proxy_kwargs['proxy'] = self._get_proxy_dict()

        page = await StealthyFetcher.async_fetch(
            url,
            headless=True,
            real_chrome=True,
            google_search=True,
            network_idle=True,
            disable_resources=True,
            **proxy_kwargs,
        )

        if page is None:
            self.logger.warning(f'No response for keyword "{keyword}"')
            return []

        # Try selector strategies in preference order.
        jobs = self._strategy_base_cards(page)
        if not jobs:
            jobs = self._strategy_search_cards(page)
        if not jobs:
            jobs = self._strategy_entity_urn(page)
        if not jobs:
            jobs = self._strategy_generic_list(page)

        return jobs

    # -- Strategy 1: .base-card / .base-search-card --------------------

    def _strategy_base_cards(self, page: object) -> list[Job]:
        """Parse jobs from LinkedIn's base-card elements."""
        cards = page.css('.base-card, .base-search-card')
        if not cards:
            return []

        jobs: list[Job] = []
        for card in cards:
            title = self._extract_title(card)
            if not title:
                continue

            job_url = self._extract_url(card)
            company = self._extract_company(card)
            location = self._extract_location(card)
            date_posted = self._extract_date(card)

            jobs.append(
                Job(
                    title=title,
                    company=company,
                    location=location or 'Philippines',
                    url=job_url,
                    source='linkedin',
                    salary='',  # LinkedIn guest view rarely shows salary
                    date_posted=date_posted,
                )
            )
        return jobs

    # -- Strategy 2: div.job-search-card -------------------------------

    def _strategy_search_cards(self, page: object) -> list[Job]:
        """Parse jobs from div.job-search-card elements."""
        cards = page.css('div.job-search-card')
        if not cards:
            return []

        jobs: list[Job] = []
        for card in cards:
            title = self._extract_title(card)
            if not title:
                continue

            job_url = self._extract_url(card)
            company = self._extract_company(card)
            location = self._extract_location(card)
            date_posted = self._extract_date(card)

            jobs.append(
                Job(
                    title=title,
                    company=company,
                    location=location or 'Philippines',
                    url=job_url,
                    source='linkedin',
                    salary='',
                    date_posted=date_posted,
                )
            )
        return jobs

    # -- Strategy 3: data-entity-urn attribute -------------------------

    def _strategy_entity_urn(self, page: object) -> list[Job]:
        """Parse jobs from elements with data-entity-urn attribute."""
        cards = page.css('[data-entity-urn]')
        if not cards:
            return []

        jobs: list[Job] = []
        for card in cards:
            urn = card.attrib.get('data-entity-urn', '')
            if 'jobPosting' not in urn:
                continue

            title = self._extract_title(card)
            if not title:
                continue

            job_url = self._extract_url(card)
            company = self._extract_company(card)
            location = self._extract_location(card)
            date_posted = self._extract_date(card)

            jobs.append(
                Job(
                    title=title,
                    company=company,
                    location=location or 'Philippines',
                    url=job_url,
                    source='linkedin',
                    salary='',
                    date_posted=date_posted,
                )
            )
        return jobs

    # -- Strategy 4: generic <li> inside results list ------------------

    def _strategy_generic_list(self, page: object) -> list[Job]:
        """Last-resort: scan <li> items inside the results list."""
        results_list = page.css('.jobs-search__results-list')
        if not results_list:
            return []

        items = results_list[0].css('li')
        if not items:
            return []

        jobs: list[Job] = []
        for item in items:
            link = item.css('a[href*="/jobs/view/"]')
            if not link:
                link = item.css('a[href]')
            if not link:
                continue

            href = link[0].attrib.get('href', '')
            job_url = self._normalise_url(href)
            title = self._clean_text(link[0].text)
            if not title:
                continue

            company = self._extract_company(item)
            location = self._extract_location(item)
            date_posted = self._extract_date(item)

            jobs.append(
                Job(
                    title=title,
                    company=company,
                    location=location or 'Philippines',
                    url=job_url,
                    source='linkedin',
                    salary='',
                    date_posted=date_posted,
                )
            )
        return jobs

    # -- Shared field extractors ---------------------------------------

    def _extract_title(self, card: object) -> str:
        """Extract the job title from a card element."""
        for selector in [
            '.base-search-card__title',
            'h3.base-search-card__title',
            'h3',
            'a[href*="/jobs/view/"]',
        ]:
            els = card.css(selector)
            if els:
                text = self._clean_text(els[0].text)
                if text:
                    return text
        return ''

    def _extract_company(self, card: object) -> str:
        """Extract the company name from a card element."""
        for selector in [
            '.base-search-card__subtitle',
            'h4.base-search-card__subtitle',
            'h4',
            'a[data-tracking-control-name*="company"]',
        ]:
            els = card.css(selector)
            if els:
                text = self._clean_text(els[0].text)
                if text:
                    return text
        return ''

    def _extract_location(self, card: object) -> str:
        """Extract the location from a card element."""
        for selector in [
            '.job-search-card__location',
            'span.job-search-card__location',
            'span[class*="location"]',
        ]:
            els = card.css(selector)
            if els:
                text = self._clean_text(els[0].text)
                if text:
                    return text
        return ''

    def _extract_date(self, card: object) -> str:
        """Extract the posting date from a card element."""
        for selector in [
            'time',
            '.job-search-card__listdate',
            '.job-search-card__listdate--new',
        ]:
            els = card.css(selector)
            if els:
                # Prefer the datetime attribute on <time> elements.
                dt = els[0].attrib.get('datetime', '')
                if dt:
                    return dt
                text = self._clean_text(els[0].text)
                if text:
                    return text
        return ''

    def _extract_url(self, card: object) -> str:
        """Extract the job URL from a card element."""
        for selector in [
            'a.base-card__full-link',
            'a[href*="/jobs/view/"]',
            'a[href]',
        ]:
            els = card.css(selector)
            if els:
                href = els[0].attrib.get('href', '')
                if href:
                    return self._normalise_url(href)
        return ''

    def _normalise_url(self, href: str) -> str:
        """Ensure *href* is an absolute LinkedIn URL.

        Also strips tracking query parameters for cleaner deduplication.
        """
        if not href:
            return ''
        url = href if href.startswith('http') else f'{_BASE_URL}{href}'
        # Strip tracking params after '?' for cleaner dedup.
        if '?' in url:
            url = url.split('?')[0]
        return url
