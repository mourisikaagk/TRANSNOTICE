from __future__ import annotations

import hmac
import logging
import re
import secrets
import sqlite3
import zlib
from functools import wraps
from logging.handlers import RotatingFileHandler

import click
from flask import (Flask, abort, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for)

from config import Settings
from database.db import apply_migrations, close_db, connect, get_db
from scraper import demo_source
from services import account_service, notice_service, scheduler_service, weather_service
from services.account_service import AccountError
from services.collector_service import run_all
from services.notice_service import NoticeFilters
from services.source_registry import seed_demo_subscription, sync_sources
from timeutil import format_local, humanize_age, utcnow

ROUTE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,11}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    if settings.log_to_file and not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(settings.log_dir / "transitnotice.log", maxBytes=500_000, backupCount=3,
                                      encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)


def create_app(settings: Settings | None = None, clock=utcnow) -> Flask:
    settings = settings or Settings.from_env()
    configure_logging(settings)
    app = Flask(__name__)
    app.config.update(SECRET_KEY=settings.secret_key, SESSION_COOKIE_NAME="transitnotice_session",
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      MAX_CONTENT_LENGTH=64 * 1024)
    app.extensions.update(settings=settings, clock=clock, last_manual_refresh=None)
    app.teardown_appcontext(close_db)

    conn = connect(settings.database_path)
    try:
        apply_migrations(conn)
        sync_sources(conn, settings, clock())
        seed_demo_subscription(conn, settings, clock())
    finally:
        conn.close()

    register_filters(app, settings, clock)
    register_hooks(app, settings, clock)
    register_routes(app, settings, clock)
    register_cli(app, settings, clock)

    if settings.enable_scheduler and not app.testing:
        app.extensions["scheduler"] = scheduler_service.SchedulerService(settings, clock)
        app.extensions["scheduler"].start()
    return app


def register_filters(app: Flask, settings: Settings, clock) -> None:
    app.add_template_filter(lambda v, zone=True: format_local(v, settings.display_timezone, zone), "local_dt")
    app.add_template_filter(lambda v: humanize_age(v, clock()), "ago")

    app.add_template_filter(lambda route: f"rc-{zlib.crc32(str(route).encode()) % 10}", "route_class")

    @app.context_processor
    def inject():
        conn = get_db()
        user = account_service.get_user(conn, session.get("user_id"))
        if user is None:
            session.pop("user_id", None)
        demo = conn.execute("""SELECT 1 FROM sources s JOIN agencies a ON a.id = s.agency_id
                               WHERE s.enabled = 1 AND a.is_demo = 1 LIMIT 1""").fetchone()
        return {"tz_name": settings.display_timezone, "freshness_minutes": settings.freshness_minutes,
                "csrf_token": session.setdefault("csrf", secrets.token_hex(16)),
                "is_admin": bool(session.get("is_admin")), "email_enabled": settings.email_enabled,
                "current_user": user, "demo_mode": bool(demo),
                "followed": account_service.followed_routes(conn, user["id"]) if user else [],
                "weather_enabled": settings.weather_enabled}


def register_hooks(app: Flask, settings: Settings, clock) -> None:
    @app.before_request
    def csrf_protect():
        if request.method == "POST":
            sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            expected = session.get("csrf", "")
            if not expected or not hmac.compare_digest(sent, expected):
                abort(400, "Security token missing or invalid. Reload the page and try again.")

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' https://tile.openstreetmap.org; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
        return response

    @app.errorhandler(Exception)
    def handle_error(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            code, message = exc.code, exc.description
        else:
            current_app.logger.exception("Unhandled error")
            code, message = 500, "Something went wrong on our side. The error has been logged."
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error=message), code
        return render_template("error.html", code=code, message=message), code


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            if request.path.startswith("/api/"):
                return jsonify(ok=False, error="Admin sign-in required."), 401
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapper


def summarize_run(outcome: dict) -> dict:
    reports = outcome["reports"]
    return {
        "status": outcome["status"],
        "sources_checked": len(reports),
        "new": sum(r.new for r in reports), "revised": sum(r.revised for r in reports),
        "withdrawn": sum(r.withdrawn for r in reports),
        "errors": [f"{r.source_code}: {r.error}" for r in reports if r.error],
    }


def run_refresh(settings: Settings, clock, trigger: str) -> dict:
    conn = get_db()
    return summarize_run(run_all(conn, settings, clock, trigger))


