"""
Signal engine — computes fair probability and detects mispricings.

Strategy:
    As a 5-min BTC binary market approaches expiry, the "correct" probability
    of UP winning converges toward the current price relative to the opening
    reference price. We model this as a Gaussian random walk:

        P(UP wins) = Φ(z)   where z = (btc - ref) / (σ * √(tte/300))

    Φ is the standard normal CDF, σ is 5-min BTC return volatility, and tte
    is remaining time in seconds. As tte → 0 with btc > ref, z → ∞ and P → 1.

    If our model probability differs from the market price by > min_edge_bps,
    we have a positive-EV trade opportunity.
"""
import logging
import math
import time
from typing import Optional

from src.models import MarketWindow, Signal

logger = logging.getLogger(__name__)

# Empirical 5-min BTC return sigma (annualised ~80% → per 5-min stdev ~0.28%)
# Calibrate from backtester output before live trading.
DEFAULT_5MIN_SIGMA = 0.0028


class SignalEngine:
    def __init__(
        self,
        lookback_seconds: float = 15.0,
        min_edge_bps: int = 500,
        min_liquidity: float = 200.0,
        sigma_5min: float = DEFAULT_5MIN_SIGMA,
    ) -> None:
        self.lookback_seconds = lookback_seconds
        self.min_edge_threshold = min_edge_bps / 10_000
        self.min_liquidity = min_liquidity
        self.sigma_5min = sigma_5min

    def evaluate(
        self,
        market: MarketWindow,
        btc_price: float,
    ) -> Optional[Signal]:
        """Evaluate a single market against current BTC price."""
        if market.ref_price <= 0 or btc_price <= 0:
            return None

        tte = market.end_time - time.time()
        if tte <= 0 or tte > self.lookback_seconds:
            return None

        if market.liquidity < self.min_liquidity:
            return None

        delta = btc_price - market.ref_price
        implied_prob_up = self._prob_up(delta, market.ref_price, tte)

        # Best edge: buy UP or buy DOWN?
        edge_up = implied_prob_up - market.side_up_price
        edge_down = (1 - implied_prob_up) - market.side_down_price

        if edge_up >= self.min_edge_threshold and edge_up >= edge_down:
            direction = "UP"
            edge = edge_up
            token_id = market.up_token_id
        elif edge_down >= self.min_edge_threshold:
            direction = "DOWN"
            edge = edge_down
            token_id = market.down_token_id
        else:
            direction = "NONE"
            edge = max(edge_up, edge_down)
            token_id = ""

        return Signal(
            market_id=market.id,
            ts=time.time(),
            btc_price=btc_price,
            ref_price=market.ref_price,
            delta=delta,
            implied_prob_up=implied_prob_up,
            market_price_up=market.side_up_price,
            edge=edge,
            direction=direction,
            time_to_expiry=tte,
            liquidity=market.liquidity,
            token_id=token_id,
        )

    def _prob_up(self, delta: float, ref_price: float, tte_seconds: float) -> float:
        """
        Normal CDF: probability that BTC closes above ref_price given current delta.

        delta       — absolute price move (btc_price - ref_price) in USD
        ref_price   — BTC price at market open, used to normalise to fractional return
        tte_seconds — remaining time until market expires

        As TTE → 0 and delta > 0, prob → 1.0 (and vice versa for delta < 0).
        """
        if self.sigma_5min <= 0 or ref_price <= 0:
            return 1.0 if delta > 0 else 0.0

        # Normalise dollar delta to fractional return (e.g. $730 / $73000 = 0.01)
        frac_delta = delta / ref_price

        # Scale sigma to remaining time: σ_rem = σ_5min × √(tte / 300)
        remaining_sigma = self.sigma_5min * math.sqrt(max(tte_seconds, 0.1) / 300.0)

        # z-score: how many remaining-sigmas has BTC already moved
        z = frac_delta / remaining_sigma

        return self._norm_cdf(z)

    @staticmethod
    def _norm_cdf(z: float) -> float:
        """Abramowitz & Stegun approximation of the standard normal CDF (error < 7.5e-8)."""
        if z < -6:
            return 0.0
        if z > 6:
            return 1.0
        t = 1.0 / (1.0 + 0.2316419 * abs(z))
        poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
        pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
        cdf = 1.0 - pdf * poly
        return cdf if z >= 0 else 1.0 - cdf
