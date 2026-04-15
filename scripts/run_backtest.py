"""Run backtest and print metrics. Usage: python scripts/run_backtest.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.backtester import Backtester
from src.backtest.metrics import compute_metrics
from rich.console import Console
from rich.table import Table

console = Console()

BTC_TICKS = "data/btc_ticks.csv"        # ts,price
POLY_MARKETS = "data/poly_markets.jsonl" # historical market snapshots

bt = Backtester(
    lookback_seconds=15,
    min_edge_bps=500,
    starting_bankroll=1000.0,
)

result = bt.run(BTC_TICKS, POLY_MARKETS)
metrics = compute_metrics(result, starting_bankroll=1000.0)

table = Table(title="Backtest Results")
table.add_column("Metric", style="cyan")
table.add_column("Value", style="white")
for k, v in metrics.items():
    table.add_row(k, str(v))

console.print(table)
