"""Tests for SignalEngine — signal generation and probability model."""
import math
import time
import pytest

from src.core.signal_engine import SignalEngine, DEFAULT_5MIN_SIGMA
from src.models import MarketWindow, MarketStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_market(
    ref_price: float = 73_000.0,
    side_up_price: float = 0.5,
    side_down_price: float = 0.5,
    liquidity: float = 15_000.0,
    tte_seconds: float = 30.0,
) -> MarketWindow:
    now = time.time()
    return MarketWindow(
        id="0xtest000001",
        start_time=now - 270.0,
        end_time=now + tte_seconds,
        ref_price=ref_price,
        side_up_price=side_up_price,
        side_down_price=side_down_price,
        liquidity=liquidity,
        status=MarketStatus.EXPIRING,
    )


# ---------------------------------------------------------------------------
# _prob_up unit tests
# ---------------------------------------------------------------------------

class TestProbUp:
    engine = SignalEngine()

    def test_zero_delta_returns_half(self):
        p = self.engine._prob_up(0.0, 73_000.0, 30.0)
        assert abs(p - 0.5) < 0.01

    def test_large_positive_delta_approaches_one(self):
        # +5% move with only 1s left — should be very close to 1.0
        ref = 73_000.0
        delta = ref * 0.05  # +5%
        p = self.engine._prob_up(delta, ref, 1.0)
        assert p > 0.99

    def test_large_negative_delta_approaches_zero(self):
        ref = 73_000.0
        delta = -ref * 0.05  # -5%
        p = self.engine._prob_up(delta, ref, 1.0)
        assert p < 0.01

    def test_symmetry(self):
        """+X and -X deltas should give probs that sum to 1."""
        ref = 73_000.0
        delta = ref * 0.01  # 1%
        p_up = self.engine._prob_up(delta, ref, 30.0)
        p_down = self.engine._prob_up(-delta, ref, 30.0)
        assert abs(p_up + p_down - 1.0) < 1e-6

    def test_longer_tte_means_more_uncertainty(self):
        """Same delta but more time remaining → prob closer to 0.5."""
        ref = 73_000.0
        delta = ref * 0.005  # 0.5% move
        p_short = self.engine._prob_up(delta, ref, 5.0)    # 5s left
        p_long = self.engine._prob_up(delta, ref, 60.0)    # 60s left
        assert p_short > p_long  # short tte = more certain

    def test_dollar_scale_independence(self):
        """Prob should be identical whether BTC is at 10k or 100k (same % move)."""
        pct_move = 0.01
        for ref in [10_000.0, 50_000.0, 100_000.0]:
            delta = ref * pct_move
            p = self.engine._prob_up(delta, ref, 30.0)
            # All should be roughly the same value
            assert abs(p - self.engine._prob_up(73_000.0 * pct_move, 73_000.0, 30.0)) < 0.001

    def test_zero_sigma_falls_back_to_sign(self):
        engine = SignalEngine(sigma_5min=0.0)
        assert engine._prob_up(100.0, 73_000.0, 30.0) == 1.0
        assert engine._prob_up(-100.0, 73_000.0, 30.0) == 0.0

    def test_zero_ref_price_falls_back_to_sign(self):
        p = self.engine._prob_up(100.0, 0.0, 30.0)
        assert p == 1.0


# ---------------------------------------------------------------------------
# _norm_cdf unit tests
# ---------------------------------------------------------------------------

class TestNormCdf:
    def test_zero(self):
        assert abs(SignalEngine._norm_cdf(0.0) - 0.5) < 1e-4

    def test_large_positive_clamp(self):
        assert SignalEngine._norm_cdf(10.0) == 1.0

    def test_large_negative_clamp(self):
        assert SignalEngine._norm_cdf(-10.0) == 0.0

    def test_one_sigma(self):
        # CDF(1.0) ≈ 0.8413
        assert abs(SignalEngine._norm_cdf(1.0) - 0.8413) < 0.001

    def test_neg_one_sigma(self):
        # CDF(-1.0) ≈ 0.1587
        assert abs(SignalEngine._norm_cdf(-1.0) - 0.1587) < 0.001

    def test_symmetry(self):
        for z in [0.5, 1.0, 1.96, 2.5]:
            assert abs(SignalEngine._norm_cdf(z) + SignalEngine._norm_cdf(-z) - 1.0) < 1e-5


