import json
from flask import Blueprint, render_template, request, abort
from ..database import get_db

bp = Blueprint('web', __name__)

CATEGORY_LABELS = {
    'appetizer': 'Appetizers',
    'entree': 'Entree',
    'dessert': 'Desserts',
    'drink': 'Drinks',
}
CATEGORY_ORDER = ['appetizer', 'entree', 'dessert', 'drink']


def _parse_recipe(row):
    r = dict(row)
    r['ingredients'] = json.loads(r['ingredients'])
    r['instructions'] = json.loads(r['instructions'])
    return r


@bp.route('/')
def index():
    db = get_db()
    cities = db.execute('''
        SELECT c.*, COUNT(r.id) AS recipe_count
        FROM cities c
        LEFT JOIN recipes r ON r.city_id = c.id AND r.is_verified = 1
        GROUP BY c.id
        ORDER BY c.name
    ''').fetchall()
    return render_template('index.html', cities=cities)


@bp.route('/city/<slug>')
def city(slug):
    db = get_db()
    city_row = db.execute('SELECT * FROM cities WHERE slug = ?', (slug,)).fetchone()
    if not city_row:
        abort(404)

    recipes_raw = db.execute('''
        SELECT r.*, c.name AS city_name, c.slug AS city_slug
        FROM recipes r
        JOIN cities c ON c.id = r.city_id
        WHERE c.slug = ? AND r.is_verified = 1
        ORDER BY r.name
    ''', (slug,)).fetchall()

    by_category = {cat: [] for cat in CATEGORY_ORDER}
    for row in recipes_raw:
        r = _parse_recipe(row)
        cat = r['category']
        if cat in by_category:
            by_category[cat].append(r)

    return render_template('city.html',
                           city=dict(city_row),
                           by_category=by_category,
                           category_labels=CATEGORY_LABELS,
                           category_order=CATEGORY_ORDER)


@bp.route('/recipe/<slug>')
def recipe(slug):
    db = get_db()
    row = db.execute('''
        SELECT r.*, c.name AS city_name, c.slug AS city_slug
        FROM recipes r
        JOIN cities c ON c.id = r.city_id
        WHERE r.slug = ?
    ''', (slug,)).fetchone()
    if not row:
        abort(404)
    recipe_data = _parse_recipe(row)
    return render_template('recipe.html', recipe=recipe_data,
                           category_labels=CATEGORY_LABELS)


@bp.route('/search')
def search():
    db = get_db()
    q = request.args.get('q', '').strip()
    city_filter = request.args.get('city', '').strip()
    cat_filter = request.args.get('category', '').strip()

    results = []
    if q or city_filter or cat_filter:
        where_clauses = ['r.is_verified = 1']
        params = []

        if q:
            # FTS5 match
            fts_ids = db.execute(
                "SELECT rowid FROM recipes_fts WHERE recipes_fts MATCH ? ORDER BY rank",
                (q + '*',)
            ).fetchall()
            if fts_ids:
                id_list = ','.join(str(row['rowid']) for row in fts_ids)
                where_clauses.append(f'r.id IN ({id_list})')
            else:
                # fallback LIKE search
                where_clauses.append('(r.name LIKE ? OR r.description LIKE ?)')
                params += [f'%{q}%', f'%{q}%']

        if city_filter:
            where_clauses.append('c.slug = ?')
            params.append(city_filter)

        if cat_filter:
            where_clauses.append('r.category = ?')
            params.append(cat_filter)

        where_sql = ' AND '.join(where_clauses)
        rows = db.execute(f'''
            SELECT r.*, c.name AS city_name, c.slug AS city_slug
            FROM recipes r
            JOIN cities c ON c.id = r.city_id
            WHERE {where_sql}
            ORDER BY r.name
            LIMIT 60
        ''', params).fetchall()

        for row in rows:
            r = dict(row)
            r['ingredients'] = json.loads(r['ingredients'])
            results.append(r)

    cities = db.execute('SELECT slug, name FROM cities ORDER BY name').fetchall()
    return render_template('search.html',
                           results=results,
                           q=q,
                           city_filter=city_filter,
                           cat_filter=cat_filter,
                           cities=cities,
                           category_labels=CATEGORY_LABELS,
                           categories=CATEGORY_ORDER)


@bp.route('/menu-builder')
def menu_builder():
    db = get_db()
    cities = db.execute('SELECT slug, name FROM cities ORDER BY name').fetchall()
    recipes_raw = db.execute('''
        SELECT r.id, r.name, r.slug, r.category, r.prep_time_mins, r.cook_time_mins,
               c.name AS city_name, c.slug AS city_slug
        FROM recipes r
        JOIN cities c ON c.id = r.city_id
        WHERE r.is_verified = 1
        ORDER BY r.category, r.name
    ''').fetchall()

    recipes_by_category = {cat: [] for cat in CATEGORY_ORDER}
    for row in recipes_raw:
        r = dict(row)
        if r['category'] in recipes_by_category:
            recipes_by_category[r['category']].append(r)

    return render_template('menu_builder.html',
                           cities=cities,
                           recipes_by_category=recipes_by_category,
                           category_labels=CATEGORY_LABELS,
                           category_order=CATEGORY_ORDER)


@bp.route('/menu/<int:menu_id>')
def view_menu(menu_id):
    db = get_db()
    menu_row = db.execute('SELECT * FROM saved_menus WHERE id = ?', (menu_id,)).fetchone()
    if not menu_row:
        abort(404)
    menu = dict(menu_row)
    lunch_ids = json.loads(menu['lunch_ids'])
    dinner_ids = json.loads(menu['dinner_ids'])

    def fetch_recipes(ids):
        if not ids:
            return []
        placeholders = ','.join('?' * len(ids))
        rows = db.execute(f'''
            SELECT r.*, c.name AS city_name, c.slug AS city_slug
            FROM recipes r JOIN cities c ON c.id = r.city_id
            WHERE r.id IN ({placeholders})
        ''', ids).fetchall()
        return [_parse_recipe(r) for r in rows]

    menu['lunch_recipes'] = fetch_recipes(lunch_ids)
    menu['dinner_recipes'] = fetch_recipes(dinner_ids)
    return render_template('view_menu.html', menu=menu,
                           category_labels=CATEGORY_LABELS)


@bp.route('/menu/<int:menu_id>/print')
def print_menu(menu_id):
    db = get_db()
    menu_row = db.execute('SELECT * FROM saved_menus WHERE id = ?', (menu_id,)).fetchone()
    if not menu_row:
        abort(404)
    menu = dict(menu_row)
    lunch_ids = json.loads(menu['lunch_ids'])
    dinner_ids = json.loads(menu['dinner_ids'])

    def fetch_recipes(ids):
        if not ids:
            return []
        placeholders = ','.join('?' * len(ids))
        rows = db.execute(f'''
            SELECT r.*, c.name AS city_name, c.slug AS city_slug
            FROM recipes r JOIN cities c ON c.id = r.city_id
            WHERE r.id IN ({placeholders})
        ''', ids).fetchall()
        return [_parse_recipe(r) for r in rows]

    menu['lunch_recipes'] = fetch_recipes(lunch_ids)
    menu['dinner_recipes'] = fetch_recipes(dinner_ids)
    return render_template('menu_print.html', menu=menu,
                           category_labels=CATEGORY_LABELS)
