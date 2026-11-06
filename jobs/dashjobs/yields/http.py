"""Polite HTTP for the yield sources: one request at a time, a pause between requests, a few retries, a clear
User-Agent. Tests replace this with FakeGetter."""
from __future__ import annotations

import time

USER_AGENT = "vasconomics-dashboard/1.0 (personal, non-commercial; weekly job; github.com/vlaranjo/vasconomics-dashboard-data)"


class FetchError(Exception):
    pass


class Getter:
    def __init__(self, delay: float = 2.0, retries: int = 3, timeout: int = 60, sleep=time.sleep):
        import requests

        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.delay, self.retries, self.timeout, self.sleep = delay, retries, timeout, sleep
        self._first = True
        self.log: list[str] = []

    def _do(self, method: str, url: str, **kw) -> bytes:
        last = None
        for attempt in range(1, self.retries + 1):
            if not self._first:
                self.sleep(self.delay * (attempt if attempt > 1 else 1))
            self._first = False
            try:
                r = self.s.request(method, url, timeout=self.timeout, **kw)
                self.log.append(f"{method} {r.status_code} {url}")
                if r.status_code >= 400:
                    raise FetchError(f"HTTP {r.status_code} for {url}")
                return r.content
            except FetchError as e:
                last = e
                if "HTTP 404" in str(e) or "HTTP 401" in str(e) or "HTTP 403" in str(e):
                    break          # retrying will not help
            except Exception as e:  # noqa: BLE001
                last = FetchError(f"{type(e).__name__} for {url}")
        raise last or FetchError(url)

    def get(self, url: str, *, params=None, headers=None) -> bytes:
        return self._do("GET", url, params=params, headers=headers)

    def get_or_none(self, url: str, *, headers=None) -> bytes | None:
        """A plain 404 means 'no such page' (Japan's per-auction result pages); anything else is an error."""
        try:
            return self._do("GET", url, headers=headers)
        except FetchError as e:
            if "HTTP 404" in str(e):
                return None
            raise

    def post(self, url: str, data: dict, *, headers=None) -> bytes:
        return self._do("POST", url, data=data, headers=headers)


class FakeGetter:
    """Test double: routes maps a substring of the URL to bytes (or a callable(url, params) -> bytes | None)."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.log: list[str] = []

    def _find(self, url, params=None, data=None):
        self.log.append(url)
        for key, val in self.routes.items():
            if key in url:
                return val(url, params or data) if callable(val) else val
        raise FetchError(f"HTTP 404 (no fake route) for {url}")

    def get(self, url, *, params=None, headers=None):
        out = self._find(url, params)
        if out is None:
            raise FetchError(f"HTTP 404 for {url}")
        return out

    def get_or_none(self, url, *, headers=None):
        try:
            return self._find(url)
        except FetchError as e:
            if "HTTP 404" in str(e):
                return None
            raise

    def post(self, url, data, *, headers=None):
        out = self._find(url, data=data)
        if out is None:
            raise FetchError(f"HTTP 404 for {url}")
        return out