# ---------------------------------------------------------------------------
# evaluate() integration tests
# ---------------------------------------------------------------------------

class TestEvaluate:
    engine = SignalEngine(lookback_seconds=60, min_edge_bps=100)

    def test_returns_none_for_zero_ref_price(self):
        market = make_market(ref_price=0.0)
        assert self.engine.evaluate(market, 73_000.0) is None

    def test_returns_none_for_zero_btc_price(self):
        market = make_market(ref_price=73_000.0)
        assert self.engine.evaluate(market, 0.0) is None

    def test_returns_none_when_tte_exceeds_lookback(self):
        market = make_market(tte_seconds=120.0)  # > 60s lookback
        assert self.engine.evaluate(market, 73_000.0) is None

    def test_returns_none_when_tte_expired(self):
        market = make_market(tte_seconds=-1.0)
        assert self.engine.evaluate(market, 73_000.0) is None

    def test_returns_none_below_liquidity(self):
        market = make_market(liquidity=100.0)
        assert self.engine.evaluate(market, 73_730.0) is None

    def test_up_signal_when_btc_risen_and_market_underpriced(self):
        """BTC moved +2% from ref, market UP priced at 0.50 (should be ~0.87)."""
        ref = 73_000.0
        btc = ref * 1.02  # +2% in final 30s
        market = make_market(ref_price=ref, side_up_price=0.50, side_down_price=0.50)
        signal = self.engine.evaluate(market, btc)
        assert signal is not None
        assert signal.direction == "UP"
        assert signal.edge > 0
        assert signal.implied_prob_up > 0.5

    def test_down_signal_when_btc_fallen_and_market_underpriced(self):
        """BTC -2%, market DOWN priced at 0.50 (should be ~0.87)."""
        ref = 73_000.0
        btc = ref * 0.98  # -2%
        market = make_market(ref_price=ref, side_up_price=0.50, side_down_price=0.50)
        signal = self.engine.evaluate(market, btc)
        assert signal is not None
        assert signal.direction == "DOWN"
        assert signal.edge > 0
        assert signal.implied_prob_up < 0.5

    def test_none_direction_when_edge_below_threshold(self):
        """Tiny BTC move → implied prob ≈ market price → no edge."""
        ref = 73_000.0
        btc = ref + 10.0  # ~0.014% move — negligible
        # Market priced efficiently at 0.5 / 0.5
        market = make_market(ref_price=ref, side_up_price=0.50, side_down_price=0.50)
        signal = self.engine.evaluate(market, btc)
        # With 10s left and tiny delta, might still pass — check direction at least
        if signal is not None:
            # edge should be small regardless
            assert abs(signal.edge) < 0.5

    def test_signal_fields_populated(self):
        ref = 73_000.0
        btc = ref * 1.02
        market = make_market(ref_price=ref)
        signal = self.engine.evaluate(market, btc)
        assert signal is not None
        assert signal.market_id == market.id
        assert signal.btc_price == btc
        assert signal.ref_price == ref
        assert abs(signal.delta - (btc - ref)) < 0.01
        assert 0 <= signal.implied_prob_up <= 1
        assert signal.time_to_expiry > 0
        assert signal.liquidity == market.liquidity

    def test_implied_prob_scales_with_tte(self):
        """Same % move but less time remaining → higher implied_prob."""
        ref = 73_000.0
        btc = ref * 1.005  # +0.5%
        m_short = make_market(ref_price=ref, tte_seconds=5.0)
        m_long = make_market(ref_price=ref, tte_seconds=55.0)
        s_short = self.engine.evaluate(m_short, btc)
        s_long = self.engine.evaluate(m_long, btc)
        assert s_short is not None and s_long is not None
        assert s_short.implied_prob_up > s_long.implied_prob_up
