"""
Tastes of India — Recipe Agent
Runs independently from Flask. Discovers and adds new recipes every 6 hours.

Usage:
  cd ~/Desktop/tastes-of-india
  source venv/bin/activate
  python agent/recipe_agent.py
"""
from __future__ import annotations

import os
import sys
import json
import time
import hashlib
import sqlite3
import logging
import re
import random
import unicodedata

import requests
import schedule
from bs4 import BeautifulSoup

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.agent_config import (
    CITIES, CATEGORIES, TARGET_SITES, DDG_URL,
    REQUEST_DELAY, MAX_NEW_PER_RUN, RUN_INTERVAL_HOURS,
    NON_VEG_TOKENS, VEG_QUERY_MODIFIER,
    MIN_SITES_PER_RUN, CATEGORIES_PER_SITE,
)
from agent.parsers.generic_parser import GenericParser
from agent.parsers.archana_kitchen import ArchanaKitchenParser
from agent.discover import discover_site_urls

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [AGENT] %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
log = logging.getLogger(__name__)

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'instance', 'tastes.db'
)

PARSERS = [ArchanaKitchenParser(), GenericParser()]

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
}

CATEGORY_MAP = {
    'appetizer': 'appetizer',
    'appetizers': 'appetizer',
    'starter': 'appetizer',
    'starters': 'appetizer',
    'indian starter': 'appetizer',
    'indian starters': 'appetizer',
    'snack': 'appetizer',
    'snacks': 'appetizer',
    'indian snack': 'appetizer',
    'indian snacks': 'appetizer',
    'pakora': 'appetizer',
    'chaat': 'appetizer',
    'tikki': 'appetizer',
    'samosa': 'appetizer',
    'street food': 'appetizer',
    'entree': 'entree',
    'main course': 'entree',
    'main dish': 'entree',
    'curry': 'entree',
    'rice': 'entree',
    'bread': 'entree',
    'biryani': 'entree',
    'dessert': 'dessert',
    'sweet': 'dessert',
    'mithai': 'dessert',
    'drink': 'drink',
    'beverage': 'drink',
    'sherbet': 'drink',
    'lassi': 'drink',
    'chai': 'drink',
}


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def normalise_name(name: str) -> str:
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    name = re.sub(r'[^a-z0-9\s]', '', name.lower())
    return ' '.join(name.split())


def content_hash(recipe: dict) -> str:
    ings = recipe.get('ingredients', [])
    first3 = [i['item'] if isinstance(i, dict) else str(i) for i in ings[:3]]
    payload = normalise_name(recipe['name']) + '|' + '|'.join(first3)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def is_duplicate(db: sqlite3.Connection, city_id: int, recipe: dict) -> bool:
    norm = normalise_name(recipe['name'])
    existing = db.execute(
        'SELECT name FROM recipes WHERE city_id = ?', (city_id,)
    ).fetchall()
    for row in existing:
        if normalise_name(row['name']) == norm:
            return True
    return False


def url_already_seen(db: sqlite3.Connection, url: str) -> bool:
    row = db.execute(
        'SELECT id FROM agent_runs WHERE source_url = ?', (url,)
    ).fetchone()
    return row is not None


def log_run(db: sqlite3.Connection, url: str, status: str, reason: str = ''):
    try:
        db.execute(
            'INSERT OR IGNORE INTO agent_runs (source_url, status, reason) VALUES (?, ?, ?)',
            (url, status, reason)
        )
        db.commit()
    except Exception:
        pass


def guess_category(recipe: dict, search_query: str) -> str:
    combined = (recipe.get('name', '') + ' ' + search_query).lower()
    for keyword, cat in CATEGORY_MAP.items():
        if keyword in combined:
            return cat
    return 'entree'


def is_vegetarian(recipe: dict) -> tuple[bool, str]:
    """Return (ok, reason). Reject if any non-veg token appears in name,
    description, ingredients, or instructions."""
    haystack_parts = [
        recipe.get('name', ''),
        recipe.get('description', ''),
    ]
    for ing in recipe.get('ingredients', []):
        if isinstance(ing, dict):
            haystack_parts.append(ing.get('item', ''))
            haystack_parts.append(ing.get('qty', ''))
        else:
            haystack_parts.append(str(ing))
    for step in recipe.get('instructions', []):
        haystack_parts.append(str(step))

    hay = ' '.join(haystack_parts).lower()
    for token in NON_VEG_TOKENS:
        # Word-boundary-ish check: surround with spaces to avoid 'hambagh' etc.
        if f' {token} ' in f' {hay} ' or hay.startswith(token + ' ') or hay.endswith(' ' + token):
            return False, token
        if token in hay and len(token) >= 6:
            # longer tokens are specific enough (e.g. "chicken", "prawn", "mutton")
            return False, token
    return True, ''


def search_ddg(query: str) -> list[str]:
    """Return up to 5 URLs from DuckDuckGo HTML search."""
    try:
        resp = requests.post(
            DDG_URL,
            data={'q': query, 'b': '', 'kl': 'us-en'},
            headers=HEADERS,
            timeout=15,
        )
        soup = BeautifulSoup(resp.text, 'lxml')
        links = []
        for a in soup.select('a.result__a'):
            href = a.get('href', '')
            if href.startswith('http') and any(s in href for s in TARGET_SITES):
                links.append(href)
            if len(links) >= 5:
                break
        return links
    except Exception as e:
        log.warning(f'DDG search failed for "{query}": {e}')
        return []


