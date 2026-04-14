"""Embedded starter files for `scrape init` (works from wheel or source)."""

STARTER_SCHEMA = """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "MyPage",
  "type": "object",
  "required": ["title"],
  "properties": {
    "title": {
      "type": "string",
      "x-healscrape": {
        "selector": "h1",
        "required": true
      }
    },
    "subtitle": {
      "type": "string",
      "x-healscrape": {
        "selector": "h2",
        "required": false
      }
    }
  }
}
"""

STARTER_PROFILE = """# Edit selectors to match your site, then:
#   scrape extract "https://yoursite.com/page" site.yaml
site: my_site
render: false
selectors:
  title: "h1"
  subtitle: ".subtitle"
schema:
  type: object
  required: [title]
  properties:
    title:
      type: string
      x-healscrape: { required: true }
    subtitle:
      type: string
"""
