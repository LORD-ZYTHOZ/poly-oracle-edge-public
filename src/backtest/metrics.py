"""Compute performance statistics from backtest results."""
import math
from src.backtest.backtester import BacktestResult


def compute_metrics(result: BacktestResult, starting_bankroll: float) -> dict:
    trades = result.trades
    if not trades:
        return {"error": "no trades"}

    pnls = [t.pnl for t in trades if t.pnl is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / len(pnls) if pnls else 0
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0
    total_pnl = sum(pnls)

    # Max drawdown
    peak = starting_bankroll
    max_dd = 0.0
    equity = starting_bankroll
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        dd = (peak - equity) / peak
        max_dd = max(max_dd, dd)

    # Sharpe (daily, assume ~288 5-min periods/day)
    if len(pnls) > 1 and any(p != pnls[0] for p in pnls):
        mean = avg_pnl
        variance = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
        std = math.sqrt(variance)
        sharpe = (mean / std) * math.sqrt(288) if std > 0 else 0
    else:
        sharpe = 0

    avg_edge = sum(s.edge for s in result.signals) / len(result.signals) if result.signals else 0

    return {
        "trade_count": len(pnls),
        "signal_count": len(result.signals),
        "win_rate": round(win_rate, 4),
        "avg_pnl": round(avg_pnl, 4),
        "total_pnl": round(total_pnl, 4),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe_daily": round(sharpe, 3),
        "avg_edge_bps": round(avg_edge * 10_000, 1),
        "avg_win": round(sum(wins) / len(wins), 4) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0,
    }
