import json

from services import account_service
from tests.conftest import csrf_token, sign_up


def login(client, email="student@example.com", password="correct-horse-9"):
    return client.post("/account/login", data={"csrf_token": csrf_token(client), "email": email, "password": password},
                       follow_redirects=True)


def api(client, action, route):
    return client.post("/api/my-routes", data=json.dumps({"action": action, "route": route}),
                       headers={"X-CSRF-Token": csrf_token(client), "Content-Type": "application/json"})


def test_signup_creates_session_and_hashes_password(client, conn):
    response = sign_up(client)
    assert response.status_code == 302 and response.headers["Location"].endswith("/my-routes")
    row = conn.execute("SELECT * FROM users").fetchone()
    assert row["email"] == "student@example.com"
    assert row["password_hash"].startswith("pbkdf2:sha256") and "correct-horse-9" not in row["password_hash"]
    assert "student@example.com" in client.get("/").get_data(as_text=True)


def test_signup_validation(client, conn):
    token = csrf_token(client)
    def attempt(**kw):
        data = {"csrf_token": token, "email": "a@b.example", "password": "longenough1", "confirm": "longenough1"}
        data.update(kw)
        return client.post("/account/signup", data=data, follow_redirects=True).get_data(as_text=True)
    assert "valid e-mail" in attempt(email="not-an-email")
    assert "at least 8 characters" in attempt(password="short", confirm="short")
    assert "do not match" in attempt(confirm="different1")
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_duplicate_email_is_rejected_case_insensitively(client, app):
    sign_up(client, "Same@Example.com")
    other = app.test_client()
    page = other.post("/account/signup", data={"csrf_token": csrf_token(other), "email": "same@example.COM",
                                              "password": "another-pass1", "confirm": "another-pass1"}, follow_redirects=True)
    assert "already exists" in page.get_data(as_text=True)


def test_login_logout_and_session_rotation(client, app):
    sign_up(client)
    client.post("/account/logout", data={"csrf_token": csrf_token(client)})
    assert "Sign in" in client.get("/").get_data(as_text=True)
    before = csrf_token(client)
    page = login(client)
    assert "Signed in" in page.get_data(as_text=True)
    assert csrf_token(client) != before


def test_wrong_password_and_unknown_user_get_the_same_message(client):
    sign_up(client)
    client.post("/account/logout", data={"csrf_token": csrf_token(client)})
    wrong = login(client, password="wrong-password").get_data(as_text=True)
    unknown = login(client, email="nobody@example.com").get_data(as_text=True)
    assert "E-mail or password is incorrect" in wrong and "E-mail or password is incorrect" in unknown


def test_login_is_throttled_after_repeated_failures(client, settings):
    sign_up(client)
    client.post("/account/logout", data={"csrf_token": csrf_token(client)})
    for _ in range(settings.max_login_failures):
        login(client, password="wrong-password")
    assert "Too many failed attempts" in login(client).get_data(as_text=True)  # even the right password is refused


def test_account_forms_need_csrf(client):
    assert client.post("/account/signup", data={"email": "a@b.example", "password": "longenough1", "confirm": "longenough1"}).status_code == 400
    assert client.post("/account/login", data={"email": "a@b.example", "password": "x"}).status_code == 400


def test_follow_creates_one_subscription_and_unfollow_removes_it(client, conn):
    sign_up(client)
    assert api(client, "add", "12a").get_json()["routes"] == ["12A"]
    api(client, "add", "12A")
    assert conn.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id IS NOT NULL").fetchone()[0] == 1
    assert api(client, "remove", "12A").get_json()["routes"] == []
    assert conn.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id IS NOT NULL").fetchone()[0] == 0


def test_my_routes_api_rules(client):
    assert api(client, "add", "12A").status_code == 401
    sign_up(client)
    assert api(client, "add", "<script>").status_code == 400
    assert api(client, "explode", "12A").status_code == 400
    for i in range(account_service.MAX_ROUTES):
        assert api(client, "add", f"R{i}").status_code == 200
    assert api(client, "add", "EXTRA").status_code == 400


def test_alert_inbox_records_each_change_once(client, token, settings, clock):
    from scraper import demo_source
    sign_up(client)
    api(client, "add", "12A")
    client.post("/api/refresh", headers={"X-CSRF-Token": csrf_token(client)})
    page = client.get("/my-routes").get_data(as_text=True)
    assert page.count("New notice: Riverside Bridge") == 1 or page.count("Riverside Bridge closed") >= 1
    demo_source.apply_scenario(settings, "extend_outage", clock())
    clock.advance(minutes=20)
    for _ in range(2):
        client.post("/api/refresh", headers={"X-CSRF-Token": csrf_token(client)})
    page = client.get("/my-routes").get_data(as_text=True)
    assert page.count("Validity extended") == 1 and page.count("recorded in this app") == 2


def test_delete_account_removes_all_user_data(client, conn):
    sign_up(client)
    api(client, "add", "12A")
    bad = client.post("/account/delete", data={"csrf_token": csrf_token(client), "password": "wrong-pass"}, follow_redirects=True)
    assert "not deleted" in bad.get_data(as_text=True) and conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    client.post("/account/delete", data={"csrf_token": csrf_token(client), "password": "correct-horse-9"})
    for table in ("users", "user_routes"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id IS NOT NULL").fetchone()[0] == 0


def test_admin_flag_survives_user_login_but_user_is_not_admin(client, token):
    sign_up(client)
    assert client.get("/admin").status_code == 302
