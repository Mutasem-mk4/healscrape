from __future__ import annotations

from healscrape.domain.schema_spec import ExtractFieldSpec
from healscrape.engine.extract import extract_from_spec_fields, extract_from_spec_map


def test_extract_from_spec_fields_json_path():
    html = "<html><body><h1 class='t'>Hi</h1><a id='l' href='/x'>go</a></body></html>"
    selectors = {
        "title_field": {"css": "h1.t", "attr": None},
        "link_field": {"css": "#l", "attr": "href"},
    }
    fields = [
        ExtractFieldSpec(name="title_field", json_path="item.title", json_type="string"),
        ExtractFieldSpec(name="link_field", json_path="item.url", json_type="string"),
    ]
    data = extract_from_spec_fields(html, selectors, fields)
    assert data == {"item": {"title": "Hi", "url": "/x"}}


def test_extract_from_spec_map_backward_compat():
    html = "<html><body><h1>x</h1></body></html>"
    data = extract_from_spec_map(html, {"title": {"css": "h1", "attr": None}}, ["title"])
    assert data["title"] == "x"
