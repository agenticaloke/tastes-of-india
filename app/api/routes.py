import json
from flask import Blueprint, jsonify, request, abort
from ..database import get_db

bp = Blueprint('api', __name__, url_prefix='/api')


def _parse_recipe(row):
    r = dict(row)
    r['ingredients'] = json.loads(r['ingredients'])
    r['instructions'] = json.loads(r['instructions'])
    return r


@bp.route('/cities')
def api_cities():
    db = get_db()
    rows = db.execute('''
        SELECT c.*, COUNT(r.id) AS recipe_count
        FROM cities c
        LEFT JOIN recipes r ON r.city_id = c.id AND r.is_verified = 1
        GROUP BY c.id ORDER BY c.name
    ''').fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route('/recipes')
def api_recipes():
    db = get_db()
    city = request.args.get('city', '')
    category = request.args.get('category', '')
    where = ['r.is_verified = 1']
    params = []
    if city:
        where.append('c.slug = ?')
        params.append(city)
    if category:
        where.append('r.category = ?')
        params.append(category)
    where_sql = ' AND '.join(where)
    rows = db.execute(f'''
        SELECT r.id, r.name, r.slug, r.category, r.description,
               r.prep_time_mins, r.cook_time_mins, r.servings,
               r.source_url, r.author_credit, r.is_verified,
               c.name AS city_name, c.slug AS city_slug
        FROM recipes r JOIN cities c ON c.id = r.city_id
        WHERE {where_sql}
        ORDER BY r.category, r.name
    ''', params).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route('/recipe/<int:recipe_id>')
def api_recipe(recipe_id):
    db = get_db()
    row = db.execute('''
        SELECT r.*, c.name AS city_name, c.slug AS city_slug
        FROM recipes r JOIN cities c ON c.id = r.city_id
        WHERE r.id = ?
    ''', (recipe_id,)).fetchone()
    if not row:
        abort(404)
    return jsonify(_parse_recipe(row))


@bp.route('/search')
def api_search():
    db = get_db()
    q = request.args.get('q', '').strip()
    city = request.args.get('city', '').strip()
    category = request.args.get('category', '').strip()

    where = ['r.is_verified = 1']
    params = []

    if q:
        fts_ids = db.execute(
            "SELECT rowid FROM recipes_fts WHERE recipes_fts MATCH ? ORDER BY rank",
            (q + '*',)
        ).fetchall()
        if fts_ids:
            id_list = ','.join(str(row['rowid']) for row in fts_ids)
            where.append(f'r.id IN ({id_list})')
        else:
            where.append('(r.name LIKE ? OR r.description LIKE ?)')
            params += [f'%{q}%', f'%{q}%']

    if city:
        where.append('c.slug = ?')
        params.append(city)
    if category:
        where.append('r.category = ?')
        params.append(category)

    where_sql = ' AND '.join(where)
    rows = db.execute(f'''
        SELECT r.id, r.name, r.slug, r.category, r.description,
               r.prep_time_mins, r.cook_time_mins,
               c.name AS city_name, c.slug AS city_slug
        FROM recipes r JOIN cities c ON c.id = r.city_id
        WHERE {where_sql}
        ORDER BY r.name LIMIT 40
    ''', params).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route('/menu', methods=['POST'])
def api_create_menu():
    db = get_db()
    data = request.get_json(force=True)
    title = data.get('title', '').strip()
    meal_type = data.get('meal_type', 'both')
    lunch_ids = data.get('lunch_ids', [])
    dinner_ids = data.get('dinner_ids', [])
    notes = data.get('notes', '')

    if not title:
        return jsonify({'error': 'title is required'}), 400
    if meal_type not in ('lunch', 'dinner', 'both'):
        meal_type = 'both'

    cur = db.execute(
        'INSERT INTO saved_menus (title, meal_type, lunch_ids, dinner_ids, notes) VALUES (?, ?, ?, ?, ?)',
        (title, meal_type, json.dumps(lunch_ids), json.dumps(dinner_ids), notes)
    )
    db.commit()
    return jsonify({'id': cur.lastrowid, 'title': title}), 201


@bp.route('/menu/<int:menu_id>')
def api_get_menu(menu_id):
    db = get_db()
    row = db.execute('SELECT * FROM saved_menus WHERE id = ?', (menu_id,)).fetchone()
    if not row:
        abort(404)
    menu = dict(row)
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
        return [dict(r) for r in rows]

    menu['lunch_recipes'] = fetch_recipes(lunch_ids)
    menu['dinner_recipes'] = fetch_recipes(dinner_ids)
    return jsonify(menu)


@bp.route('/menu/<int:menu_id>', methods=['DELETE'])
def api_delete_menu(menu_id):
    db = get_db()
    db.execute('DELETE FROM saved_menus WHERE id = ?', (menu_id,))
    db.commit()
    return jsonify({'deleted': menu_id})
