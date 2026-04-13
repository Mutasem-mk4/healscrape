from __future__ import annotations

from healscrape.engine.extract import extract_from_spec_map


def test_extract_from_spec_map():
    html = "<html><body><h1 class='t'>Hi</h1><a id='l' href='/x'>go</a></body></html>"
    selectors = {
        "title": {"css": "h1.t", "attr": None},
        "link": {"css": "#l", "attr": "href"},
    }
    data = extract_from_spec_map(html, selectors, ["title", "link"])
    assert data["title"] == "Hi"
    assert data["link"] == "/x"