def fetch_page(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        log.warning(f'Fetch failed {url}: {e}')
    return None


def get_parsers_for(url: str):
    """Return an ordered list of parsers to try for this URL — site-specific
    parsers first, GenericParser always last as a fallback."""
    chain = []
    for parser in PARSERS:
        if parser.can_parse(url) and type(parser).__name__ != 'GenericParser':
            chain.append(parser)
    chain.append(PARSERS[-1])  # generic JSON-LD fallback
    return chain


def run_agent():
    log.info('=== Agent run starting ===')

    if not os.path.exists(DB_PATH):
        log.error(f'Database not found at {DB_PATH}. Run flask init-db and flask seed-recipes first.')
        return

    db = get_db()
    added_count = 0

    city_rows = {row['slug']: row['id'] for row in db.execute('SELECT id, slug FROM cities').fetchall()}

    # Pick at least MIN_SITES_PER_RUN distinct sites to consult this run.
    sites_for_run = random.sample(
        TARGET_SITES, min(MIN_SITES_PER_RUN, len(TARGET_SITES))
    )
    log.info(f'This run will consult {len(sites_for_run)} sites: {", ".join(sites_for_run)}')

    # Discover candidate URLs by reading each site's sitemap.xml. This is
    # far more reliable than scraping search engines, which rate-limit hard.
    candidates: list[tuple[str, str]] = []  # (site, url)
    for site in sites_for_run:
        try:
            urls = discover_site_urls(site, max_urls=80)
        except Exception as e:
            log.warning(f'Discovery failed for {site}: {e}')
            urls = []
        for u in urls:
            candidates.append((site, u))
        time.sleep(REQUEST_DELAY)

    if not candidates:
        log.warning('No candidate URLs discovered. Aborting run.')
        db.close()
        return

    def pick_city_for_text(*texts: str):
        hay = ' '.join(t.lower() for t in texts if t)
        for city in CITIES:
            for kw in city['keywords']:
                if kw.lower() in hay:
                    return city
        return None

    random.shuffle(candidates)
    log.info(f'Discovered {len(candidates)} candidate URLs across {len(sites_for_run)} sites')

    for site, url in candidates:
        if added_count >= MAX_NEW_PER_RUN:
            break

        if url_already_seen(db, url):
            log.debug(f'Already seen: {url}')
            continue

        # Quick URL-slug city check; if no hint we still fetch + check content
        url_city = pick_city_for_text(url)

        html = fetch_page(url)
        time.sleep(REQUEST_DELAY)
        if not html:
            log_run(db, url, 'error', 'fetch failed')
            continue

        recipe = None
        for parser in get_parsers_for(url):
            recipe = parser.parse(url, html)
            if recipe and recipe.get('name'):
                break

        if not recipe or not recipe.get('name'):
            log_run(db, url, 'rejected', 'parse returned nothing')
            continue

        # Decide which city this recipe belongs to. URL hint wins; otherwise
        # check the parsed name/description for a cuisine keyword.
        city = url_city or pick_city_for_text(recipe.get('name', ''), recipe.get('description', ''))
        if not city:
            log_run(db, url, 'rejected', 'no city match')
            continue
        city_id = city_rows.get(city['slug'])
        if not city_id:
            continue

        query = f'{site} {url} {recipe.get("name","")}'

        veg_ok, veg_reason = is_vegetarian(recipe)
        if not veg_ok:
            log_run(db, url, 'rejected', f'non-veg: {veg_reason}')
            log.info(f'Rejected non-veg [{recipe.get("name","?")}]: {veg_reason}')
            continue

        if is_duplicate(db, city_id, recipe):
            log_run(db, url, 'duplicate', normalise_name(recipe['name']))
            log.info(f'Duplicate: {recipe["name"]}')
            continue

        # Ensure unique slug
        base_slug = recipe['slug'] or parser.slugify(recipe['name'])
        slug = base_slug
        suffix = 1
        while db.execute('SELECT id FROM recipes WHERE slug = ?', (slug,)).fetchone():
            slug = f'{base_slug}-{suffix}'
            suffix += 1

        cat = guess_category(recipe, query)
        chash = content_hash(recipe)

        try:
            db.execute('''
                INSERT INTO recipes
                (city_id, name, slug, category, description, ingredients,
                 instructions, prep_time_mins, cook_time_mins, servings,
                 source_url, author_credit, is_verified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            ''', (
                city_id,
                recipe['name'],
                slug,
                cat,
                recipe.get('description', ''),
                json.dumps(recipe.get('ingredients', [])),
                json.dumps(recipe.get('instructions', [])),
                recipe.get('prep_time_mins'),
                recipe.get('cook_time_mins'),
                recipe.get('servings'),
                recipe['source_url'],
                recipe.get('author_credit', 'Unknown'),
            ))
            db.commit()
            log_run(db, url, 'added', chash)
            added_count += 1
            log.info(f'Added [{city["name"]}] {recipe["name"]}')
        except Exception as e:
            log_run(db, url, 'error', str(e))
            log.warning(f'DB insert failed for {recipe["name"]}: {e}')

    if added_count > 0:
        try:
            from agent.exporter import export_finds, git_push_finds
            total = export_finds(db)
            log.info(f'Exported {total} agent-discovered recipes to agent_finds.json')
            ok = git_push_finds(f'agent: add {added_count} new recipe(s) (total {total})')
            if ok:
                log.info('Pushed agent_finds.json to GitHub — Render will redeploy.')
            else:
                log.warning('git push failed — check logs above.')
        except Exception as e:
            log.warning(f'Auto-push failed: {e}')

    db.close()
    log.info(f'=== Agent run complete. Added {added_count} recipes. ===')


if __name__ == '__main__':
    log.info(f'Recipe Agent starting. Will run every {RUN_INTERVAL_HOURS} hours.')
    log.info(f'Database: {DB_PATH}')

    run_agent()  # run immediately on start

    schedule.every(RUN_INTERVAL_HOURS).hours.do(run_agent)
    while True:
        schedule.run_pending()
        time.sleep(60)
