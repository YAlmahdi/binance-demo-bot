> Current implementation, test evidence and phase approval: [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md). This is the project status source of truth; older reports retain historical context.

# Futures AI Lab — Binance USD-M Futures Demo

A runnable Python project for **Binance Demo only**: safe diagnostics, validated local market data and separate offline historical backtesting.

**Current scope: Phase 2 offline research.** Phase 1 diagnostics remain available. No paper/Demo execution engine, ML model or Streamlit dashboard is enabled. There are no profit guarantees.

## Phase 2: offline historical backtesting

Phase 2 adds EMA20/50/200, RSI14, MACD12/26/9, ATR14 and preceding-volume analysis; a fixed LONG/SHORT/NO TRADE baseline; next-candle entries; adverse fills, fees and historical funding; ATR stops/targets; a trade/decision/equity journal; and metrics compared with NO TRADE.

From the official project directory:

```powershell
$pythonExe = 'C:\Users\yazan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $pythonExe run.py backtest --db data/market.sqlite3 --output reports/my-backtest
# Full suite plus default and doubled-cost samples; blocks network and real .env reads:
& $pythonExe scripts/verify_phase2.py
```

Backtesting never loads .env or calls Binance. It reads the existing SQLite database in read-only mode. No new historical data is downloaded. You can use your own Python 3.11+ interpreter instead.

Defaults: a separate simulated 10,000 USDT account, maximum 0.5% planned risk per trade, 2x entry leverage, 2% UTC daily entry halt, one shared position, 2x ATR stop, 3x ATR target and a 48-bar holding cap. No Martingale or adding to existing positions. Fees are assumed at 0.05% per side and slippage at 0.02% per fill. Funding, gap losses and conservative OHLC rules are documented; planned risk is not a guaranteed loss cap.

**Original one-day integration sample:** BTCUSDT and ETHUSDT, 288 five-minute candles each, UTC 2026-10-08. Zero trades; zero net PnL after simulated costs; zero drawdown; undefined win rate/profit factor. This ties NO TRADE and **does not demonstrate profitability**. Each symbol has only 89 fully warmed indicator rows. No strategy thresholds were tuned to force trades. Doubling fee/slippage assumptions also produces zero trades, which does not establish cost robustness.

Original Phase 2 verification: **80 discovered, 79 passed, 0 failed, 0 errors, 1 skipped**. The skipped test is the optional public Demo network smoke test, intentionally disabled for offline-only work. Long/short trades and costs are exercised in labeled synthetic tests, not passed off as historical performance.

Read the [Phase 2 guide](docs/phase2-guide.md), [specification](docs/phase2-spec.md), [review and verification](docs/phase2-review.md), and [sample report](reports/phase2-sample/report.md). Reports include CSV journals and JSON with exact assumptions and reproducibility hashes. Phase 3, Demo execution and ML are not enabled.

## Larger historical research

The original one-day Phase 2 sample is preserved. A separate public-Demo-only 90-day dataset now covers July 11 through October 9, 2026: 25,920 completed 5m candles per symbol, with no missing candle intervals.

The frozen baseline generates trades but loses money after assumed costs: **851 trades, -7,516.50 USDT net PnL**, versus NO TRADE at zero. Doubled fees/slippage produce **723 trades, -8,222.31 USDT**. Starting simulated equity is 10,000 USDT in each scenario. Funding completeness and Demo-market realism remain documented limitations. No trading rules were optimized.

Run `scripts/research_history.py` without --collect to reproduce the saved snapshot evaluation offline. Read [methodology, results and changed files](docs/historical-research.md) and the [full research report](reports/historical-90d/report.md). Final research suite: **104 passed, 0 failed, 1 optional network test skipped**. No credentials, orders, ML or Phase 3 were used.

## Requirements and Phase 1 diagnostics

Python 3.11 or newer. Phases 1 and 2 use only the standard library; no third-party runtime packages are needed.

In PowerShell:

```powershell
cd "C:\Users\yazan\Development\binance-demo-bot"
python run.py check-public
```

On this machine, the current `python` command points to a nonworking WindowsApps alias. The bundled interpreter used to verify this project is:

```powershell
$pythonExe = 'C:\Users\yazan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $pythonExe run.py check-public
```

This bundled path is machine-specific and may change after app updates. For ongoing development, use a standalone Python installation and virtual environment. Installing the package with `python -m pip install -e .` is optional; `run.py` works without installation.

## Step 1: access Demo with your existing Binance account

You do not convert your real account or transfer real funds. Binance's [official Demo guide](https://www.binance.com/en/support/faq/detail/9be58f73e5e14338809e3b705b9687dd) describes signing into Demo using your existing Binance account. Access depends on account and regional eligibility.

