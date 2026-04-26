import sqlite3
import click
from flask import current_app, g


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(
            current_app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with current_app.open_resource('schema.sql') as f:
        db.executescript(f.read().decode('utf8'))


@click.command('init-db')
def init_db_command():
    init_db()
    click.echo('Database initialized.')


def seed_recipes():
    import json, os
    db = get_db()

    seed_path = os.path.join(os.path.dirname(__file__), 'seed_recipes.json')
    with open(seed_path) as f:
        data = json.load(f)

    for city_data in data['cities']:
        existing = db.execute('SELECT id FROM cities WHERE slug = ?', (city_data['slug'],)).fetchone()
        if not existing:
            db.execute(
                'INSERT INTO cities (slug, name, description, image_file) VALUES (?, ?, ?, ?)',
                (city_data['slug'], city_data['name'], city_data['description'], city_data['image_file'])
            )

    db.commit()

    for city_data in data['cities']:
        city_row = db.execute('SELECT id FROM cities WHERE slug = ?', (city_data['slug'],)).fetchone()
        city_id = city_row['id']
        for recipe in city_data['recipes']:
            existing = db.execute('SELECT id FROM recipes WHERE slug = ?', (recipe['slug'],)).fetchone()
            if not existing:
                db.execute(
                    '''INSERT INTO recipes
                       (city_id, name, slug, category, description, ingredients, instructions,
                        prep_time_mins, cook_time_mins, servings, source_url, author_credit, is_verified)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)''',
                    (
                        city_id,
                        recipe['name'],
                        recipe['slug'],
                        recipe['category'],
                        recipe['description'],
                        json.dumps(recipe['ingredients']),
                        json.dumps(recipe['instructions']),
                        recipe.get('prep_time_mins'),
                        recipe.get('cook_time_mins'),
                        recipe.get('servings'),
                        recipe.get('source_url'),
                        recipe.get('author_credit'),
                    )
                )

    db.commit()


@click.command('seed-recipes')
def seed_recipes_command():
    seed_recipes()
    click.echo('Recipes seeded.')


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_recipes_command)
