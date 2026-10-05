import json
import os
from flask import Blueprint, jsonify, request, abort
from ..database import get_db

bp = Blueprint('api', __name__, url_prefix='/api')

AI_MODEL = 'claude-haiku-4-5-20251001'
AI_SYSTEM = (
    "You are a chef helping build vegetarian Indian menus from a fixed catalog "
    "of recipes. The user provides a natural-language request; you pick dishes "
    "from the catalog that best fit. Respond ONLY with valid JSON in this exact "
    "shape:\n"
    '{"lunch": [<recipe ids>], "dinner": [<recipe ids>], "explanation": "<one to two sentences>"}\n'
    "Rules:\n"
    "- Use only ids that appear in the provided catalog.\n"
    "- If the user asks only for a lunch or only for a dinner, leave the other array empty.\n"
    "- Prefer a balanced mix of appetizer, entree, dessert, and drink unless the user says otherwise.\n"
    "- 3-6 dishes per meal by default.\n"
    "- The explanation should call out the theme, city origin, or dietary notes.\n"
    "- Return NOTHING except the JSON object."
)


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


@bp.route('/menu/ai-suggest', methods=['POST'])
def api_ai_suggest():
    """AI-powered menu builder. Accepts {prompt: str}, returns a suggested
    lunch/dinner selection using the current recipe catalog."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return jsonify(error='ANTHROPIC_API_KEY not set on the server.'), 503

    payload = request.get_json(silent=True) or {}
    user_prompt = (payload.get('prompt') or '').strip()
    if not user_prompt:
        return jsonify(error='Prompt is required.'), 400
    if len(user_prompt) > 1000:
        return jsonify(error='Prompt is too long (max 1000 chars).'), 400

    db = get_db()
    rows = db.execute('''
        SELECT r.id, r.name, r.category, c.name AS city
        FROM recipes r JOIN cities c ON c.id = r.city_id
        ORDER BY r.name
    ''').fetchall()
    catalog = [
        {'id': r['id'], 'name': r['name'], 'city': r['city'], 'category': r['category']}
        for r in rows
    ]
    valid_ids = {r['id'] for r in catalog}

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        message = client.messages.create(
            model=AI_MODEL,
            max_tokens=1024,
            system=AI_SYSTEM,
            messages=[{
                'role': 'user',
                'content': (
                    f"User request: {user_prompt}\n\n"
                    f"Recipe catalog (JSON):\n{json.dumps(catalog)}"
                )
            }],
        )
        raw = message.content[0].text.strip()
    except Exception as e:
        return jsonify(error=f'AI call failed: {e}'), 502

    # Strip markdown fences if the model included them
    if raw.startswith('```'):
        raw = raw.strip('`')
        if raw.lower().startswith('json'):
            raw = raw[4:].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return jsonify(error='AI returned malformed JSON.', raw=raw), 502

    lunch = [int(i) for i in data.get('lunch') or [] if int(i) in valid_ids]
    dinner = [int(i) for i in data.get('dinner') or [] if int(i) in valid_ids]
    explanation = str(data.get('explanation') or '').strip()[:600]

    # Hydrate ids into recipe cards the frontend can render directly.
    def hydrate(ids):
        if not ids:
            return []
        placeholders = ','.join('?' * len(ids))
        recipe_rows = db.execute(f'''
            SELECT r.id, r.name, r.category, c.name AS city_name, c.slug AS city_slug
            FROM recipes r JOIN cities c ON c.id = r.city_id
            WHERE r.id IN ({placeholders})
        ''', ids).fetchall()
        by_id = {r['id']: dict(r) for r in recipe_rows}
        return [by_id[i] for i in ids if i in by_id]

    return jsonify(
        lunch=hydrate(lunch),
        dinner=hydrate(dinner),
        explanation=explanation,
    )


@bp.route('/ingredients', methods=['POST'])
def api_ingredients():
    """Given {ids: [1,2,3]}, return aggregated ingredient groups."""
    payload = request.get_json(silent=True) or {}
    ids = payload.get('ids') or []
    ids = [int(i) for i in ids if str(i).isdigit()]
    if not ids:
        return jsonify(groups=[])

    db = get_db()
    placeholders = ','.join('?' * len(ids))
    rows = db.execute(
        f'SELECT id, name, ingredients FROM recipes WHERE id IN ({placeholders})',
        ids
    ).fetchall()

    groups = {}
    for row in rows:
        for ing in json.loads(row['ingredients']):
            if isinstance(ing, dict):
                item = (ing.get('item') or '').strip()
                qty = (ing.get('qty') or '').strip()
            else:
                item, qty = str(ing).strip(), ''
            if not item:
                continue
            key = item.lower()
            if key not in groups:
                groups[key] = {'item': item, 'entries': []}
            groups[key]['entries'].append({'qty': qty, 'recipe': row['name']})

    return jsonify(groups=sorted(groups.values(), key=lambda g: g['item'].lower()))


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