def safe_next(value) -> str | None:
    """Only same-site paths are accepted as a post-login destination."""
    if isinstance(value, str) and value.startswith("/") and not value.startswith("//") \
            and "\\" not in value and len(value) <= 200 and value.isprintable():
        return value
    return None


def pins_for(notices: list[dict], url_for_notice) -> list[dict]:
    return [{"id": n["id"], "title": n["title"], "status": n["status"], "routes": n["routes"], "area": n["area"],
             "lat": n["latitude"], "lon": n["longitude"], "demo": bool(n["is_demo"]), "url": url_for_notice(n["id"])}
            for n in notices if n["latitude"] is not None]


def register_routes(app: Flask, settings: Settings, clock) -> None:
    def notice_url(notice_id: int) -> str:
        return url_for("notice_detail", notice_id=notice_id)

    map_context = {"map_tiles": settings.map_tiles_enabled, "map_center": [settings.map_center_lat, settings.map_center_lon]}

    @app.get("/")
    def index():
        filters = NoticeFilters.from_args(request.args)
        for warning in filters.warnings:
            flash(warning, "warning")
        conn, now = get_db(), clock()
        return render_template(
            "index.html", filters=filters, notices=notice_service.list_notices(conn, filters, now, settings),
            stats=notice_service.get_stats(conn, now, settings), options=notice_service.filter_options(conn),
            statuses=notice_service.STATUSES, changes=notice_service.recent_changes(conn, now))

    @app.get("/notice/<int:notice_id>")
    def notice_detail(notice_id: int):
        notice = notice_service.get_notice(get_db(), notice_id, clock(), settings)
        if notice is None:
            abort(404, "That notice does not exist.")
        return render_template("notice_detail.html", notice=notice, pins=pins_for([notice], notice_url), **map_context)

    @app.get("/api/notices")
    def api_notices():
        filters = NoticeFilters.from_args(request.args)
        notices = notice_service.list_notices(get_db(), filters, clock(), settings)
        return jsonify(ok=True, count=len(notices), warnings=filters.warnings, notices=notices)

    @app.get("/api/stats")
    def api_stats():
        return jsonify(ok=True, **notice_service.get_stats(get_db(), clock(), settings))

    @app.get("/health")
    def health():
        get_db().execute("SELECT 1")
        return jsonify(ok=True)

    @app.post("/api/refresh")
    def api_refresh():
        now = clock()
        last = current_app.extensions["last_manual_refresh"]
        if last is not None:
            wait = settings.manual_refresh_cooldown - (now - last).total_seconds()
            if wait > 0:
                return jsonify(ok=False, error=f"Sources were just checked. Try again in {int(wait) + 1} s."), 429
        current_app.extensions["last_manual_refresh"] = now
        summary = run_refresh(settings, clock, "manual")
        if summary["status"] == "busy":
            return jsonify(ok=False, error="A refresh is already running. Try again shortly."), 409
        if summary["status"] == "failed":
            return jsonify(ok=False, error="Could not reach the source. Showing the last known data, "
                           "which has not been re-verified.", detail=summary), 502
        return jsonify(ok=True, summary=summary)


    @app.get("/map")
    def map_page():
        filters = NoticeFilters.from_args(request.args)
        conn, now = get_db(), clock()
        notices = notice_service.list_notices(conn, filters, now, settings)
        return render_template(
            "map.html", filters=filters, notices=notices, diagram=notice_service.build_diagram(notices),
            options=notice_service.filter_options(conn), statuses=notice_service.STATUSES,
            pins=pins_for(notices, notice_url), pinned=sum(1 for n in notices if n["latitude"] is not None), **map_context)

    @app.get("/api/map")
    def api_map():
        filters = NoticeFilters.from_args(request.args)
        notices = notice_service.list_notices(get_db(), filters, clock(), settings)
        return jsonify(ok=True, pins=pins_for(notices, notice_url))

    @app.get("/api/weather")
    def api_weather():
        return jsonify(weather_service.get_weather(settings, clock()))

    # ---- accounts and My Routes ----
    def start_session(user_id: int) -> None:
        was_admin = session.get("is_admin")
        session.clear()
        session["csrf"] = secrets.token_hex(16)
        session["user_id"] = user_id
        if was_admin:
            session["is_admin"] = True

    @app.get("/account")
    def account():
        target = safe_next(request.args.get("next"))
        if target:
            session["next"] = target
        if session.get("user_id") and account_service.get_user(get_db(), session["user_id"]):
            return render_template("account.html", tab="manage")
        return render_template("account.html", tab="signup" if request.args.get("tab") == "signup" else "login")

    @app.post("/account/signup")
    def account_signup():
        conn = get_db()
        password = request.form.get("password", "")
        if password != request.form.get("confirm", ""):
            flash("The two passwords do not match.", "error")
            return redirect(url_for("account", tab="signup"))
        try:
            user_id = account_service.sign_up(conn, request.form.get("email", ""), password, clock())
        except AccountError as exc:
            flash(str(exc), "error")
            return redirect(url_for("account", tab="signup"))
        target = safe_next(session.get("next")) or url_for("my_routes")
        start_session(user_id)
        flash("Account created. Follow a route to start getting alerts.", "success")
        return redirect(target)

    @app.post("/account/login")
    def account_login():
        try:
            user = account_service.authenticate(get_db(), request.form.get("email", ""), request.form.get("password", ""),
                                                clock(), request.remote_addr or "?", settings.max_login_failures)
        except AccountError as exc:
            flash(str(exc), "error")
            return redirect(url_for("account", tab="login"))
        target = safe_next(session.get("next")) or url_for("my_routes")
        start_session(user["id"])
        flash("Signed in.", "success")
        return redirect(target)

    @app.post("/account/logout")
    def account_logout():
        session.pop("user_id", None)
        flash("Signed out.", "success")
        return redirect(url_for("index"))

    @app.post("/account/delete")
    def account_delete():
        conn = get_db()
        user = account_service.get_user(conn, session.get("user_id"))
        if user is None:
            return redirect(url_for("account"))
        try:
            account_service.authenticate(conn, user["email"], request.form.get("password", ""), clock(),
                                         request.remote_addr or "?", settings.max_login_failures)
        except AccountError:
            flash("Password incorrect. Your account was not deleted.", "error")
            return redirect(url_for("account"))
        account_service.delete_user(conn, user["id"])
        session.pop("user_id", None)
        flash("Your account, saved routes and alerts were deleted.", "success")
        return redirect(url_for("index"))

    @app.get("/my-routes")
    def my_routes():
        conn, now = get_db(), clock()
        user = account_service.get_user(conn, session.get("user_id"))
        if user is None:
            flash("Sign in to use My routes.", "info")
            return redirect(url_for("account", tab="login", next=url_for("my_routes")))
        routes = account_service.followed_routes(conn, user["id"])
        notices = notice_service.list_notices(conn, NoticeFilters(routes=routes), now, settings) if routes else []
        return render_template(
            "my_routes.html", routes=routes, notices=notices, options=notice_service.filter_options(conn),
            alerts=account_service.user_alerts(conn, user["id"]))

    @app.post("/api/my-routes")
    def api_my_routes():
        conn = get_db()
        user = account_service.get_user(conn, session.get("user_id"))
        if user is None:
            return jsonify(ok=False, error="Sign in to save routes to your account."), 401
        data = request.get_json(silent=True) or {}
        route = str(data.get("route", ""))
        try:
            if data.get("action") == "add":
                account_service.follow_route(conn, user["id"], route, clock())
            elif data.get("action") == "remove":
                account_service.unfollow_route(conn, user["id"], route)
            else:
                return jsonify(ok=False, error="Unknown action."), 400
        except AccountError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(ok=True, routes=account_service.followed_routes(conn, user["id"]))

    # ---- admin ----
    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "POST":
            token = settings.admin_token
            if not token:
                flash("Admin access is disabled: set ADMIN_TOKEN in the .env file.", "error")
            elif hmac.compare_digest(request.form.get("token", ""), token):
                session["is_admin"] = True
                return redirect(url_for("admin"))
            else:
                flash("Incorrect admin token.", "error")
        return render_template("admin_login.html")

    @app.post("/admin/logout")
    def admin_logout():
        session.pop("is_admin", None)
        return redirect(url_for("index"))

    @app.get("/admin")
    @admin_required
    def admin():
        conn = get_db()
        def rows(sql):
            return [dict(r) for r in conn.execute(sql)]
        return render_template(
            "admin.html", scenarios=demo_source.SCENARIOS,
            demo_enabled=settings.enable_demo_source,
            sources=rows("SELECT s.*, a.name AS agency_name FROM sources s JOIN agencies a ON a.id = s.agency_id ORDER BY s.id"),
            runs=rows("SELECT r.*, s.code AS source_code FROM scraper_runs r JOIN sources s ON s.id = r.source_id ORDER BY r.id DESC LIMIT 15"),
            subscriptions=rows("SELECT * FROM subscriptions ORDER BY id"),
            notifications=rows("""SELECT nt.*, s.label AS subscription_label FROM notifications nt
                                  JOIN subscriptions s ON s.id = nt.subscription_id ORDER BY nt.id DESC LIMIT 25"""),
            events=rows("""SELECT e.*, n.title FROM audit_events e LEFT JOIN notices n ON n.id = e.notice_id
                           ORDER BY e.id DESC LIMIT 20"""))

    @app.post("/admin/scrape")
    @admin_required
    def admin_scrape():
        summary = run_refresh(settings, clock, "manual")
        if summary["errors"]:
            flash("Check finished with errors: " + "; ".join(summary["errors"]), "error")
        else:
            flash(f"Check finished: {summary['new']} new, {summary['revised']} revised, "
                  f"{summary['withdrawn']} withdrawn.", "success")
        return redirect(url_for("admin"))

    @app.post("/admin/demo/<action>")
    @admin_required
    def admin_demo(action: str):
        if not settings.enable_demo_source:
            abort(404, "Demo source is disabled.")
        try:
            flash(demo_source.apply_scenario(settings, action, clock()), "success")
        except ValueError:
            abort(404, "Unknown demo action.")
        return redirect(url_for("admin"))

    @app.post("/admin/subscriptions")
    @admin_required
    def admin_add_subscription():
        label = (request.form.get("label") or "").strip()[:60]
        route = (request.form.get("route") or "").strip().upper()
        channel = request.form.get("channel", "demo")
        email = (request.form.get("email") or "").strip()
        error = None
        if not label:
            error = "Give the subscription a name."
        elif route and not ROUTE_RE.match(route):
            error = "Route IDs may only contain letters, numbers, dots, dashes and underscores."
        elif channel not in {"demo", "email"}:
            error = "Unknown notification channel."
        elif channel == "email" and not EMAIL_RE.match(email):
            error = "Enter a valid e-mail address for e-mail notifications."
        if error:
            flash(error, "error")
        else:
            get_db().execute(
                "INSERT INTO subscriptions (label, route_filter, channel, email, created_at) VALUES (?, ?, ?, ?, ?)",
                (label, route or None, channel, email if channel == "email" else None,
                 clock().strftime("%Y-%m-%dT%H:%M:%SZ")))
            flash("Subscription added.", "success")
        return redirect(url_for("admin"))

    @app.post("/admin/subscriptions/<int:sub_id>/toggle")
    @admin_required
    def admin_toggle_subscription(sub_id: int):
        get_db().execute("UPDATE subscriptions SET active = 1 - active WHERE id = ?", (sub_id,))
        return redirect(url_for("admin"))


