"""
Admin GUI for Tastes of India — protected by HTTP Basic Auth.
Access at /admin/  (credentials in env vars ADMIN_USER, ADMIN_PASSWORD).
"""
import json
import os
from functools import wraps
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    abort, Response, flash, current_app,
)
from ..database import get_db

bp = Blueprint('admin', __name__, url_prefix='/admin')

CATEGORIES = ['appetizer', 'entree', 'dessert', 'drink']


def _check_auth(user, pw):
    expected_user = os.environ.get('ADMIN_USER', 'admin')
    expected_pw = os.environ.get('ADMIN_PASSWORD', 'changeme')
    return user == expected_user and pw == expected_pw


def _auth_challenge():
    return Response(
        'Authentication required.',
        401,
        {'WWW-Authenticate': 'Basic realm="Tastes of India Admin"'},
    )


def requires_admin(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        if not auth or not _check_auth(auth.username, auth.password):
            return _auth_challenge()
        return f(*args, **kwargs)
    return wrapped


def _parse_lines(text):
    """Split a textarea on newlines, drop blanks, strip."""
    return [ln.strip() for ln in (text or '').splitlines() if ln.strip()]


def _parse_ingredients(text):
    """Each line is either 'qty | item' or just 'item'."""
    out = []
    for ln in _parse_lines(text):
        if '|' in ln:
            qty, item = ln.split('|', 1)
            out.append({'qty': qty.strip(), 'item': item.strip()})
        else:
            out.append({'qty': '', 'item': ln})
    return out


def _format_ingredients(ings):
    """Inverse of _parse_ingredients — for the edit textarea."""
    lines = []
    for ing in ings or []:
        if isinstance(ing, dict):
            qty = (ing.get('qty') or '').strip()
            item = (ing.get('item') or '').strip()
            lines.append(f'{qty} | {item}' if qty else item)
        else:
            lines.append(str(ing))
    return '\n'.join(lines)


@bp.route('/')
@requires_admin
def index():
    db = get_db()
    q = request.args.get('q', '').strip()
    city_filter = request.args.get('city', '').strip()
    verified_filter = request.args.get('verified', '').strip()  # '', '0', '1'

    where = []
    params = []
    if q:
        where.append('(r.name LIKE ? OR r.description LIKE ?)')
        params += [f'%{q}%', f'%{q}%']
    if city_filter:
        where.append('c.slug = ?')
        params.append(city_filter)
    if verified_filter in ('0', '1'):
        where.append('r.is_verified = ?')
        params.append(int(verified_filter))

    where_sql = ' AND '.join(where) if where else '1=1'
    rows = db.execute(f'''
        SELECT r.id, r.name, r.slug, r.category, r.is_verified,
               r.source_url, r.author_credit,
               c.name AS city_name, c.slug AS city_slug
        FROM recipes r
        JOIN cities c ON c.id = r.city_id
        WHERE {where_sql}
        ORDER BY r.is_verified ASC, c.name, r.name
        LIMIT 500
    ''', params).fetchall()

    cities = db.execute('SELECT slug, name FROM cities ORDER BY name').fetchall()
    counts = db.execute('''
        SELECT
          SUM(CASE WHEN is_verified = 1 THEN 1 ELSE 0 END) AS verified,
          SUM(CASE WHEN is_verified = 0 THEN 1 ELSE 0 END) AS unverified,
          COUNT(*) AS total
        FROM recipes
    ''').fetchone()

    return render_template('admin/list.html',
                           recipes=rows,
                           cities=cities,
                           counts=counts,
                           q=q,
                           city_filter=city_filter,
                           verified_filter=verified_filter)


@bp.route('/recipe/<int:recipe_id>', methods=['GET', 'POST'])
@requires_admin
def edit(recipe_id):
    db = get_db()
    row = db.execute('''
        SELECT r.*, c.slug AS city_slug, c.name AS city_name
        FROM recipes r JOIN cities c ON c.id = r.city_id
        WHERE r.id = ?
    ''', (recipe_id,)).fetchone()
    if not row:
        abort(404)

    if request.method == 'POST':
        f = request.form
        name = f.get('name', '').strip()
        slug = f.get('slug', '').strip()
        category = f.get('category', '').strip()
        description = f.get('description', '').strip()
        author_credit = f.get('author_credit', '').strip()
        source_url = f.get('source_url', '').strip()
        is_verified = 1 if f.get('is_verified') == 'on' else 0
        city_id = int(f.get('city_id'))

        ingredients = _parse_ingredients(f.get('ingredients', ''))
        instructions = _parse_lines(f.get('instructions', ''))

        def _opt_int(s):
            try:
                return int(s) if s.strip() else None
            except ValueError:
                return None

        prep_time = _opt_int(f.get('prep_time_mins', ''))
        cook_time = _opt_int(f.get('cook_time_mins', ''))
        servings = _opt_int(f.get('servings', ''))

        if not name or not slug or category not in CATEGORIES:
            flash('Name, slug, and a valid category are required.', 'error')
            return redirect(url_for('admin.edit', recipe_id=recipe_id))

        # Slug uniqueness (allow keeping own slug)
        clash = db.execute(
            'SELECT id FROM recipes WHERE slug = ? AND id != ?',
            (slug, recipe_id)
        ).fetchone()
        if clash:
            flash(f'Slug "{slug}" already in use by recipe #{clash["id"]}.', 'error')
            return redirect(url_for('admin.edit', recipe_id=recipe_id))

        db.execute('''
            UPDATE recipes SET
              name=?, slug=?, category=?, description=?,
              ingredients=?, instructions=?,
              prep_time_mins=?, cook_time_mins=?, servings=?,
              source_url=?, author_credit=?,
              is_verified=?, city_id=?,
              updated_at=datetime('now')
            WHERE id=?
        ''', (
            name, slug, category, description,
            json.dumps(ingredients), json.dumps(instructions),
            prep_time, cook_time, servings,
            source_url, author_credit,
            is_verified, city_id, recipe_id,
        ))
        db.commit()
        flash(f'Saved "{name}".', 'success')
        return redirect(url_for('admin.edit', recipe_id=recipe_id))

    cities = db.execute('SELECT id, slug, name FROM cities ORDER BY name').fetchall()
    recipe = dict(row)
    recipe['ingredients'] = json.loads(recipe['ingredients'])
    recipe['instructions'] = json.loads(recipe['instructions'])
    recipe['ingredients_text'] = _format_ingredients(recipe['ingredients'])
    recipe['instructions_text'] = '\n'.join(recipe['instructions'])

    return render_template('admin/edit.html',
                           recipe=recipe, cities=cities, categories=CATEGORIES)


@bp.route('/recipe/<int:recipe_id>/verify', methods=['POST'])
@requires_admin
def toggle_verify(recipe_id):
    db = get_db()
    row = db.execute('SELECT is_verified FROM recipes WHERE id = ?', (recipe_id,)).fetchone()
    if not row:
        abort(404)
    new_val = 0 if row['is_verified'] else 1
    db.execute("UPDATE recipes SET is_verified=?, updated_at=datetime('now') WHERE id=?",
               (new_val, recipe_id))
    db.commit()
    flash(f'Recipe #{recipe_id} marked {"verified" if new_val else "unverified"}.', 'success')
    return redirect(request.referrer or url_for('admin.index'))


@bp.route('/recipe/<int:recipe_id>/delete', methods=['POST'])
@requires_admin
def delete(recipe_id):
    db = get_db()
    row = db.execute('SELECT name FROM recipes WHERE id = ?', (recipe_id,)).fetchone()
    if not row:
        abort(404)
    db.execute('DELETE FROM recipes WHERE id = ?', (recipe_id,))
    db.commit()
    flash(f'Deleted "{row["name"]}".', 'success')
    return redirect(url_for('admin.index'))


@bp.route('/sync', methods=['POST'])
@requires_admin
def sync():
    """Re-export agent_finds.json and push to GitHub so Render redeploys."""
    db = get_db()
    try:
        from agent.exporter import export_finds, git_push_finds
        n = export_finds(db)
        ok = git_push_finds(f'admin: sync {n} agent finds after manual edits')
        if ok:
            flash(f'Exported {n} recipes and pushed to Render.', 'success')
        else:
            flash('Export wrote the file but git push failed — check server logs.', 'error')
    except Exception as e:
        flash(f'Sync failed: {e}', 'error')
    return redirect(url_for('admin.index'))
