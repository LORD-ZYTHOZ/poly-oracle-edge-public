"""Load historical BTC ticks and Polymarket market snapshots for backtesting."""
import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

from src.models import MarketWindow, MarketStatus, Tick

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HistoricalMarket:
    market: MarketWindow
    outcome: str          # "UP" | "DOWN"
    settlement_price: float


def load_btc_ticks(path: str | Path) -> Generator[Tick, None, None]:
    """
    Load BTC ticks from CSV with columns: ts, price
    ts = unix timestamp (float), price = USDT price (float)
    """
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield Tick(
                exchange="historical",
                symbol="BTCUSDT",
                ts=float(row["ts"]),
                price=float(row["price"]),
            )


def load_poly_markets(path: str | Path) -> Generator[HistoricalMarket, None, None]:
    """
    Load historical Polymarket data from JSONL.
    Each line: { market: {...}, outcome: "UP"|"DOWN", settlement_price: float }
    """
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            mw = MarketWindow(
                id=raw["market"]["id"],
                start_time=raw["market"]["start_time"],
                end_time=raw["market"]["end_time"],
                ref_price=raw["market"]["ref_price"],
                side_up_price=raw["market"].get("side_up_price", 0.5),
                side_down_price=raw["market"].get("side_down_price", 0.5),
                liquidity=raw["market"].get("liquidity", 500.0),
                status=MarketStatus.SETTLED,
            )
            yield HistoricalMarket(
                market=mw,
                outcome=raw["outcome"],
                settlement_price=raw["settlement_price"],
            )