def register_cli(app: Flask, settings: Settings, clock) -> None:
    @app.cli.command("init-db")
    def init_db_command():
        """Create or upgrade the database and register sources."""
        conn = connect(settings.database_path)
        applied = apply_migrations(conn)
        notes = sync_sources(conn, settings, clock())
        seed_demo_subscription(conn, settings, clock())
        conn.close()
        click.echo(f"Migrations applied: {', '.join(applied) or 'none (already up to date)'}")
        for note in notes:
            click.echo(f"Note: {note}")
        click.echo(f"Database ready at {settings.database_path}")

    @app.cli.command("scrape")
    def scrape_command():
        """Run every enabled source once."""
        conn = connect(settings.database_path)
        outcome = run_all(conn, settings, clock, trigger="cli")
        conn.close()
        for r in outcome.get("reports", []):
            click.echo(f"{r.source_code}: {r.status} new={r.new} revised={r.revised} withdrawn={r.withdrawn} "
                       f"unchanged={r.unchanged}" + (f" error={r.error}" if r.error else ""))
        if outcome["status"] == "busy":
            click.echo("Another run is already in progress.")

    @app.cli.command("reset-demo")
    def reset_demo_command():
        """Reset the demo feed to the original sample notices."""
        click.echo(demo_source.apply_scenario(settings, "reset", clock()))


if __name__ == "__main__":
    application = create_app()
    application.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
