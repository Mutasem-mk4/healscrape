# healscrape

Self-healing, operator-focused CLI scraper: **deterministic CSS extraction first**, **JSON Schema validation**, optional **Gemini-assisted healing** with **audited selector promotion**, and **full persistence** (runs, snapshots, traces, healing events, selector versions).

## Requirements

- Python **3.12+**
- Optional: **Playwright** (`pip install healscrape[browser]` then `playwright install chromium`)
- For healing: **Gemini API key** (`GEMINI_API_KEY`)

## Install (development tree)

```bash
cd healscrape
pip install -e ".[dev,browser]"
cp .env.example .env   # add GEMINI_API_KEY when using healing
alembic upgrade head   # optional if CLI auto-migrate is skipped
```

The CLI entry point is **`scrape`**. Run **`scrape --help`** for built-in examples.

**Structured JSON / CSV / NDJSON is written to stdout** (human hints and errors to stderr), so this works:  
`scrape quick https://example.com > page.json`

## Easiest usage (no schema file, no database)

```bash
scrape https://example.com                    # same as: scrape quick … (JSON to stdout)
scrape quick https://example.com              # explicit quick mode
scrape quick https://example.com -t           # friendly table on stderr
scrape quick https://example.com --save       # same fields + full persist / optional healing
scrape setup                                  # guided wizard: .env, data dir, Gemini, starter files
```

## Quick start (your own schema)

```bash
scrape init                                   # writes page.schema.json + site.yaml in current directory
scrape extract "https://example.com/page" page.schema.json
# same as: scrape extract URL --schema page.schema.json

# Structured extract + auto-heal when validation fails (needs GEMINI_API_KEY)
scrape extract "https://example.com/product/1" samples/products.schema.json

scrape inspect "https://example.com"
scrape heal "https://example.com/product/1" samples/products.schema.json
scrape doctor                                 # check Python, API key, Playwright

# Operator queries
scrape profiles list
scrape selectors show demo_shop
scrape runs show <run_public_uuid>
```

## Configuration

| Env | Purpose |
|-----|---------|
| `GEMINI_API_KEY` | Required for LLM healing / fallback extraction |
| `HEALSCRAPE_DATA_DIR` | SQLite DB, snapshots, traces (default `~/.healscrape`) |
| `DATABASE_URL` | Override DB (e.g. `postgresql+psycopg2://...` with `pip install healscrape[postgres]`) |
| `HEALSCRAPE_HTTP_TIMEOUT_S` | HTTP timeout |
| `HEALSCRAPE_MAX_RETRIES` | Bound for transport retries (Tenacity wraps fetch) |
| `HEALSCRAPE_RATE_LIMIT_RPS` | Client-side pacing between HTTP requests |
| `HEALSCRAPE_MIN_PROMOTION_CONFIDENCE` | Minimum confidence to promote repaired selectors (default `0.85`) |
| `HEALSCRAPE_LLM_MAX_INPUT_CHARS` | Cap on visible text / context shipped to the model |

Standard `HTTP_PROXY` / `HTTPS_PROXY` are honored by **httpx** for fetch only (no CAPTCHA or anti-bot tooling).

## Schema & profiles

- **JSON Schema** files may attach per-field hints under **`x-healscrape`**: `selector`, optional `attr`, optional `required` override.
- **YAML profiles** (`samples/demo_site.yaml`) set `site`, optional `render`, optional top-level `selectors` map merged into schema fields, plus a nested `schema` object.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `10` | Validation failed |
| `20` | Fetch failed |
| `21` | Render failed (Playwright) |
| `30` | Healing failed (LLM error / bad repair) |
| `31` | LLM unavailable / misconfigured |
| `40` | CLI configuration error |
| `44` | Entity not found |
| `99` | Internal error |

## Docker

```bash
docker build -t healscrape .
docker run --rm -e GEMINI_API_KEY -e HEALSCRAPE_DATA_DIR=/data -v hsdata:/data healscrape extract "https://example.com" --schema /app/samples/products.schema.json
```

## Tests

```bash
pytest tests -q
```

Includes unit tests (validation, `json_path`, LLM merge/evidence), DB integration, a fast deterministic E2E (`test_e2e_fast.py`), healing + promotion (`test_e2e_healing_promotes_selectors.py`), **LLM value fallback when selectors stay broken** (`test_e2e_llm_fallback.py`), and a **second-run** check that promoted selectors work without the LLM (`test_e2e_healing_promotes_selectors.py::test_e2e_second_run_uses_promoted_selectors_without_llm`).

## Documentation

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for interfaces, persistence, and the healing state machine.

## Limitations & hardening (next steps)

- Healing quality depends on **bounded DOM/text context**; very large or highly dynamic pages may need `--render` and tighter schemas.
- **CSV output** flattens top-level scalar fields only.
- **Wheel/sdist** installs may not ship the `alembic/` tree; from a wheel, the CLI falls back to `create_all` (documented in ARCHITECTURE). Prefer running from a source checkout for migration-controlled deployments.
- Add richer **nested object** extraction, **multi-record** schemas, and **human approval** gates before promotion in high-stakes environments.

## License

MIT
