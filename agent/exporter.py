"""
Exports agent-discovered (is_verified=0) recipes to agent_finds.json so
they can be seeded into the Render deployment alongside seed_recipes.json.
Also commits + pushes to GitHub so Render auto-deploys.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import logging
from typing import Optional

log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINDS_PATH = os.path.join(PROJECT_ROOT, 'app', 'agent_finds.json')


def export_finds(db: sqlite3.Connection) -> int:
    """Write all agent-discovered recipes (is_verified=0) to agent_finds.json.
    Returns the number of recipes written."""
    rows = db.execute('''
        SELECT r.name, r.slug, r.category, r.description,
               r.ingredients, r.instructions,
               r.prep_time_mins, r.cook_time_mins, r.servings,
               r.source_url, r.author_credit,
               c.slug AS city_slug
        FROM recipes r
        JOIN cities c ON c.id = r.city_id
        WHERE r.is_verified = 0
        ORDER BY c.slug, r.name
    ''').fetchall()

    by_city: dict[str, list[dict]] = {}
    for row in rows:
        d = dict(row)
        city_slug = d.pop('city_slug')
        d['ingredients'] = json.loads(d['ingredients'])
        d['instructions'] = json.loads(d['instructions'])
        by_city.setdefault(city_slug, []).append(d)

    payload = {
        'cities': [
            {'slug': city_slug, 'recipes': recipes}
            for city_slug, recipes in sorted(by_city.items())
        ]
    }

    with open(FINDS_PATH, 'w') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write('\n')

    return len(rows)


def _run(cmd: list[str], cwd: str) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip()
    return p.returncode, out


def git_push_finds(commit_message: str) -> bool:
    """Stage agent_finds.json, commit, pull --rebase, push. Returns True on success."""
    rc, out = _run(['git', 'status', '--porcelain', 'app/agent_finds.json'], PROJECT_ROOT)
    if rc != 0:
        log.warning(f'git status failed: {out}')
        return False
    if not out.strip():
        log.info('No changes in agent_finds.json — nothing to push.')
        return True

    steps = [
        ['git', 'add', 'app/agent_finds.json'],
        ['git', 'commit', '-m', commit_message],
        ['git', 'pull', '--rebase', 'origin', 'main'],
        ['git', 'push', 'origin', 'HEAD:main'],
    ]
    for cmd in steps:
        rc, out = _run(cmd, PROJECT_ROOT)
        if rc != 0:
            log.warning(f'git step failed ({" ".join(cmd)}): {out}')
            return False
        log.info(f'git: {" ".join(cmd)} -> ok')
    return True
