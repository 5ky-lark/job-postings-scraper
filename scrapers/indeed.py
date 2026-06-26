"""Indeed Philippines job board scraper.

Uses StealthyFetcher (auto Cloudflare bypass) to scrape job listings from
https://ph.indeed.com for Philippine-based positions.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote_plus, urlencode

from scrapling.fetchers import StealthyFetcher

from .base import BaseScraper, Job

# Pre-defined keywords — a curated subset to keep request volume low.
_DEFAULT_KEYWORDS: list[str] = [
    'software developer',
    'software engineer',
    'web developer',
    'full stack developer',
    'frontend developer',
    'backend developer',
    'python developer',
    'java developer',
]

_BASE_URL = 'https://ph.indeed.com'


class IndeedScraper(BaseScraper):
    """Scrapes job listings from Indeed Philippines."""

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
        self.name = 'indeed'

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape(self) -> list[Job]:
        """Scrape Indeed PH for all configured keywords and return jobs."""
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

            # Indeed is stricter — use longer delays.
            await self._random_delay(min_sec=5.0, max_sec=10.0)

        self.logger.info(f'Indeed scrape complete — {len(all_jobs)} unique jobs')
        return all_jobs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _scrape_keyword(self, keyword: str) -> list[Job]:
        """Fetch and parse Indeed results for a single *keyword* (first page only)."""
        params = {
            'q': keyword,
            'l': 'Philippines',
            'fromage': '7',   # posted in last 7 days
            'sort': 'date',
            'start': '0',     # first page only
        }
        url = f'{_BASE_URL}/jobs?{urlencode(params)}'
        self.logger.info(f'Fetching {url}')

        proxy_kwargs: dict = {}
        if self._get_proxy_dict():
            proxy_kwargs['proxy'] = self._get_proxy_dict()

        page = await StealthyFetcher.async_fetch(
            url,
            headless=True,
            network_idle=True,
            disable_resources=True,
            **proxy_kwargs,
        )

        if page is None:
            self.logger.warning(f'No response for keyword "{keyword}"')
            return []

        # Try several selector strategies in order of preference.
        jobs = self._strategy_data_jk(page)
        if not jobs:
            jobs = self._strategy_job_beacon(page)
        if not jobs:
            jobs = self._strategy_card_outline(page)
        if not jobs:
            jobs = self._strategy_generic(page)

        return jobs

    # -- Strategy 1: elements with data-jk attribute (Indeed job key) --

    def _strategy_data_jk(self, page: object) -> list[Job]:
        """Parse jobs using Indeed's data-jk attribute on elements."""
        cards = page.css('[data-jk]')
        if not cards:
            return []

        jobs: list[Job] = []
        for card in cards:
            job_key = card.attrib.get('data-jk', '')
            if not job_key:
                continue

            job_url = f'{_BASE_URL}/viewjob?jk={job_key}'

            title = self._extract_title(card)
            if not title:
                continue

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
                    source='indeed',
                    salary=salary,
                    date_posted=date_posted,
                    description=self._extract_description(card),
                )
            )
        return jobs

    # -- Strategy 2: .job_seen_beacon / .resultContent -----------------

    def _strategy_job_beacon(self, page: object) -> list[Job]:
        """Parse jobs from .job_seen_beacon containers."""
        cards = page.css('.job_seen_beacon')
        if not cards:
            cards = page.css('.resultContent')
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
                    source='indeed',
                    salary=salary,
                    date_posted=date_posted,
                    description=self._extract_description(card),
                )
            )
        return jobs

    # -- Strategy 3: div.cardOutline -----------------------------------

    def _strategy_card_outline(self, page: object) -> list[Job]:
        """Parse jobs from div.cardOutline containers."""
        cards = page.css('div.cardOutline')
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
                    source='indeed',
                    salary=salary,
                    date_posted=date_posted,
                    description=self._extract_description(card),
                )
            )
        return jobs

    # -- Strategy 4: generic fallback ----------------------------------

    def _strategy_generic(self, page: object) -> list[Job]:
        """Last-resort generic parsing by scanning for job-title anchors."""
        links = page.css('a[href*="viewjob"], a[href*="/rc/clk"]')
        if not links:
            return []

        jobs: list[Job] = []
        for link in links:
            href = link.attrib.get('href', '')
            if not href:
                continue

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
                    source='indeed',
                )
            )
        return jobs

    # -- Shared field extractors ---------------------------------------

    def _extract_title(self, card: object) -> str:
        """Extract the job title from a card element."""
        for selector in [
            'h2[class*="jobTitle"] a',
            'h2[class*="jobTitle"] span',
            'h2[class*="jobTitle"]',
            'a[data-jk]',
            '.jobTitle a',
            '.jobTitle span',
            '.jobTitle',
            'h2 a',
            'h2 span',
            'h2',
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
            '[data-testid="company-name"]',
            '.companyName',
            'span[class*="company"]',
            '.company_location .companyName',
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
            '[data-testid="text-location"]',
            '.companyLocation',
            'div[class*="location"]',
            '.company_location .companyLocation',
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
            '.salary-snippet-container',
            '[data-testid="attribute_snippet_testid"]',
            'div[class*="salary"]',
            '.salaryText',
            'span[class*="salary"]',
        ]:
            els = card.css(selector)
            if els:
                text = self._clean_text(els[0].text)
                if text:
                    return text
        return ''

    def _extract_date(self, card: object) -> str:
        """Extract the posted date from a card element."""
        for selector in [
            'span[data-testid="myJobsStateDate"]',
            '.date',
            'span[class*="date"]',
        ]:
            els = card.css(selector)
            if els:
                text = self._clean_text(els[0].text)
                if text:
                    return text
        return ''

    def _extract_url(self, card: object) -> str:
        """Extract the job URL from a card element."""
        # Check for data-jk first.
        jk = card.attrib.get('data-jk', '')
        if jk:
            return f'{_BASE_URL}/viewjob?jk={jk}'

        # Look for data-jk on child elements.
        jk_els = card.css('[data-jk]')
        if jk_els:
            jk = jk_els[0].attrib.get('data-jk', '')
            if jk:
                return f'{_BASE_URL}/viewjob?jk={jk}'

        # Fallback: extract href from title link.
        for selector in [
            'h2 a[href]',
            'a[href*="viewjob"]',
            'a[href*="/rc/clk"]',
            'a[href]',
        ]:
            els = card.css(selector)
            if els:
                href = els[0].attrib.get('href', '')
                if href:
                    return href if href.startswith('http') else f'{_BASE_URL}{href}'

        return ''

    def _extract_description(self, card: object) -> str:
        """Extract a short description or qualifications snippet from the job card."""
        for selector in ['.job-snippet', 'div[class*="job-snippet"]', '.summary', '.metadata']:
            try:
                els = card.css(selector)
                if els:
                    text = self._clean_text(els[0].text)
                    if text:
                        return text
            except Exception:
                continue
        return ''
