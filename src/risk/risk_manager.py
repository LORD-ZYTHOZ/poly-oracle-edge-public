"""Risk manager — gates signals, sizes trades, enforces daily stop-loss."""
import logging
from dataclasses import dataclass, replace
from typing import Optional

from src.models import Signal, Trade, TradingMode

logger = logging.getLogger(__name__)


@dataclass
class RiskState:
    bankroll: float
    starting_equity: float
    daily_pnl: float = 0.0
    open_exposure: float = 0.0
    trade_count: int = 0
    halted: bool = False


class RiskManager:
    def __init__(
        self,
        starting_bankroll: float,
        max_risk_per_trade: float = 0.02,
        max_open_exposure: float = 0.10,
        daily_stop_loss: float = 0.05,
        kelly_fraction: float = 0.25,
        mode: TradingMode = TradingMode.WATCH,
    ) -> None:
        self._cfg_max_risk = max_risk_per_trade
        self._cfg_max_exposure = max_open_exposure
        self._cfg_daily_sl = daily_stop_loss
        self._kelly = kelly_fraction
        self._mode = mode
        self.state = RiskState(
            bankroll=starting_bankroll,
            starting_equity=starting_bankroll,
        )

    def evaluate(self, signal: Signal) -> Optional[Trade]:
        """Return a Trade if signal passes all risk checks, else None."""
        if self.state.halted:
            logger.warning("Risk halted — skipping signal %s", signal.market_id)
            return None

        if signal.direction == "NONE":
            return None

        # Daily stop-loss check
        daily_loss_pct = -self.state.daily_pnl / self.state.starting_equity
        if daily_loss_pct >= self._cfg_daily_sl:
            logger.warning("Daily stop-loss triggered (%.2f%%) — halting", daily_loss_pct * 100)
            self.state = replace(self.state, halted=True)
            return None

        # Size the trade
        size = self._size(signal)
        if size <= 0:
            return None

        # Exposure check
        if self.state.open_exposure + size > self.state.bankroll * self._cfg_max_exposure:
            logger.debug("Exposure cap reached — skipping %s", signal.market_id)
            return None

        entry_price = signal.market_price_up if signal.direction == "UP" else (1 - signal.market_price_up)
        ev = size * signal.edge

        trade = Trade(
            market_id=signal.market_id,
            side=signal.direction,
            size=size,
            entry_price=entry_price,
            expected_value=ev,
            mode=self._mode,
            token_id=signal.token_id,
        )

        # Reserve exposure immediately
        self.state = replace(self.state, open_exposure=self.state.open_exposure + size)
        return trade

    def record_settlement(self, trade: Trade, won: bool) -> None:
        """Update state after a trade settles.

        size is USDC staked. If won, return = size/price shares * $1 = size/price.
        Net pnl = size/price - size = size*(1/price - 1).
        If lost, pnl = -size (entire stake lost).
        """
        if won:
            pnl = trade.size * (1.0 / trade.entry_price - 1.0)
        else:
            pnl = -trade.size

        self.state = replace(
            self.state,
            bankroll=self.state.bankroll + pnl,
            daily_pnl=self.state.daily_pnl + pnl,
            open_exposure=max(0.0, self.state.open_exposure - trade.size),
            trade_count=self.state.trade_count + 1,
        )
        logger.info(
            "Settlement: %s %s | won=%s | pnl=%.2f | bankroll=%.2f",
            trade.market_id, trade.side, won, pnl, self.state.bankroll,
        )

    def _size(self, signal: Signal) -> float:
        """Kelly-fractional sizing capped at max_risk_per_trade."""
        # Kelly: f = edge / (1 - entry_price)  for binary bet
        entry = signal.market_price_up if signal.direction == "UP" else (1 - signal.market_price_up)
        if entry <= 0 or entry >= 1:
            return 0.0

        kelly_full = signal.edge / (1 - entry)
        kelly_sized = max(0.0, kelly_full) * self._kelly
        cap = self.state.bankroll * self._cfg_max_risk
        return min(kelly_sized * self.state.bankroll, cap)