1. Open [Binance Demo](https://demo.binance.com/) in your own browser and sign in yourself.
2. Choose **Start Demo Trading** if prompted, then select **USD-M Futures** (USDⓈ-M in some UI labels).
3. Confirm you are in Demo and see virtual funds. The Demo Assets page can reset virtual balances if needed. No real deposit is required for this project.
4. Stop here until Demo access works. If unavailable, check eligibility with Binance; do not change the bot to a production endpoint.

API keys are not needed for this step, `check-public`, or public Demo data collection.

## Step 2: create a separate Demo API key

Inside Demo, open the account menu and **API Management**, or visit [Demo API Management](https://demo.binance.com/en/my/settings/api-management). Verify the hostname is `demo.binance.com`.

Select **Create API**, name it `Futures-AI-Lab-Demo`, and choose a system-generated HMAC key if a key-type choice appears. The current client supports HMAC-SHA256, not RSA/Ed25519 signing. Complete Binance's verification yourself.

Use only permissions needed to read the Demo account for now. We are not testing order validation or placing trades during setup. UI labels and permissions can vary; if they differ, describe only the labels, without sharing credentials or screenshots containing them.

Never reuse keys from the real account's API Management. Do not paste credentials into Codex chat, skill files, screenshots, shell commands, or GitHub.

## Step 3: save credentials locally, not in Codex chat

You do not need to add a Binance key to Codex settings. The **local Python application** loads it from `.env` when you run an authenticated check. The agent and project skills must not inspect credential values.

From the project directory:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Enter the actual Demo values yourself in Notepad, replacing these placeholders, then save and close:

```dotenv
BINANCE_ENV=demo
BINANCE_DEMO_API_KEY=YOUR_DEMO_API_KEY
BINANCE_DEMO_API_SECRET=YOUR_DEMO_API_SECRET
```

Do not add spaces inside credential values. The parser supports plain assignments or quoted values, but not shell execution or interpolation. Environment variables take precedence over the file; do not dump your environment to troubleshoot this.

`.env` and SQLite data are excluded from Git. Never force-add them. **Git exclusion is not encryption or a filesystem restriction.** The project has been moved to `C:\Users\yazan\Development\binance-demo-bot`, outside OneDrive. Keep `.env` in this local folder; do not copy it back into a synced location. A Git ignore rule does not control cloud-sync software.

## Step 4: verify the account without trading

After saving your Demo keys locally, run this yourself:

```powershell
& $pythonExe run.py check-account
```

It reads Demo balances and open orders for BTCUSDT/ETHUSDT. It does not place, cancel, or close orders. Account output is private even without API secrets. If it fails, share only the sanitized HTTP/code error, not `.env`, headers, signatures, keys, or full account output.

An authentication failure is not a reason to use production. Check Demo key origin, saved values, required read permissions, and your computer clock.

## Order validation without execution — later, optional

Do not run this during skill setup or initial Demo access. Once diagnostics work and order validation is requested:

```powershell
& $pythonExe run.py test-order --symbol BTCUSDT --side BUY --quantity 0.002 --price 60000.10
```

This checks current LOT_SIZE, PRICE_FILTER, and MIN_NOTIONAL rules, then uses **POST /fapi/v1/order/test** only. Binance does not send this request to the matching engine or create a position. The example may be rejected because of current prices or other exchange rules; use current Demo information. Validation does not prove an actual order would fill or a strategy is safe.

## Collect market data

```powershell
& $pythonExe run.py collect --start 2026-10-08T00:00:00Z --end 2026-10-09T00:00:00Z
# One symbol and interval:
& $pythonExe run.py collect --start 2026-10-08T00:00:00Z --end 2026-10-09T00:00:00Z --symbols BTCUSDT --intervals 5m
```

All times are UTC; the end bound is exclusive. Only complete candles inside the requested range are collected, with pagination and idempotent storage keyed by symbol, interval, and open time. Supported intervals: 5m, 15m, 1h, 4h. Demo determines historical availability, which can differ from the real market. No production fallback exists.

The default `data/market.sqlite3` database contains:

| Table | Contents |
|---|---|
| `candles` | OHLCV, quote volume, and trade count |
| `funding` | Historical funding events and first local observation times |
| `open_interest` | Current snapshots with event and first observation times, not reconstructed historical OI |
| `collection_runs` | Completed collection reports and optional-dataset availability |

Validation rejects NaN/Infinity, inconsistent prices, negative volumes, duplicates, missing intervals, and incorrect chronology. Open candles are excluded. Missing data is not fabricated. A failed batch does not roll back earlier batches; rerunning the same range does not duplicate rows. Reading a stored range with gaps fails explicitly.

Explicit unsupported optional datasets are reported as `unavailable`; empty responses as `empty`. Authentication, ban, outage, and other network failures stop collection. REST is used now; WebSocket is deferred until continuous updates are needed in phase 3.

## Safety boundary

- REST is fixed to `https://demo-fapi.binance.com`, with certificate verification. Alternative origins are rejected.
- Redirects and ambient proxies are disabled. The method/path allowlist permits selected reads and order validation only; execution routes remain blocked.
- Ping/time/exchangeInfo verify connectivity and expected contracts. Signed requests require verification no older than 60 seconds. Excessive latency or clock skew stops the process.
- Binance has no documented `isDemo` balance flag. The fixed Demo hostname over TLS is the boundary; a balance payload does not independently prove Demo. Create keys inside Demo only.
- Request failures invalidate verification. No automatic retry exists, including POST and HTTP 429/418. Missing credentials block private diagnostics.
- Phase 1 does not change leverage/margin or open positions. A position-closing kill switch belongs to a later reviewed execution phase.
- Skills are instructions, **not a security sandbox or implemented runtime risk controls**. Their installation grants no credential access and does not activate future features.

## Tests

```powershell
$env:PYTHONPATH = 'src'
& $pythonExe -m unittest discover -s tests -v
# Optional public Demo HTTPS smoke test, without credentials:
$env:RUN_DEMO_INTEGRATION = '1'
& $pythonExe -m unittest discover -s tests -v
Remove-Item Env:RUN_DEMO_INTEGRATION
```

Offline tests use dummy credentials and mock transports. They cover blocked production origins/execution, signing, expired verification, clock skew, filters, connection failures, pagination, data quality, and SQLite idempotency. Network tests are opt-in. Mock tests do not verify personal keys, and no tests place trades.

The original phase-1 verification passed 28 tests including the public smoke test and collected 828 candles. See [verification details](docs/verification.md) for that historical run and its limits. Documentation and skill validation are separate from these results.

## Project structure and Agent Skills

```text
src/demo_futures/
  config.py       # Local settings and Demo guardrails
  client.py       # HTTPS, signing, account and order-validation checks
  data.py         # Data validation and SQLite
  collector.py    # Historical pagination and availability reports
  cli.py          # Phase 1 commands and logging
  indicators.py   # Causal indicators and warm-up
  strategy.py     # Frozen interpretable baseline
  risk.py         # Offline sizing, costs and daily risk gate
  backtest.py     # Historical portfolio simulation
  backtest_cli.py # Offline command; no credential/client imports
  reporting.py    # JSON, CSV journals and Markdown
scripts/verify_phase2.py # Offline audit guard, tests and sample reports
reports/          # Reproducible historical results and journals
tests/            # Unit, offline integration, optional public network smoke
.agents/skills/   # Five project-local engineering skills
AGENTS.md         # Project instructions and skill routing
docs/             # Verification, Arabic skill report and Demo setup guide
```

The five skills are `binance-demo-api`, `quant-backtesting`, `ml-trading-research`, `futures-risk-manager`, and `trading-code-review`. They are locally authored instructions without external scripts, services, or credentials.

Open **this binance-demo-bot directory** as the Codex project/working directory for normal repository discovery. This chat originally started in the old parent `New project` folder. Open the new local project in Codex so its working directory and skill discovery match the moved files. You can explicitly provide a skill path if it is not listed. New skills should be available on the next turn in the correct project; restart Codex if absent. See [OpenAI skill documentation](https://learn.chatgpt.com/docs/build-skills).

Example: `Use $trading-code-review to review phase 1 offline, without reading .env or calling order endpoints.` Read the [Arabic skills report](docs/skills-report.ar.md) and [Arabic Demo setup guide](docs/demo-setup.ar.md).

## Development phases

1. **Completed:** Demo diagnostics, safe configuration, validated local data.
2. **Current:** Interpretable indicator baseline and offline backtesting, with next-bar timing, risk limits, fees, funding, slippage, journals and NO TRADE comparison. Await approval before further work.
3. Separate paper/Demo execution, reconciliation, duplicate prevention, risk controls, and kill switch. Before execution: 0.5% per-trade risk, 2x leverage, Isolated Margin where supported, 2% daily entry halt, finite position cap, volatility-based SL/TP, and no Martingale.
4. Simple interpretable ML, causal features, purged chronological walk-forward validation, untouched holdout, versioned artifacts, and predeclared performance/risk gates before activation. No self-updating trading models.
5. Streamlit, monitoring, and stability.

Phases 3-5 remain future requirements. Skills alone do not implement or enable them. Docker Compose can be added when a dashboard and persistent worker justify multiple services.

## Official references

Reviewed October 9, 2026:

- [Binance Demo access and API creation](https://www.binance.com/en/support/faq/detail/9be58f73e5e14338809e3b705b9687dd)
- [Futures General Info: Demo origins, signing, errors](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info)
- [Market Data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)
- [Account](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account)
- [Trade: test order and open orders](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade)
- [OpenAI: skills](https://learn.chatgpt.com/docs/build-skills)
