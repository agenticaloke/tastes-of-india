import os
from flask import Flask
from . import database


def create_app():
    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-change-me'),
        DATABASE=os.path.join(app.instance_path, 'tastes.db'),
    )

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    database.init_app(app)

    from .web import routes as web_routes
    from .api import routes as api_routes
    from .admin import routes as admin_routes

    app.register_blueprint(web_routes.bp)
    app.register_blueprint(api_routes.bp)
    app.register_blueprint(admin_routes.bp)

    return app
