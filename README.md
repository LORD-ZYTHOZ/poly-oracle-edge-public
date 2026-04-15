# poly-oracle-edge

**Polymarket 5-min BTC binary market scanner.**

Exploits the lag between Chainlink oracle updates and Polymarket odds adjustment in the final seconds of 5-minute BTC Up/Down markets. Uses a Gaussian probability model to compute fair probabilities, detect mispricings, and size trades via fractional Kelly.

---

## How it works

Polymarket lists 5-minute binary markets: *"Will BTC be higher or lower than $X at time T?"*

The market's opening reference price is set via Chainlink oracle at market start. In the final 10–20 seconds, the true probability of UP winning converges rapidly toward 0 or 1 — but market makers are often slow to reprice. This scanner:

1. **Tracks every active BTC 5-min market** via Polymarket's Gamma API
2. **Subscribes to live BTC price** via Binance WebSocket (`btcusdt@trade`)
3. **Computes fair probability** using a Gaussian random walk model:

```
P(UP wins) = Φ(z)

where:
  z = (btc_price - ref_price) / ref_price / (σ × √(tte / 300))
  Φ = standard normal CDF
  σ = 5-min BTC return volatility (~0.28%)
  tte = remaining time to expiry (seconds)
```

4. **Detects edge** when `|P(UP) - market_price_UP| > min_edge_bps`
5. **Sizes trades** via quarter-Kelly with daily stop-loss and exposure caps
6. **Places CLOB orders** on Polymarket via `py-clob-client`

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  poly-oracle-edge (scanner)                     │
│                                                 │
│  BTCFeedListener (Binance WS)                   │
│       │                                         │
│       ▼                                         │
│  SignalEngine ──── PolyFeedListener (HTTP poll) │
│       │                                         │
│       ▼                                         │
│  RiskManager (Kelly sizing + stop-loss)         │
│       │                                         │
│       ▼                                         │
│  SignalSender ──▶ executor (CLOB orders)        │
│       │                                         │
│  SignalLogger (SQLite)                          │
│  TelegramAlerter (optional)                     │
└─────────────────────────────────────────────────┘
```

The scanner runs on your local machine. It sends signed signal payloads via HMAC-SHA256 to a separate executor process that handles actual order placement. This separation keeps your private key off the scanner machine.

---

## Quickstart

### 1. Install

```bash
git clone https://github.com/LORD-ZYTHOZ/poly-oracle-edge
cd poly-oracle-edge
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — set TRADING_MODE=watch to start
```

Generate Polymarket API credentials (needed for live mode only):

```bash
PRIVATE_KEY=0xyour_private_key python scripts/generate_api_keys.py
```

### 3. Run

```bash
# Watch mode — signals logged, no orders placed
python main.py

# A/B test configs
python main.py config/split_a.yaml   # tight window, low edge threshold
python main.py config/split_b.yaml   # wide window, original threshold

# Run with PM2 (auto-restart)
pm2 start pm2.config.js
```

### 4. Backtest

```bash
# Requires data/btc_ticks.csv and data/poly_markets.jsonl
# See scripts/run_backtest.py for format
python scripts/run_backtest.py
```

---

## Configuration

All parameters in `config/default.yaml`:

| Parameter | Default | Description |
|---|---|---|
| `lookback_seconds` | `15` | Window before expiry to scan |
| `min_edge_bps` | `500` | Min edge in basis points (500 = 5%) |
| `min_liquidity_usd` | `200` | Min market liquidity to trade |
| `sigma_5min` | `0.0028` | BTC 5-min return volatility — calibrate from backtester |
| `kelly_fraction` | `0.25` | Quarter-Kelly sizing (conservative) |
| `max_risk_per_trade` | `0.02` | Max 2% of bankroll per trade |
| `max_open_exposure` | `0.10` | Max 10% simultaneous exposure |
| `daily_stop_loss` | `0.05` | Halt if daily loss > 5% of equity |

---

## Trading modes

Always start at `watch` and validate each stage before moving to the next.

| `TRADING_MODE` | Orders | Use for |
|---|---|---|
| `watch` | None | Signal validation — check edge distribution |
| `paper` | Simulated | Full pipeline test — verify sizing and dedup |
| `live` | Real CLOB | Production — after paper validation |

---

## Security

- **Private key** — never in this repo. Set via `POLY_PRIVATE_KEY` env var only.
- **HMAC auth** — signals to executor are signed with `EXECUTOR_SECRET` (SHA-256). Generate with: `python3 -c "import secrets; print(secrets.token_hex(32))"`
- **Executor isolation** — keep the executor on a separate machine/process. It's the only component that touches your wallet.
- **Tailscale recommended** — bind the executor to a Tailscale IP rather than exposing port 8420 publicly.

---

## Project structure

```
poly-oracle-edge/
├── main.py                     # Scanner entrypoint
├── config/
│   ├── default.yaml            # Default parameters
│   ├── split_a.yaml            # A/B test: tight window
│   ├── split_b.yaml            # A/B test: wide window
│   └── split_c.yaml            # A/B test: custom
├── src/
│   ├── core/
│   │   ├── signal_engine.py    # Gaussian probability model + edge detection
│   │   └── state_tracker.py    # In-memory market registry
│   ├── feeds/
│   │   ├── btc_feed.py         # Binance WebSocket BTC price feed
│   │   └── poly_feed.py        # Polymarket market poller
│   ├── risk/
│   │   └── risk_manager.py     # Kelly sizing, daily stop-loss, exposure caps
│   ├── execution/
│   │   ├── polymarket_client.py # CLOB order placement (with timeout)
│   │   └── signal_sender.py    # HMAC-signed signal forwarding to executor
│   ├── monitoring/
│   │   ├── dashboard.py        # Rich CLI live dashboard
│   │   ├── logger.py           # SQLite signal + trade logger
│   │   └── telegram.py         # Optional Telegram trade alerts
│   ├── backtest/
│   │   ├── backtester.py       # Historical replay engine
│   │   ├── data_loader.py      # CSV/JSONL data loading
│   │   └── metrics.py          # Sharpe, win rate, EV, drawdown
│   └── models.py               # Core dataclasses (immutable)
├── scripts/
│   ├── generate_api_keys.py    # Derive Polymarket CLOB credentials
│   └── run_backtest.py         # Run backtest and print metrics
├── tests/
│   ├── test_signal_engine.py   # Probability model unit tests
│   ├── test_risk_and_feed.py   # RiskManager + feed parser tests
│   └── test_scanner.py         # Throttle, dedup, ref_price tests
└── pm2.config.js               # PM2 process manager config
```

---

## Tests

```bash
pytest tests/ -v
```

---

## Disclaimer

This is experimental software for research purposes. Polymarket is a prediction market — regulations vary by jurisdiction. Do your own research. Never risk money you can't afford to lose.

---

## License

MIT
