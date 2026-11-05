import json

from tests.conftest import csrf_token, sign_up


def refresh(client):
    client.post("/api/refresh", headers={"X-CSRF-Token": csrf_token(client)})


def follow(client, route):
    return client.post("/api/my-routes", data=json.dumps({"action": "add", "route": route}),
                       headers={"X-CSRF-Token": csrf_token(client), "Content-Type": "application/json"})


def test_my_routes_redirects_visitors_to_login_and_returns_after_signing_in(client, app):
    response = client.get("/my-routes")
    assert response.status_code == 302 and "/account?tab=login&next=/my-routes" in response.headers["Location"]
    assert "Log in" in client.get(response.headers["Location"]).get_data(as_text=True)
    sign_up(client)  # form on the page the visitor was sent to; the saved destination is My routes
    assert client.get("/my-routes").status_code == 200


def test_login_returns_to_the_page_that_asked_for_it(client):
    client.get("/account?tab=signup&next=/notice/1")
    response = sign_up(client)
    assert response.headers["Location"].endswith("/notice/1")


def test_next_parameter_cannot_redirect_off_site(client):
    for bad in ("https://evil.example/", "//evil.example", "/\\evil.example", "javascript:alert(1)"):
        client.get("/account", query_string={"next": bad})
        response = sign_up(client, email=f"user{abs(hash(bad))}@example.com")
        assert response.headers["Location"].endswith("/my-routes"), bad
        client.post("/account/logout", data={"csrf_token": csrf_token(client)})


def test_message_shown_when_redirected(client):
    page = client.get("/my-routes", follow_redirects=True).get_data(as_text=True)
    assert "Sign in to use My routes" in page


def test_my_routes_shows_only_followed_routes(client):
    refresh(client)
    sign_up(client)
    assert "Follow a route to see its notices" in client.get("/my-routes").get_data(as_text=True)
    follow(client, "12A")
    follow(client, "45")
    html = client.get("/my-routes").get_data(as_text=True)
    assert "Riverside Bridge" in html and "Market Road diversion" in html and "Signal fault" not in html
    assert "Saved in this browser" not in html


def test_route_with_no_notices_shows_empty_state(client):
    refresh(client)
    sign_up(client)
    follow(client, "NOPE")
    assert "No notices on your routes" in client.get("/my-routes").get_data(as_text=True)


def test_routes_in_url_are_ignored_now(client):
    refresh(client)
    sign_up(client)
    html = client.get("/my-routes?routes=12A").get_data(as_text=True)
    assert "Riverside Bridge" not in html


def test_follow_button_is_present_for_visitors_and_needs_login_to_act(client):
    refresh(client)
    assert 'data-follow="12A"' in client.get("/notice/1").get_data(as_text=True)
    assert client.post("/api/my-routes", data=json.dumps({"action": "add", "route": "12A"}),
                       headers={"X-CSRF-Token": csrf_token(client), "Content-Type": "application/json"}).status_code == 401
