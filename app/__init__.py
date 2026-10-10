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
    from app import perf
    perf.install(app)  # registered first so its compression runs after every other after_request hook
    from app import logs
    logs.install(app, r())  # errors and warnings land in the admin Logs tab
    from app.game import events
    events._cache.update(at=0.0, event=None)  # a fresh app never trusts another app's Redis

    from app import filters
    filters.register(app)

    from app.auth import bp as auth_bp
    from app.routes.main import bp as main_bp
    from app.routes.play import bp as play_bp
    from app.routes.social import bp as social_bp
    from app.routes.admin import bp as admin_bp
    from app.routes.battles import bp as battles_bp
    from app.routes.gangs import bp as gangs_bp
    from app.routes.progress import bp as progress_bp
    from app.routes.trades import bp as trades_bp
    from app.routes.community import bp as community_bp
    from app.routes.auction import bp as auction_bp
    from app.routes.journey import bp as journey_bp
    from app.routes.coop import bp as coop_bp
    from app.routes.chat import bp as chat_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(play_bp)
    app.register_blueprint(social_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(battles_bp)
    app.register_blueprint(gangs_bp)
    app.register_blueprint(progress_bp)
    app.register_blueprint(trades_bp)
    app.register_blueprint(community_bp)
    app.register_blueprint(auction_bp)
    app.register_blueprint(journey_bp)
    app.register_blueprint(coop_bp)
    app.register_blueprint(chat_bp)

    @app.before_request
    def live_state():
        """Read the running event (the fight engine applies its boost) and send due notifications."""
        from flask import request
        if request.endpoint in (None, "static", "healthz"):
            return
        from flask import session
        from app import social
        from app.game import events
        try:
            events.current(r())
            social.tick(seen=session.get("uid") if not request.path.startswith("/push/") else None)
        except Exception:
            app.logger.exception("live state")

    @app.get("/healthz")
    def healthz():
        r().ping()
        return {"ok": True}

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404, message="This page doesn't exist."), 404

    @app.errorhandler(403)
    def forbidden(e):
        message = e.description if e.description and "banned" in e.description else "This account can't access this page."
        return render_template("error.html", code=403, message=message), 403

    @app.errorhandler(500)
    def server_error(_):
        return render_template("error.html", code=500, message="Something broke on our side. Try again in a moment."), 500

    return app
