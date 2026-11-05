import json

from scraper import demo_source
from services.collector_service import run_all
from tests.conftest import csrf_token


def refresh(client, token):
    return client.post("/api/refresh", headers={"X-CSRF-Token": token})


def test_empty_state_before_first_collection(client):
    html = client.get("/").get_data(as_text=True)
    assert "No notices collected yet" in html
    assert "No successful check yet" in html


def test_refresh_populates_dashboard(client, token):
    body = refresh(client, token).get_json()
    assert body["ok"] and body["summary"]["new"] == 6
    html = client.get("/").get_data(as_text=True)
    assert "Riverside Bridge closed for maintenance" in html and "Last verified" in html


def test_post_without_csrf_is_rejected(client):
    assert client.post("/api/refresh").status_code == 400
    assert client.post("/admin/logout", data={}).status_code == 400


def test_route_filter_matches_notices_with_multiple_routes(client, token):
    refresh(client, token)
    for route in ("12A", "12B"):
        data = client.get(f"/api/notices?route={route}").get_json()
        assert [n["external_id"] for n in data["notices"]] == ["DEMO-001"]
    assert client.get("/api/notices?route=NOPE").get_json()["count"] == 0


def test_search_filters_status_type_and_date(client, token):
    refresh(client, token)
    ids = lambda qs: sorted(n["external_id"] for n in client.get(f"/api/notices?{qs}").get_json()["notices"])
    assert ids("q=bridge") == ["DEMO-001"]
    assert ids("q=45x") == ["DEMO-002"]
    assert ids("q=demo city") == sorted(f"DEMO-00{i}" for i in range(1, 7))
    assert ids("status=expired") == ["DEMO-004"]
    assert ids("status=upcoming") == ["DEMO-002"]
    assert "DEMO-004" not in ids("status=active")
    assert ids("type=Delay") == ["DEMO-003"]
    assert ids("q=%25") == []  # wildcard characters are escaped, not interpreted
    assert ids("date=2026-10-26") != []
    assert ids("date=2026-12-31") == ["DEMO-006"]  # only the open-ended notice still applies


def test_invalid_filter_values_are_ignored_with_message(client, token):
    refresh(client, token)
    data = client.get("/api/notices?status=bogus&date=31-31-2026").get_json()
    assert data["ok"] and data["count"] == 6 and len(data["warnings"]) == 2
    assert "was ignored" in client.get("/?status=bogus").get_data(as_text=True)


def test_notice_detail_shows_history_and_missing_end_date(client, token, app, settings, clock):
    refresh(client, token)
    demo_source.apply_scenario(settings, "extend_outage", clock())
    clock.advance(minutes=20)
    refresh(client, token)
    page = client.get("/notice/1").get_data(as_text=True)
    assert "Revision history" in page and "Validity extended" in page and "Revision 2" in page
    open_ended = client.get("/api/notices?q=lakeside").get_json()["notices"][0]
    html = client.get(f"/notice/{open_ended['id']}").get_data(as_text=True)
    assert "No end date announced" in html


def test_expired_notice_is_not_active_on_page(client, token):
    refresh(client, token)
    expired = client.get("/api/notices?q=hillview").get_json()["notices"][0]
    assert expired["status"] == "expired"
    assert "pill-active" not in client.get(f"/notice/{expired['id']}").get_data(as_text=True)


def test_stale_data_labelled_after_failed_refresh(client, token, settings, clock):
    refresh(client, token)
    demo_source.apply_scenario(settings, "fail_on", clock())
    clock.advance(minutes=settings.freshness_minutes + 10)
    response = refresh(client, token)
    assert response.status_code == 502 and "not been re-verified" in response.get_json()["error"]
    html = client.get("/").get_data(as_text=True)
    assert "pill-stale" in html and "have not been re-verified" in html
    stats = client.get("/api/stats").get_json()
    assert stats["counts"]["active"] == 0 and stats["counts"]["stale"] >= 1


def test_timezone_display_is_ist(client, token, clock):
    refresh(client, token)
    html = client.get("/notice/1").get_data(as_text=True)
    assert "IST" in html  # base time is 09:00 UTC


def test_refresh_cooldown(settings):
    from dataclasses import replace
    from app import create_app
    from tests.helpers import Clock
    clock = Clock()
    strict = create_app(replace(settings, manual_refresh_cooldown=60), clock)
    strict.testing = True
    c = strict.test_client()
    t = csrf_token(c)
    assert c.post("/api/refresh", headers={"X-CSRF-Token": t}).status_code == 200
    assert c.post("/api/refresh", headers={"X-CSRF-Token": t}).status_code == 429
    clock.advance(seconds=61)
    assert c.post("/api/refresh", headers={"X-CSRF-Token": t}).status_code == 200


def test_unknown_pages_and_api_errors(client):
    assert client.get("/notice/9999").status_code == 404
    assert "Page not found" in client.get("/nowhere").get_data(as_text=True)
    api = client.get("/api/nowhere")
    assert api.status_code == 404 and api.get_json()["ok"] is False


def test_admin_requires_login(client, token):
    assert client.get("/admin").status_code == 302
    assert client.post("/admin/scrape", data={"csrf_token": token}).status_code == 302
    bad = client.post("/admin/login", data={"token": "wrong", "csrf_token": token})
    assert "Incorrect admin token" in bad.get_data(as_text=True)
    assert client.get("/admin").status_code == 302


def test_admin_disabled_without_token(settings, clock):
    from dataclasses import replace
    from app import create_app
    app = create_app(replace(settings, admin_token=None), clock)
    c = app.test_client()
    page = c.post("/admin/login", data={"token": "", "csrf_token": csrf_token(c)})
    assert "Admin access is disabled" in page.get_data(as_text=True)


def test_admin_scenario_flow_and_subscription_validation(admin_client, token, settings):
    assert admin_client.get("/admin").status_code == 200
    r = admin_client.post("/admin/demo/extend_outage", data={"csrf_token": token}, follow_redirects=True)
    assert "Extended the Riverside Bridge outage" in r.get_data(as_text=True)
    assert admin_client.post("/admin/demo/not_real", data={"csrf_token": token}).status_code == 404
    bad = admin_client.post("/admin/subscriptions", data={"csrf_token": token, "label": "x", "route": "<b>"}, follow_redirects=True)
    assert "Route IDs may only contain" in bad.get_data(as_text=True)
    bad = admin_client.post("/admin/subscriptions", data={"csrf_token": token, "label": "m", "channel": "email", "email": "nope"}, follow_redirects=True)
    assert "valid e-mail" in bad.get_data(as_text=True)
    ok = admin_client.post("/admin/subscriptions", data={"csrf_token": token, "label": "Route 45", "route": "45", "channel": "demo"}, follow_redirects=True)
    assert "Subscription added" in ok.get_data(as_text=True)


def test_security_headers_and_health(client):
    r = client.get("/health")
    assert r.get_json()["ok"] and r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


def test_session_cookie_has_its_own_name(client):
    cookie = client.get("/").headers.get("Set-Cookie", "")
    assert cookie.startswith("transitnotice_session=") and "HttpOnly" in cookie and "SameSite=Lax" in cookie
