import re
from pathlib import Path

import pytest

from app import create_app
from config import BASE_DIR, Settings
from database.db import apply_migrations, connect
from tests.helpers import Clock


@pytest.fixture
def settings(tmp_path):
    return Settings(
        secret_key="test-secret", admin_token="test-admin-token", database_path=tmp_path / "test.db",
        demo_feed_path=tmp_path / "demo_feed.json", sample_data_path=BASE_DIR / "sample_data" / "sample_notices.json",
        manual_refresh_cooldown=0, min_request_interval=0, backoff_seconds=0, log_to_file=False, max_retries=3)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def conn(settings):
    connection = connect(settings.database_path)
    apply_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def app(settings, clock):
    application = create_app(settings, clock)
    application.testing = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_token(client) -> str:
    html = client.get("/").get_data(as_text=True)
    return re.search(r'name="csrf-token" content="(\w+)"', html).group(1)


@pytest.fixture
def token(client):
    return csrf_token(client)


@pytest.fixture
def admin_client(client, token):
    client.post("/admin/login", data={"token": "test-admin-token", "csrf_token": token})
    return client


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def reset_shared_state():
    from services import account_service, weather_service
    account_service.reset_throttle()
    weather_service.clear_cache()
    yield


def sign_up(client, email="Student@Example.com", password="correct-horse-9"):
    token = csrf_token(client)
    return client.post("/account/signup", data={"csrf_token": token, "email": email, "password": password,
                                                "confirm": password})
