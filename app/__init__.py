from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from config import Config

db = SQLAlchemy()


def create_app():
    app = Flask(
        __name__,
        instance_relative_config=True,
    )

    app.config.from_object(Config)

    db.init_app(app)

    from app.routes.crawler import crawler_bp

    app.register_blueprint(crawler_bp)

    with app.app_context():
        db.create_all()

    return app
