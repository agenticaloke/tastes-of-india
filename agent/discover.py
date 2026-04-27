"""
Sitemap-based URL discovery.

Search engines (DuckDuckGo, etc.) rate-limit aggressively, so the agent
falls back to reading each site's sitemap.xml directly. Sitemaps are public
and meant to be crawled — this is more reliable than scraping search.
"""
from __future__ import annotations

import re
import logging
import requests
from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
}

SITEMAP_PATHS = [
    '/sitemap.xml',
    '/sitemap_index.xml',
    '/wp-sitemap.xml',
    '/post-sitemap.xml',
]

# URLs that look like category/tag/page indexes rather than recipe pages.
SKIP_PATH_PATTERNS = [
    '/category/', '/categories/', '/tag/', '/tags/',
    '/page/', '/author/', '/about', '/contact', '/privacy',
    '/collection/', '/collections/', '/recipes/', '/cuisine/',
    '/feed/', '/rss', '/sitemap',
]

NS = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}


def _fetch(url: str, timeout: int = 15) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200 and r.text.strip():
            return r.text
    except Exception as e:
        log.debug(f'Sitemap fetch failed {url}: {e}')
    return None


def _parse_sitemap(xml_text: str) -> tuple[list[str], list[str]]:
    """Return (child_sitemap_urls, page_urls)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], []

    tag = root.tag.lower()
    children: list[str] = []
    pages: list[str] = []

    if tag.endswith('sitemapindex'):
        for sm in root.findall('sm:sitemap', NS):
            loc = sm.find('sm:loc', NS)
            if loc is not None and loc.text:
                children.append(loc.text.strip())
    elif tag.endswith('urlset'):
        for u in root.findall('sm:url', NS):
            loc = u.find('sm:loc', NS)
            if loc is not None and loc.text:
                pages.append(loc.text.strip())
    return children, pages


def _looks_like_recipe(url: str) -> bool:
    low = url.lower()
    if any(p in low for p in SKIP_PATH_PATTERNS):
        return False
    # Must end in a slug-looking segment, not a top-level page
    path = low.split('://', 1)[-1].split('/', 1)
    if len(path) < 2:
        return False
    slug = path[1].rstrip('/')
    if not slug or slug.count('/') > 3:
        return False
    # Has at least one hyphenated word (typical recipe slug)
    return bool(re.search(r'[a-z]+-[a-z]+', slug))


def discover_site_urls(site: str, max_urls: int = 200) -> list[str]:
    """Walk a site's sitemap and return up to max_urls recipe-looking URLs."""
    base = f'https://www.{site}'
    sitemap_text = None
    for path in SITEMAP_PATHS:
        sitemap_text = _fetch(base + path)
        if sitemap_text:
            log.debug(f'Found sitemap: {base}{path}')
            break
    if not sitemap_text:
        # Try without www
        for path in SITEMAP_PATHS:
            sitemap_text = _fetch(f'https://{site}{path}')
            if sitemap_text:
                break
    if not sitemap_text:
        log.warning(f'No sitemap found for {site}')
        return []

    children, pages = _parse_sitemap(sitemap_text)

    # Walk one level of child sitemaps if this was an index
    for child in children[:8]:  # cap to keep it polite
        if len(pages) >= max_urls * 3:
            break
        text = _fetch(child)
        if not text:
            continue
        _, child_pages = _parse_sitemap(text)
        pages.extend(child_pages)

    # Filter to recipe-looking URLs and dedupe while preserving order
    seen = set()
    recipe_urls = []
    for u in pages:
        if u in seen:
            continue
        seen.add(u)
        if _looks_like_recipe(u):
            recipe_urls.append(u)
        if len(recipe_urls) >= max_urls:
            break
    log.info(f'Discovered {len(recipe_urls)} candidate URLs from {site}')
    return recipe_urls
