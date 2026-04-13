from __future__ import annotations

from healscrape.providers.fetch import FetchedPage


class FakeFetcher:
    def __init__(self, body: str, status: int = 200) -> None:
        self._body = body.encode("utf-8")
        self._status = status

    def get(self, url: str) -> FetchedPage:
        return FetchedPage(
            url=url,
            status_code=self._status,
            headers={"content-type": "text/html"},
            body=self._body,
            final_url=url,
        )

    def close(self) -> None:
        pass
