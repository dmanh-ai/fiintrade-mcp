# CLAUDE.md

Guidance for Claude Code working in this repo.

## What this is

A single-file FastMCP server (`server.py`) that exposes 15 tools for accessing Vietnamese stock market data from FiinTrade (`*.fiintrade.vn`). It is deployed to Railway as an HTTP MCP endpoint and consumed by Claude.ai as a custom connector at `https://<host>/mcp`.

The server is a thin proxy: each tool maps to one FiinTrade REST or Excel-download endpoint, with light response shaping. There is no database, no caching layer, and no business logic beyond Excel parsing.

## Layout

```
server.py          # All MCP tools + HTTP helpers + entrypoint (single file)
requirements.txt   # fastmcp, httpx, pandas, openpyxl
Dockerfile         # python:3.12-slim, runs `python server.py`
railway.json       # Railway uses Dockerfile builder
README.md          # User-facing deploy/setup guide (Vietnamese)
```

There is no `tests/`, no `src/` layout, no package — just the script.

## Architecture

Two tool groups, both defined in `server.py`:

- **Group A — Live snapshot (REST → JSON)**: `get_latest_price`, `get_price_history`, `get_indices`, `get_money_flow_contribution`, `get_money_flow_by_investor`, `get_money_flow_chart`, `get_time_and_sales`, `get_busd_chart`, `get_watchlist`, `list_tickers`, `get_hot_news`. All go through `_get_json(host, path, params)`.
- **Group B — Excel download (full history)**: `download_investor_history`, `download_price_overview`, `download_order_statistics`, `download_time_sales`. All go through `_download_excel` → `_parse_fiintrade_excel` → `_df_to_response`.

Four upstream hosts in `HOSTS` dict: `core`, `market`, `technical`, `tools`. Most live snapshots hit `market` or `technical`; all Excel downloads hit `technical`.

### Key helpers (`server.py`)

- `_get_json(host, path, params)` — adds `language=vi` and `time=<ms>` cache buster, applies `BASE_HEADERS`, returns parsed JSON.
- `_download_excel(host, path, params)` — same headers, 60s timeout, returns raw bytes.
- `_parse_fiintrade_excel(content)` — FiinTrade Excels have 7 meta rows; real header is at row 8 (`header=7`). Datetime columns are stringified to ISO `YYYY-MM-DD` so the result is JSON-serializable.
- `_df_to_response(df, code)` — uniform shape `{ticker, rows, columns, data: [...]}`.

## Auth

The FiinTrade API uses a custom header `u268359: <token>`. The token is read from the env var `FIINTRADE_TOKEN` once at import time; missing token raises on startup. The token rotates periodically — when the API returns 401, a human grabs a fresh value from DevTools on `fiintrade.vn` and updates Railway's env var.

`BASE_HEADERS` also spoofs a Chrome browser (User-Agent, sec-ch-ua, Origin/Referer set to `https://fiintrade.vn`). Don't strip these — the API rejects requests without them.

## Conventions

- **Single file**: keep all tools in `server.py`. Don't split into modules unless the file gets unwieldy (>1000 lines or clearly separable concerns).
- **Tool docstrings are user-facing**: Claude.ai shows them to end users, so they're written in Vietnamese (with ASCII fallback in some tools — no diacritics in many spots, intentional). Match the existing style when adding tools.
- **Tickers always uppercased**: every tool calls `code.upper()` before sending. Preserve this.
- **Defaults match FiinTrade UI**: `page_size=60` for live history, `page_size=2000` for Excel downloads (≈ 8 years of daily data), `frequency="Daily"`.
- **Param names mirror upstream**: query params use FiinTrade's casing (`Code`, `Frequently` [sic — typo upstream], `ComGroupCode`, `PageSize`, `Screen`). Don't "fix" `Frequently` → `Frequency`; the upstream API expects the misspelling.
- **Group B `Screen` enum**: `StatisticByInvestor`, `Overview`, `OrderStatistic`. Adding a new download tool? It's likely just another `Screen` value on `/PriceData/DownloadPriceData`.
- **No comments unless WHY is non-obvious**. The existing code follows this — don't add narration. The `header=7` line is correctly commented because the magic number isn't self-explanatory.

## Adding a new tool

1. Decide group A (live JSON) or B (Excel download).
2. Add an `async def` decorated with `@mcp.tool()`. Type-annotate args; FastMCP derives the schema.
3. Group A: call `_get_json(host, path, params)` and return its result directly (no reshaping needed).
4. Group B: call `_download_excel`, then `_parse_fiintrade_excel`, then `_df_to_response`.
5. Write a Vietnamese docstring explaining purpose + args. Include any guessed/unverified enum values with a note (see `get_money_flow_contribution` for the pattern).

## Local dev

```bash
export FIINTRADE_TOKEN="<token>"
pip install -r requirements.txt
python server.py    # http://localhost:8000/mcp (streamable-http transport)
```

There is no test suite. Validation is manual: hit a tool from an MCP client (Claude.ai connector or `fastmcp` CLI) and inspect the JSON. If you change a Group B tool, verify the Excel parses cleanly — FiinTrade has been known to alter the meta-row count.

## Deploy

Railway builds the Dockerfile and injects `PORT` (server reads it, defaults to 8000). The MCP transport is `streamable-http` bound on `0.0.0.0`. The user adds `https://<railway-domain>/mcp` as a custom connector in Claude.ai. Setup steps (token rotation, env vars, domain generation) are in `README.md`.

## Gotchas

- `Frequently` (FiinTrade's typo) is the actual query param name, not `Frequency`.
- `_parse_fiintrade_excel` assumes 7 meta rows. If a download returns garbled columns, FiinTrade likely changed the header layout — adjust `header=7` rather than wrapping in try/except.
- The `time=` cache buster on JSON GETs is intentional; FiinTrade's CDN otherwise serves stale snapshots.
- `get_money_flow_by_investor` returns ALL investor groups regardless of `investor_type` (UI-side filter). For per-session history of a specific ticker, use `download_investor_history` instead — the docstring already says this; don't "improve" it by filtering server-side.
- Some `flow_type` / `investor_type` enum values are guesses (noted in the docstrings). When verifying, update the docstring rather than silently changing defaults.

## Branch / commit conventions

No enforced style. Recent commit history is short ("Initial FiinTrade MCP server"). Keep messages focused on the user-facing change. Default development branch for AI-authored work: `claude/<topic>-<id>`.
