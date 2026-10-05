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
    """Stage agent_finds.json, commit, pull --rebase, push. Other local
    edits are stashed around the pull so a dirty tree does not block the
    push, then restored afterwards. Returns True on success."""
    rc, out = _run(['git', 'status', '--porcelain', 'app/agent_finds.json'], PROJECT_ROOT)
    if rc != 0:
        log.warning(f'git status failed: {out}')
        return False
    if not out.strip():
        log.info('No changes in agent_finds.json — nothing to push.')
        return True

    # Commit the finds first.
    for cmd in [
        ['git', 'add', 'app/agent_finds.json'],
        ['git', 'commit', '-m', commit_message],
    ]:
        rc, out = _run(cmd, PROJECT_ROOT)
        if rc != 0:
            log.warning(f'git step failed ({" ".join(cmd)}): {out}')
            return False
        log.info(f'git: {" ".join(cmd)} -> ok')

    # Stash any unrelated local edits (so pull --rebase can proceed).
    rc, dirty_out = _run(['git', 'status', '--porcelain'], PROJECT_ROOT)
    stashed = False
    if rc == 0 and dirty_out.strip():
        rc, out = _run(
            ['git', 'stash', 'push', '-u', '-m', 'auto-export-stash'],
            PROJECT_ROOT,
        )
        if rc == 0 and 'No local changes' not in out:
            stashed = True
            log.info('git: stashed unrelated local changes')
        else:
            log.warning(f'git stash failed: {out}')

    # Pull + push.
    ok = True
    for cmd in [
        ['git', 'pull', '--rebase', 'origin', 'main'],
        ['git', 'push', 'origin', 'HEAD:main'],
    ]:
        rc, out = _run(cmd, PROJECT_ROOT)
        if rc != 0:
            log.warning(f'git step failed ({" ".join(cmd)}): {out}')
            ok = False
            break
        log.info(f'git: {" ".join(cmd)} -> ok')

    # Restore any stashed edits.
    if stashed:
        rc, out = _run(['git', 'stash', 'pop'], PROJECT_ROOT)
        if rc != 0:
            log.warning(f'git stash pop failed: {out}')
            ok = False
        else:
            log.info('git: restored stashed local changes')

    return ok
