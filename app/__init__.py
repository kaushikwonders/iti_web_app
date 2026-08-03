import os
from flask import Flask
from app.config import Config
from app.extensions import db, migrate, login_manager


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    os.makedirs(
        app.config["EVIDENCE_UPLOAD_FOLDER"],
        exist_ok=True,
    )
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    from app.auth.routes import auth_bp
    from app.admin.routes import admin_bp
    from app.learners.routes import learners_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(learners_bp, url_prefix="/learners")

    @app.route("/")
    def index():
        from flask import redirect, url_for
        return redirect(url_for("auth.login"))

    return app
