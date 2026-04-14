from __future__ import annotations

from healscrape.cli.quick_runner import looks_like_http_url


def test_looks_like_http_url():
    assert looks_like_http_url("https://a.com")
    assert looks_like_http_url("  http://x  ")
    assert not looks_like_http_url("ftp://a")
    assert not looks_like_http_url("extract")
