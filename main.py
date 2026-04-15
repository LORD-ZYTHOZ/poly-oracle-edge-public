"""
poly-oracle-edge — scanner
Watches live BTC price feed + Polymarket 5-min markets, computes edge signals
via a Gaussian probability model, applies fractional-Kelly risk sizing, and
forwards actionable signals to an executor service for CLOB order placement.

Architecture:
    BTC WebSocket (Binance)  ──┐
                               ├──▶ SignalEngine ──▶ RiskManager ──▶ SignalSender
    Polymarket HTTP poll    ──┘

Usage:
    python main.py                      # default config
    python main.py config/split_a.yaml  # A/B test config
"""
import asyncio
import logging
import os
import sys

import yaml
from dotenv import load_dotenv

from src.core.signal_engine import SignalEngine
from src.core.state_tracker import MarketStateTracker
from src.execution.signal_sender import SignalSender
from src.feeds.btc_feed import BTCFeedListener
from src.feeds.poly_feed import PolymarketFeedListener
from src.models import MarketWindow, Tick, TradingMode
from src.monitoring.dashboard import render_dashboard
from src.monitoring.logger import SignalLogger
from src.monitoring.telegram import TelegramAlerter
from src.risk.risk_manager import RiskManager

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("scanner")


def load_config(path: str = "config/default.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


async def run(cfg: dict) -> None:
    mode = TradingMode(os.getenv("TRADING_MODE", cfg.get("mode", "watch")))
    logger.info("poly-oracle-edge starting — mode=%s", mode.value.upper())

    tracker = MarketStateTracker()
    engine = SignalEngine(
        lookback_seconds=cfg["lookback_seconds"],
        min_edge_bps=cfg["min_edge_bps"],
        min_liquidity=cfg["min_liquidity_usd"],
        sigma_5min=cfg.get("sigma_5min", 0.0028),
    )
    risk = RiskManager(
        starting_bankroll=cfg["starting_bankroll"],
        max_risk_per_trade=cfg["max_risk_per_trade"],
        max_open_exposure=cfg["max_open_exposure"],
        daily_stop_loss=cfg["daily_stop_loss"],
        kelly_fraction=cfg["kelly_fraction"],
        mode=mode,
    )
    sender = SignalSender(
        executor_url=os.getenv("EXECUTOR_URL", "http://localhost:8420"),
        secret=os.getenv("EXECUTOR_SECRET", ""),
        mode=mode,
    )
    db = SignalLogger(db_path=os.getenv("DB_PATH", "data/poly_edge.db"))
    telegram = TelegramAlerter(
        token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )

    recent_signals: list = []
    btc_price_ref: list[float | None] = [None]
    _last_eval_ts = [0.0]
    EVAL_INTERVAL = 1.0
    # Dedup: one order per (market_id, end_time) window
    _traded_windows: set[tuple[str, float]] = set()

    async def on_tick(tick: Tick) -> None:
        import time as _time
        btc_price_ref[0] = tick.price

        now = _time.time()
        if now - _last_eval_ts[0] < EVAL_INTERVAL:
            return
        _last_eval_ts[0] = now

        for market in tracker.expiring(cfg["lookback_seconds"]):
            signal = engine.evaluate(market, tick.price)
            if not signal or signal.direction == "NONE":
                continue

            db.log_signal(signal)
            recent_signals.append(signal)
            if len(recent_signals) > 200:
                recent_signals.pop(0)

            logger.info(
                "SIGNAL | %s | tte=%.1fs | edge=%.1f%% | dir=%s",
                signal.market_id[:12], signal.time_to_expiry,
                signal.edge * 100, signal.direction,
            )

            if mode == TradingMode.WATCH:
                continue

            # Dedup on (market_id, end_time) — prevents double-fills if conditionId reused
            window_key = (signal.market_id, round(market.end_time, 0))
            if window_key in _traded_windows:
                logger.debug("Skipping duplicate window %s", signal.market_id[:12])
                continue

            trade = risk.evaluate(signal)
            if not trade:
                continue

            result = await sender.send(signal, size=trade.size, entry_price=trade.entry_price)
            db.log_trade(trade)
            _traded_windows.add(window_key)

            if result:
                status = result.get("status")
                tx = result.get("tx_hash")
                logger.info("EXECUTOR | status=%s | tx=%s", status, tx)
                await telegram.send(
                    f"🟢 {signal.direction} {signal.market_id[:10]}\n"
                    f"edge={signal.edge*100:.1f}% tte={signal.time_to_expiry:.0f}s\n"
                    f"size=${trade.size:.2f} | {status}"
                )

    async def on_market_update(market: MarketWindow) -> None:
        import time as _time
        existing = tracker.get(market.id)
        if existing is None or existing.ref_price <= 0:
            current_btc = btc_price_ref[0]
            if current_btc and current_btc > 0 and market.start_time <= _time.time():
                market = MarketWindow(
                    id=market.id,
                    start_time=market.start_time,
                    end_time=market.end_time,
                    ref_price=current_btc,
                    side_up_price=market.side_up_price,
                    side_down_price=market.side_down_price,
                    liquidity=market.liquidity,
                    status=market.status,
                    up_token_id=market.up_token_id,
                    down_token_id=market.down_token_id,
                )
                logger.info(
                    "REF_PRICE SET | market=%s | ref=%.2f",
                    market.id[:12], current_btc,
                )
        tracker.upsert(market)

    await sender.start()

    btc_listener = BTCFeedListener(on_tick=on_tick)
    poly_listener = PolymarketFeedListener(
        on_market_update=on_market_update,
        poll_interval=cfg["market_poll_interval_s"],
    )

    async def status_log() -> None:
        while True:
            logger.info(
                "STATUS | btc=%.2f | markets=%d | bankroll=%.2f | daily_pnl=%.2f | trades=%d",
                btc_price_ref[0] or 0,
                tracker.active_count,
                risk.state.bankroll,
                risk.state.daily_pnl,
                risk.state.trade_count,
            )
            tracker.purge_settled()
            # Clear dedup set for windows that have long expired (>5min buffer)
            import time as _time
            now = _time.time()
            expired_keys = {k for k in _traded_windows if k[1] < now - 300}
            _traded_windows.difference_update(expired_keys)
            await asyncio.sleep(30)

    try:
        await asyncio.gather(
            btc_listener.start(),
            poly_listener.start(),
            status_log(),
        )
    finally:
        await sender.stop()


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config/default.yaml"
    cfg = load_config(config_path)
    asyncio.run(run(cfg))
