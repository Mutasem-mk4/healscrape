from __future__ import annotations

import threading
from dataclasses import dataclass

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from healscrape.config import Settings
from healscrape.providers.rate_limit import RateLimiter

log = structlog.get_logger(__name__)


@dataclass
class FetchedPage:
    url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    final_url: str


class HttpFetcher:
    def __init__(self, settings: Settings, limiter: RateLimiter | None = None) -> None:
        self.settings = settings
        self.limiter = limiter or RateLimiter(settings.rate_limit_rps)
        self._sem = threading.BoundedSemaphore(max(1, settings.max_concurrent_fetches))
        # httpx respects HTTP_PROXY / HTTPS_PROXY environment variables when set.
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.settings.http_timeout_s),
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
            http2=True,
        )

    def close(self) -> None:
        self._client.close()

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    )
    def get(self, url: str) -> FetchedPage:
        self._sem.acquire()
        try:
            self.limiter.acquire()
            log.info("http_fetch", url=url)
            resp = self._client.get(url)
        finally:
            self._sem.release()
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        return FetchedPage(
            url=url,
            status_code=resp.status_code,
            headers=hdrs,
            body=resp.content,
            final_url=str(resp.url),
        )
