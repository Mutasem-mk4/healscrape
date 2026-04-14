from __future__ import annotations

from healscrape.domain.schema_spec import ExtractFieldSpec
from healscrape.engine.llm_merge import merge_llm_fallback, value_supported_by_visible_text


def test_evidence_requires_substring():
    html = "<html><body><p>Hello World</p></body></html>"
    assert value_supported_by_visible_text("Hello World", html)
    assert not value_supported_by_visible_text("Goodbye", html)


def test_merge_fills_only_when_dom_empty_and_evidence():
    html = "<html><body><span>Alpha</span></body></html>"
    fields = [
        ExtractFieldSpec(name="t", json_path="meta.label", json_type="string", required=True),
    ]
    dom = {"meta": {"label": None}}
    merged, fb = merge_llm_fallback(dom, {"t": "Alpha"}, fields, html)
    assert merged["meta"]["label"] == "Alpha"
    assert fb == ["t"]


def test_merge_skips_hallucination():
    html = "<html><body><span>Real</span></body></html>"
    fields = [
        ExtractFieldSpec(name="t", json_path="t", json_type="string", required=True),
    ]
    dom = {"t": None}
    merged, fb = merge_llm_fallback(dom, {"t": "Fake Value Not On Page"}, fields, html)
    assert merged["t"] is None
    assert fb == []
