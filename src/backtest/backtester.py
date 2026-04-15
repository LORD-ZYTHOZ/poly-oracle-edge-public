"""Offline backtester — replays historical data through signal + risk pipeline."""
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

from src.backtest.data_loader import HistoricalMarket, load_btc_ticks, load_poly_markets
from src.core.signal_engine import SignalEngine
from src.models import MarketWindow, MarketStatus, Signal, Tick, Trade, TradingMode

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    pnl_series: list[float] = field(default_factory=list)
    bankroll_series: list[float] = field(default_factory=list)


class Backtester:
    def __init__(
        self,
        lookback_seconds: float = 15.0,
        min_edge_bps: int = 500,
        max_risk_per_trade: float = 0.02,
        starting_bankroll: float = 1000.0,
        kelly_fraction: float = 0.25,
    ) -> None:
        self.lookback_seconds = lookback_seconds
        self.min_edge_bps = min_edge_bps
        self.starting_bankroll = starting_bankroll
        self.max_risk_per_trade = max_risk_per_trade
        self.kelly_fraction = kelly_fraction
        self._engine = SignalEngine(
            lookback_seconds=lookback_seconds,
            min_edge_bps=min_edge_bps,
        )

    def run(
        self,
        btc_ticks_path: str | Path,
        poly_markets_path: str | Path,
    ) -> BacktestResult:
        ticks = list(load_btc_ticks(btc_ticks_path))
        hist_markets = list(load_poly_markets(poly_markets_path))

        result = BacktestResult()
        bankroll = self.starting_bankroll

        tick_idx = 0
        for hm in hist_markets:
            market = hm.market

            # Advance ticks to market window
            while tick_idx < len(ticks) and ticks[tick_idx].ts < market.start_time:
                tick_idx += 1

            # Replay ticks within this market's window
            i = tick_idx
            while i < len(ticks) and ticks[i].ts <= market.end_time:
                tick = ticks[i]
                tte = market.end_time - tick.ts

                if tte <= self.lookback_seconds:
                    # Temporarily set market status to EXPIRING for signal engine
                    expiring = MarketWindow(
                        id=market.id,
                        start_time=market.start_time,
                        end_time=market.end_time,
                        ref_price=market.ref_price,
                        side_up_price=market.side_up_price,
                        side_down_price=market.side_down_price,
                        liquidity=market.liquidity,
                        status=MarketStatus.EXPIRING,
                    )
                    signal = self._engine.evaluate(expiring, tick.price)
                    if signal and signal.direction != "NONE":
                        result.signals.append(signal)
                        trade = self._size_trade(signal, bankroll)
                        if trade:
                            won = (hm.outcome == trade.side)
                            if won:
                                pnl = trade.size * (1 - trade.entry_price)
                            else:
                                pnl = -trade.size * trade.entry_price
                            bankroll += pnl
                            settled = replace(trade, pnl=pnl)
                            result.trades.append(settled)
                            result.pnl_series.append(pnl)
                            result.bankroll_series.append(bankroll)
                            break  # one trade per market

                i += 1

        return result

    def _size_trade(self, signal: Signal, bankroll: float) -> Optional[Trade]:
        entry = signal.market_price_up if signal.direction == "UP" else (1 - signal.market_price_up)
        if entry <= 0 or entry >= 1:
            return None
        kelly_full = signal.edge / (1 - entry)
        size = min(max(0.0, kelly_full) * self.kelly_fraction * bankroll,
                   bankroll * self.max_risk_per_trade)
        if size <= 0:
            return None
        return Trade(
            market_id=signal.market_id,
            side=signal.direction,
            size=size,
            entry_price=entry,
            expected_value=size * signal.edge,
            mode=TradingMode.PAPER,
            ts=signal.ts,
        )
