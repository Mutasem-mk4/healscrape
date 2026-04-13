from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RenderedPage:
    url: str
    html: str
    title: str | None


def render_page(url: str, timeout_ms: float = 30_000) -> RenderedPage:
    """Render JavaScript using Playwright (optional dependency)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "Playwright is not installed. Install healscrape with the `browser` extra "
            "and run `playwright install`."
        ) from e

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=int(timeout_ms))
            html = page.content()
            title = page.title()
            return RenderedPage(url=page.url, html=html, title=title)
        finally:
            browser.close()
