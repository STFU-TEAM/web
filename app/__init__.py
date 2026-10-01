from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import Config
from app.db import init_db, r


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    # Coolify / Traefik sit in front of us
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    init_db(app)

    from app import filters
    filters.register(app)

    from app.auth import bp as auth_bp
    from app.routes.main import bp as main_bp
    from app.routes.play import bp as play_bp
    from app.routes.social import bp as social_bp
    from app.routes.admin import bp as admin_bp
    from app.routes.battles import bp as battles_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(play_bp)
    app.register_blueprint(social_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(battles_bp)

    @app.get("/healthz")
    def healthz():
        r().ping()
        return {"ok": True}

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404, message="This page doesn't exist."), 404

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403, message="This Discord account can't access this page."), 403

    @app.errorhandler(500)
    def server_error(_):
        return render_template("error.html", code=500, message="Something broke on our side. Try again in a moment."), 500

    return app
