import json

import requests

from database.db import transaction
from scraper.parser import parse_notices_html
from services import notice_service, weather_service
from services.ingest_service import ingest_notices
from tests.conftest import csrf_token
from tests.helpers import make_notice, make_source

PAGE = '<article class="advisory" data-notice-id="G-1" data-lat="{lat}" data-lon="{lon}"><h2 class="advisory-title">T</h2><ul class="advisory-routes"><li>5</li></ul></article>'


def refresh(client):
    client.post("/api/refresh", headers={"X-CSRF-Token": csrf_token(client)})


def test_coordinates_parsed_and_invalid_ones_ignored():
    ok = parse_notices_html(PAGE.format(lat="12.5", lon="80.25"), "Asia/Kolkata").notices[0]
    assert (ok.latitude, ok.longitude) == (12.5, 80.25)
    for lat, lon in (("95", "10"), ("abc", "10"), ("10", "")):
        result = parse_notices_html(PAGE.format(lat=lat, lon=lon), "Asia/Kolkata")
        assert result.notices[0].latitude is None and any("invalid coordinates" in w for w in result.warnings)
    assert parse_notices_html('<article class="advisory" data-notice-id="G-2"></article>', "Asia/Kolkata").notices[0].latitude is None


def test_location_updates_silently_without_a_revision(conn, clock):
    source = make_source(conn)
    item = make_notice()
    with transaction(conn):
        ingest_notices(conn, source, [item], clock(), True)
    assert conn.execute("SELECT latitude FROM notices").fetchone()[0] is None
    item.latitude, item.longitude = 12.0, 80.0
    with transaction(conn):
        result = ingest_notices(conn, source, [item], clock(), True)
    row = conn.execute("SELECT latitude, longitude FROM notices").fetchone()
    assert (row[0], row[1]) == (12.0, 80.0) and result.unchanged == 1
    assert conn.execute("SELECT COUNT(*) FROM notice_revisions").fetchone()[0] == 1


def test_map_api_returns_only_located_notices(client):
    refresh(client)
    data = client.get("/api/map").get_json()
    assert len(data["pins"]) == 6 and all(p["demo"] for p in data["pins"])
    assert {p["id"] for p in client.get("/api/map?route=12B").get_json()["pins"]} == {1}
    client.post("/admin/login", data={"token": "test-admin-token", "csrf_token": csrf_token(client)})


def test_notice_without_coordinates_gets_no_pin(client, conn):
    refresh(client)
    conn.execute("UPDATE notices SET latitude = NULL, longitude = NULL WHERE external_id = 'DEMO-003'")
    ids = {p["id"] for p in client.get("/api/map").get_json()["pins"]}
    assert len(ids) == 5
    page = client.get("/map").get_data(as_text=True)
    assert "5 of 6 notices" in page and "never guessed" in page


def test_map_page_and_detail_carry_pins_attribution_and_demo_label(client):
    refresh(client)
    page = client.get("/map").get_data(as_text=True)
    assert "data-pins=" in page and "OpenStreetMap contributors" in page
    assert "vendor/leaflet/leaflet.js" in page
    detail = client.get("/notice/1").get_data(as_text=True)
    assert 'id="map"' in detail


def test_pin_data_is_escaped_in_html(client, conn):
    refresh(client)
    conn.execute("UPDATE notices SET title = ? WHERE external_id = 'DEMO-001'", ('<img src=x onerror=alert(1)>',))
    page = client.get("/map").get_data(as_text=True)
    assert "<img src=x" not in page
    assert "\\u003cimg" in page


def test_tiles_can_be_disabled(settings, clock):
    from dataclasses import replace
    from app import create_app
    app = create_app(replace(settings, map_tiles_enabled=False), clock)
    c = app.test_client()
    c.post("/api/refresh", headers={"X-CSRF-Token": csrf_token(c)})
    assert 'data-tiles="0"' in c.get("/map").get_data(as_text=True)


def test_diagram_has_one_line_per_live_route(client, conn, settings, clock):
    refresh(client)
    notices = notice_service.list_notices(conn, notice_service.NoticeFilters(), clock(), settings)
    diagram = notice_service.build_diagram(notices)
    routes = {row["route"] for row in diagram["rows"]}
    assert {"12A", "12B", "45", "45X", "7X", "22", "9"} <= routes and "101" not in routes  # 101 is expired
    twelve_a = next(r for r in diagram["rows"] if r["route"] == "12A")
    assert [n["id"] for n in twelve_a["nodes"]] == [1]
    page = client.get("/map").get_data(as_text=True)
    assert "<svg" in page and "does not show geography" in page.replace("do not show geography", "does not show geography")


def test_diagram_empty_state(client):
    assert "No current notices to draw" in client.get("/map").get_data(as_text=True)


class FakeWeather:
    calls = 0

    def __init__(self, payload=None, error=None):
        self.payload, self.error = payload, error

    def get(self, url, params=None, timeout=None, headers=None):
        FakeWeather.calls += 1
        if self.error:
            raise self.error
        return self

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


CURRENT = {"current": {"time": "2026-10-26T14:30", "temperature_2m": 31.4, "precipitation": 0.0, "wind_speed_10m": 12.2, "weather_code": 2}}


def test_weather_success_and_cache(settings, clock):
    FakeWeather.calls = 0
    fake = FakeWeather(CURRENT)
    first = weather_service.get_weather(settings, clock(), fake)
    assert first["ok"] and first["temperature_c"] == 31.4 and first["summary"] == "Partly cloudy"
    assert first["credit"] == "Weather data by Open-Meteo.com"
    weather_service.get_weather(settings, clock(), fake)
    assert FakeWeather.calls == 1
    clock.advance(minutes=settings.weather_cache_minutes + 1)
    weather_service.get_weather(settings, clock(), fake)
    assert FakeWeather.calls == 2


def test_weather_failure_never_invents_data(settings, clock):
    for fake in (FakeWeather(error=requests.Timeout()), FakeWeather({"unexpected": 1})):
        result = weather_service.get_weather(settings, clock(), fake)
        assert result["ok"] is False and "temperature_c" not in result and "unavailable" in result["error"]


def test_weather_route_and_disabled_flag(client, monkeypatch, settings, clock):
    monkeypatch.setattr(weather_service.requests, "get", FakeWeather(CURRENT).get)
    data = client.get("/api/weather").get_json()
    assert data["ok"] and data["label"] == settings.weather_label
    assert 'id="weather"' in client.get("/").get_data(as_text=True)
    from dataclasses import replace
    from app import create_app
    off = create_app(replace(settings, weather_enabled=False), clock).test_client()
    assert off.get("/api/weather").get_json()["enabled"] is False
    assert 'id="weather"' not in off.get("/").get_data(as_text=True)


def test_csp_allows_only_osm_tiles_as_external_resource(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    assert "img-src 'self' https://tile.openstreetmap.org" in csp and "script-src 'self'" in csp and "unsafe" not in csp
