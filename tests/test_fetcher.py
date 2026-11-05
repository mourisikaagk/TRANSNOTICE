import pytest
import requests

from scraper.fetcher import FetchError, Fetcher, RobotsDisallowed


class FakeResponse:
    def __init__(self, status=200, text="ok", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}
        self.content = text.encode()


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls, self.headers = pages, [], {}

    def get(self, url, timeout=None):
        self.calls.append(url)
        queue = self.pages.get(url)
        if queue is None:
            return FakeResponse(404, "")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item


ROBOTS_OK = "https://example.org/robots.txt"
PAGE = "https://example.org/advisories"


def make(settings, pages):
    sleeps = []
    session = FakeSession(pages)
    return Fetcher(settings, session, sleep=sleeps.append), session, sleeps


def test_success_first_try(settings):
    fetcher, session, _ = make(settings, {ROBOTS_OK: [FakeResponse(404)], PAGE: [FakeResponse(200, "<html>")]})
    result = fetcher.get(PAGE)
    assert result.text == "<html>" and result.attempts == 1


def test_retries_with_exponential_backoff_then_succeeds(settings):
    from dataclasses import replace
    s = replace(settings, backoff_seconds=2.0)
    fetcher, _, sleeps = make(s, {ROBOTS_OK: [FakeResponse(404)],
                                  PAGE: [requests.Timeout(), FakeResponse(503), FakeResponse(200, "fine")]})
    assert fetcher.get(PAGE).attempts == 3
    assert [d for d in sleeps if d] == [2.0, 4.0]


def test_gives_up_after_retry_ceiling(settings):
    fetcher, session, _ = make(settings, {ROBOTS_OK: [FakeResponse(404)], PAGE: [requests.ConnectionError()]})
    with pytest.raises(FetchError) as err:
        fetcher.get(PAGE)
    assert err.value.attempts == 3 and session.calls.count(PAGE) == 3


def test_client_errors_are_not_retried(settings):
    fetcher, session, _ = make(settings, {ROBOTS_OK: [FakeResponse(404)], PAGE: [FakeResponse(403)]})
    with pytest.raises(FetchError) as err:
        fetcher.get(PAGE)
    assert err.value.status_code == 403 and session.calls.count(PAGE) == 1


def test_robots_disallow_blocks_fetch(settings):
    robots = FakeResponse(200, "User-agent: *\nDisallow: /advisories\n")
    fetcher, session, _ = make(settings, {ROBOTS_OK: [robots], PAGE: [FakeResponse(200)]})
    with pytest.raises(RobotsDisallowed):
        fetcher.get(PAGE)
    assert PAGE not in session.calls


def test_unreadable_robots_is_treated_as_disallow(settings):
    fetcher, _, _ = make(settings, {ROBOTS_OK: [FakeResponse(503)]})
    with pytest.raises(RobotsDisallowed):
        fetcher.get(PAGE)


def test_rejects_non_http_urls(settings):
    fetcher, _, _ = make(settings, {})
    for url in ("file:///etc/passwd", "ftp://example.org/x", "not a url"):
        with pytest.raises(FetchError):
            fetcher.get(url)


def test_rate_limit_waits_between_requests(settings):
    from dataclasses import replace
    s = replace(settings, min_request_interval=5.0)
    clock = iter([0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    sleeps = []
    session = FakeSession({ROBOTS_OK: [FakeResponse(404)], PAGE: [FakeResponse(200)]})
    fetcher = Fetcher(s, session, sleep=sleeps.append, monotonic=lambda: next(clock))
    fetcher.get(PAGE)
    assert any(d > 0 for d in sleeps)
