from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from config import Settings

log = logging.getLogger(__name__)
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_BYTES = 2_000_000


class FetchError(Exception):
    def __init__(self, message: str, status_code: int | None = None, attempts: int = 0):
        super().__init__(message)
        self.status_code = status_code
        self.attempts = attempts


class RobotsDisallowed(FetchError):
    pass


@dataclass
class FetchResponse:
    text: str
    status_code: int
    attempts: int
    url: str


class Fetcher:
    def __init__(self, settings: Settings, session=None, sleep=time.sleep, monotonic=time.monotonic):
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": settings.user_agent})
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | bool] = {}

    def get(self, url: str) -> FetchResponse:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise FetchError(f"Unsupported URL: {url}")
        self._check_robots(parsed.scheme, parsed.netloc, url)

        attempts = 0
        last_error = "unknown error"
        last_status = None
        while attempts < max(1, self.settings.max_retries):
            attempts += 1
            self._respect_rate_limit(parsed.netloc)
            try:
                response = self.session.get(url, timeout=self.settings.request_timeout)
            except requests.Timeout:
                last_error, last_status = "request timed out", None
            except requests.ConnectionError:
                last_error, last_status = "connection failed", None
            except requests.RequestException as exc:
                raise FetchError(f"Request failed: {type(exc).__name__}", attempts=attempts) from exc
            else:
                last_status = response.status_code
                if response.status_code == 200:
                    if len(response.content) > MAX_BYTES:
                        raise FetchError("Response too large", 200, attempts)
                    return FetchResponse(response.text, 200, attempts, url)
                if response.status_code not in RETRY_STATUS:
                    raise FetchError(f"HTTP {response.status_code}", response.status_code, attempts)
                last_error = f"HTTP {response.status_code}"
                self._honour_retry_after(response)
            if attempts < self.settings.max_retries:
                delay = self.settings.backoff_seconds * (2 ** (attempts - 1))
                log.warning("Fetch of %s failed (%s); retrying in %.1fs", parsed.netloc, last_error, delay)
                self._sleep(delay)
        raise FetchError(f"{last_error} after {attempts} attempts", last_status, attempts)

    def _honour_retry_after(self, response) -> None:
        value = response.headers.get("Retry-After", "") if response.status_code == 429 else ""
        if value.isdigit():
            self._sleep(min(int(value), 30))

    def _respect_rate_limit(self, host: str) -> None:
        minimum = self.settings.min_request_interval
        last = self._last_request.get(host)
        if last is not None:
            wait = minimum - (self._monotonic() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = self._monotonic()

    def _check_robots(self, scheme: str, host: str, url: str) -> None:
        if host not in self._robots:
            self._robots[host] = self._load_robots(scheme, host)
        rules = self._robots[host]
        if rules is False:
            raise RobotsDisallowed(f"robots.txt for {host} could not be read; not fetching.")
        if rules is not True and not rules.can_fetch(self.settings.user_agent, url):
            raise RobotsDisallowed(f"robots.txt disallows fetching {url}.")

    def _load_robots(self, scheme: str, host: str):
        robots_url = f"{scheme}://{host}/robots.txt"
        try:
            self._respect_rate_limit(host)
            response = self.session.get(robots_url, timeout=self.settings.request_timeout)
        except requests.RequestException:
            return False
        if 400 <= response.status_code < 500:
            return True
        if response.status_code != 200:
            return False
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser
