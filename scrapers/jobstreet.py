"""JobStreet Philippines job board scraper.

Uses StealthyFetcher to scrape job listings from the SEEK-powered
https://www.jobstreet.com.ph SPA.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote_plus

from scrapling.fetchers import StealthyFetcher

from .base import BaseScraper, Job

# Pre-defined hyphenated keyword slugs.
_DEFAULT_KEYWORDS: list[str] = [
    'software-developer',
    'software-engineer',
    'web-developer',
    'full-stack-developer',
    'frontend-developer',
    'backend-developer',
    'python-developer',
    'java-developer',
]

_BASE_URL = 'https://www.jobstreet.com.ph'


class JobStreetScraper(BaseScraper):
    """Scrapes job listings from JobStreet Philippines."""

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
        self.name = 'jobstreet'

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape(self) -> list[Job]:
        """Scrape JobStreet PH for all configured keywords and return jobs."""
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

            await self._random_delay(min_sec=5.0, max_sec=10.0)

        self.logger.info(
            f'JobStreet scrape complete — {len(all_jobs)} unique jobs'
        )
        return all_jobs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _scrape_keyword(self, keyword: str) -> list[Job]:
        """Fetch and parse JobStreet results for a single *keyword*."""
        url = f'{_BASE_URL}/{keyword}-jobs?sortmode=ListedDate'
        self.logger.info(f'Fetching {url}')

        proxy_kwargs: dict = {}
        if self._get_proxy_dict():
            proxy_kwargs['proxy'] = self._get_proxy_dict()

        page = await StealthyFetcher.async_fetch(
            url,
            headless=True,
            network_idle=True,
            **proxy_kwargs,
        )

        if page is None:
            self.logger.warning(f'No response for keyword "{keyword}"')
            return []

        # Try selector strategies in preference order.
        jobs = self._strategy_article_cards(page)
        if not jobs:
            jobs = self._strategy_data_automation(page)
        if not jobs:
            jobs = self._strategy_search_meta(page)
        if not jobs:
            jobs = self._strategy_generic_links(page)

        return jobs

    # -- Strategy 1: article[data-card-type="JobCard"] -----------------

    def _strategy_article_cards(self, page: object) -> list[Job]:
        """Parse job listings from <article> JobCard elements."""
        cards = page.css('article[data-card-type="JobCard"]')
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
            salary = self._extract_salary(card)
            date_posted = self._extract_date(card)

            jobs.append(
                Job(
                    title=title,
                    company=company,
                    location=location or 'Philippines',
                    url=job_url,
                    source='jobstreet',
                    salary=salary,
                    date_posted=date_posted,
                )
            )
        return jobs

    # -- Strategy 2: data-automation="jobTitle" anchors ----------------

    def _strategy_data_automation(self, page: object) -> list[Job]:
        """Parse jobs from data-automation attributed elements."""
        title_els = page.css('a[data-automation="jobTitle"]')
        if not title_els:
            return []

        jobs: list[Job] = []
        for title_el in title_els:
            title = self._clean_text(title_el.text)
            if not title:
                continue

            href = title_el.attrib.get('href', '')
            job_url = href if href.startswith('http') else f'{_BASE_URL}{href}'

            # Navigate up to find the parent card-like container.
            # Since we can't rely on parent traversal, search siblings
            # from page-level context for matching company/location.
            company = ''
            location = ''
            salary = ''
            date_posted = ''

            # Attempt to find the closest ancestor card.
            parent_card = self._find_ancestor_card(title_el, page)
            if parent_card is not None:
                company = self._extract_company(parent_card)
                location = self._extract_location(parent_card)
                salary = self._extract_salary(parent_card)
                date_posted = self._extract_date(parent_card)

            jobs.append(
                Job(
                    title=title,
                    company=company,
                    location=location or 'Philippines',
                    url=job_url,
                    source='jobstreet',
                    salary=salary,
                    date_posted=date_posted,
                )
            )
        return jobs

    # -- Strategy 3: div[data-search-sol-meta] -------------------------

    def _strategy_search_meta(self, page: object) -> list[Job]:
        """Parse jobs from SEEK search-sol-meta containers."""
        cards = page.css('div[data-search-sol-meta]')
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
            salary = self._extract_salary(card)
            date_posted = self._extract_date(card)

            jobs.append(
                Job(
                    title=title,
                    company=company,
                    location=location or 'Philippines',
                    url=job_url,
                    source='jobstreet',
                    salary=salary,
                    date_posted=date_posted,
                )
            )
        return jobs

    # -- Strategy 4: generic link fallback -----------------------------

    def _strategy_generic_links(self, page: object) -> list[Job]:
        """Last-resort: scan for anchors whose href contains /job/."""
        links = page.css('a[href*="/job/"]')
        if not links:
            return []

        jobs: list[Job] = []
        seen_hrefs: set[str] = set()
        for link in links:
            href = link.attrib.get('href', '')
            if not href or href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            job_url = href if href.startswith('http') else f'{_BASE_URL}{href}'
            title = self._clean_text(link.text)
            if not title:
                continue

            jobs.append(
                Job(
                    title=title,
                    company='',
                    location='Philippines',
                    url=job_url,
                    source='jobstreet',
                )
            )
        return jobs

    # -- Shared field extractors ---------------------------------------

    def _extract_title(self, card: object) -> str:
        """Extract the job title from a card element."""
        for selector in [
            'a[data-automation="jobTitle"]',
            '[data-automation="jobTitle"]',
            'h3 a',
            'h3',
            'a[href*="/job/"]',
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
            'a[data-automation="jobCompany"]',
            '[data-automation="jobCompany"]',
            'span[data-automation="jobCompany"]',
            'a[href*="/companies/"]',
        ]:
            els = card.css(selector)
            if els:
                text = self._clean_text(els[0].text)
                if text:
                    return text
        return ''

    def _extract_location(self, card: object) -> str:
        """Extract the job location from a card element."""
        for selector in [
            '[data-automation="jobLocation"]',
            'span[data-automation="jobLocation"]',
            'a[data-automation="jobLocation"]',
        ]:
            els = card.css(selector)
            if els:
                text = self._clean_text(els[0].text)
                if text:
                    return text
        return ''

    def _extract_salary(self, card: object) -> str:
        """Extract salary information from a card element."""
        for selector in [
            '[data-automation="jobSalary"]',
            'span[data-automation="jobSalary"]',
            'span[class*="salary"]',
        ]:
            els = card.css(selector)
            if els:
                text = self._clean_text(els[0].text)
                if text:
                    return text
        return ''

    def _extract_date(self, card: object) -> str:
        """Extract the listing date from a card element."""
        for selector in [
            '[data-automation="jobListingDate"]',
            'span[data-automation="jobListingDate"]',
            'time',
            'span[class*="date"]',
            'span[class*="Date"]',
        ]:
            els = card.css(selector)
            if els:
                # Prefer datetime attribute on <time> elements.
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
            'a[data-automation="jobTitle"]',
            'a[href*="/job/"]',
            'h3 a[href]',
            'a[href]',
        ]:
            els = card.css(selector)
            if els:
                href = els[0].attrib.get('href', '')
                if href:
                    return href if href.startswith('http') else f'{_BASE_URL}{href}'
        return ''

    def _find_ancestor_card(
        self, element: object, page: object
    ) -> object | None:
        """Attempt to find a parent card container for *element*.

        Since Scrapling's element model may not expose direct parent
        traversal, we fall back to re-searching the page for known card
        selectors and matching by URL overlap.
        """
        href = element.attrib.get('href', '')
        if not href:
            return None

        for selector in [
            'article[data-card-type="JobCard"]',
            'div[data-search-sol-meta]',
            'div[class*="card"]',
        ]:
            cards = page.css(selector)
            for card in cards:
                links = card.css(f'a[href="{href}"]')
                if links:
                    return card
        return None
