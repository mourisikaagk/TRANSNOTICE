import re

from scraper import demo_source
from tests.conftest import csrf_token


def refresh(client):
    return client.post("/api/refresh", headers={"X-CSRF-Token": csrf_token(client)})


def test_theme_and_layout_controls_present_but_developer_view_is_admin_only(client, admin_client):
    visitor = client.application.test_client().get("/").get_data(as_text=True)
    assert 'id="theme-toggle"' in visitor and 'data-view="feed"' in visitor and 'data-view="board"' in visitor
    assert 'id="dev-toggle"' not in visitor and "Developer view" not in visitor
    assert 'id="dev-toggle"' in admin_client.get("/").get_data(as_text=True)


def test_route_colours_are_stable_and_bounded(app):
    fn = app.jinja_env.filters["route_class"]
    assert fn("12A") == fn("12A")
    assert all(re.fullmatch(r"rc-[0-9]", fn(str(i))) for i in range(200))
    assert len({fn(str(i)) for i in range(200)}) > 5


def test_developer_details_reach_admins_only(client, app):
    refresh(client)
    visitor = app.test_client()
    for path in ("/", "/notice/1"):
        html = visitor.get(path).get_data(as_text=True)
        assert "dev-info" not in html and "devbox" not in html and "content_hash:" not in html and "snapshot" not in html
    from tests.conftest import csrf_token as token_of
    admin = app.test_client()
    admin.post("/admin/login", data={"token": "test-admin-token", "csrf_token": token_of(admin)})
    html = admin.get("/").get_data(as_text=True)
    assert re.search(r'dev-info">id=\d+ source_id=DEMO-001 revisions=1 hash=[0-9a-f]{16}', html)
    detail = admin.get("/notice/1").get_data(as_text=True)
    assert "content_hash:" in detail and "latest snapshot:" in detail


def test_back_button_on_every_page_except_notices(client):
    refresh(client)
    assert "data-back" not in client.get("/").get_data(as_text=True)
    for path in ("/map", "/notice/1", "/account", "/admin/login", "/nowhere"):
        assert "data-back" in client.get(path).get_data(as_text=True), path


def test_recent_changes_panel_lists_revisions(client, settings, clock):
    assert "Changes appear here after the first collection" in client.get("/").get_data(as_text=True)
    refresh(client)
    demo_source.apply_scenario(settings, "extend_outage", clock())
    clock.advance(minutes=20)
    refresh(client)
    html = client.get("/").get_data(as_text=True)
    section = html.split("What changed recently")[1].split("</section>")[0]
    assert "Extended" in section and "Riverside Bridge" in section


def test_follow_buttons_and_feed_rows_render(client):
    refresh(client)
    html = client.get("/?route=12A").get_data(as_text=True)
    assert 'data-follow="12A"' in html
    assert 'class="cell-routes rc-' in html
    detail = client.get("/notice/1").get_data(as_text=True)
    assert 'data-follow="12A"' in detail and 'data-follow="12B"' in detail


def test_no_inline_scripts_or_styles(client):
    refresh(client)
    for path in ("/", "/map", "/notice/1", "/my-routes", "/account"):
        html = client.get(path, follow_redirects=True).get_data(as_text=True)
        assert not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", html), path
        assert " style=" not in html, path
        assert not re.search(r"\son(click|load|error)=", html), path


def test_every_page_renders(client):
    refresh(client)
    for path in ("/", "/map", "/notice/1", "/account", "/account?tab=signup", "/admin/login"):
        assert client.get(path).status_code == 200, path
    assert client.get("/my-routes").status_code == 302  # needs an account
    assert client.get("/my-routes", follow_redirects=True).status_code == 200


def test_old_demo_feed_is_upgraded_in_place_without_changing_times(settings, clock):
    import json
    original = demo_source.build_feed(settings, clock())
    old = json.loads(json.dumps(original))
    old.pop("version")
    for n in old["notices"]:
        n.pop("lat"), n.pop("lon")
    old["notices"][0]["valid_to"] = "2030-01-01T00:00:00Z"  # an earlier scenario edit
    settings.demo_feed_path.write_text(json.dumps(old))
    clock.advance(hours=5)
    feed = demo_source.load_feed(settings, clock())
    assert feed["version"] == demo_source.FEED_VERSION
    assert all(n["lat"] is not None for n in feed["notices"])
    assert feed["notices"][0]["valid_to"] == "2030-01-01T00:00:00Z"
    assert [n["valid_from"] for n in feed["notices"]] == [n["valid_from"] for n in original["notices"]]


def test_corrupt_demo_feed_is_rebuilt(settings, clock):
    import json
    settings.demo_feed_path.write_text(json.dumps({"agency": {}}))
    assert len(demo_source.load_feed(settings, clock())["notices"]) == 6
