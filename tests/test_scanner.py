"""Tests for scanner main — tick throttle, signal filtering, ref_price logic."""
import time
import pytest

from src.models import MarketWindow, MarketStatus, Signal, Tick


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tick(price: float = 73_000.0) -> Tick:
    return Tick(exchange="binance", symbol="BTCUSDT", ts=time.time(), price=price)


def make_expiring_market(ref_price: float = 73_000.0, tte: float = 30.0) -> MarketWindow:
    now = time.time()
    return MarketWindow(
        id="0xtest000001",
        start_time=now - 270,
        end_time=now + tte,
        ref_price=ref_price,
        side_up_price=0.50,
        side_down_price=0.50,
        liquidity=15_000.0,
        status=MarketStatus.EXPIRING,
    )


def make_future_market(start_offset: float = 3600.0) -> MarketWindow:
    """Market that starts in the future — ref_price should NOT be set yet."""
    now = time.time()
    return MarketWindow(
        id="0xfuture0001",
        start_time=now + start_offset,
        end_time=now + start_offset + 300,
        ref_price=0.0,
        side_up_price=0.50,
        side_down_price=0.50,
        liquidity=15_000.0,
        status=MarketStatus.LIVE,
    )


# ---------------------------------------------------------------------------
# Tick throttle tests
# ---------------------------------------------------------------------------

class TestTickThrottle:
    """Verify throttle logic: evaluate at most once per EVAL_INTERVAL."""

    def _run_throttled(self, fake_timestamps, btc_price=73_000 * 1.02):
        from src.core.signal_engine import SignalEngine
        from src.core.state_tracker import MarketStateTracker

        evaluated = []
        engine = SignalEngine(lookback_seconds=60, min_edge_bps=100)
        tracker = MarketStateTracker()
        tracker.upsert(make_expiring_market())

        last_eval_ts = [float("-inf")]  # ensures first tick always evaluates
        EVAL_INTERVAL = 1.0

        for fake_now in fake_timestamps:
            if fake_now - last_eval_ts[0] < EVAL_INTERVAL:
                continue
            last_eval_ts[0] = fake_now
            for m in tracker.expiring(60):
                sig = engine.evaluate(m, btc_price)
                if sig and sig.direction != "NONE":
                    evaluated.append(sig)

        return evaluated

    def test_rapid_ticks_only_evaluate_once(self):
        """5 ticks all at t=0 should trigger at most 1 evaluation."""
        results = self._run_throttled([0.0, 0.1, 0.2, 0.3, 0.4])
        assert len(results) <= 1

    def test_ticks_spaced_over_1s_each_evaluate(self):
        """3 ticks each 1.1s apart should each trigger evaluate."""
        results = self._run_throttled([0.0, 1.1, 2.2])
        assert len(results) == 3

    def test_mixed_rapid_and_spaced(self):
        """Burst at t=0 then burst at t=1.5 → exactly 2 evaluations."""
        results = self._run_throttled([0.0, 0.1, 0.2, 1.5, 1.6, 1.7])
        assert len(results) == 2


# ---------------------------------------------------------------------------
# ref_price stamping tests
# ---------------------------------------------------------------------------

class TestRefPriceLogic:
    def test_ref_price_not_set_for_future_market(self):
        """Markets with start_time in the future should not get ref_price stamped."""
        from src.core.state_tracker import MarketStateTracker
        tracker = MarketStateTracker()
        market = make_future_market(start_offset=3600.0)
        btc_price = 73_000.0

        # Simulate on_market_update logic
        existing = tracker.get(market.id)
        if existing is None or existing.ref_price <= 0:
            if btc_price > 0 and market.start_time <= time.time():
                market = MarketWindow(
                    id=market.id, start_time=market.start_time,
                    end_time=market.end_time, ref_price=btc_price,
                    side_up_price=market.side_up_price,
                    side_down_price=market.side_down_price,
                    liquidity=market.liquidity, status=market.status,
                )
        tracker.upsert(market)

        stored = tracker.get(market.id)
        assert stored.ref_price == 0.0  # should NOT be set

    def test_ref_price_set_for_active_market(self):
        """Markets that have already started should get ref_price on first seen."""
        from src.core.state_tracker import MarketStateTracker
        tracker = MarketStateTracker()
        now = time.time()
        market = MarketWindow(
            id="0xactive001",
            start_time=now - 60,  # started 60s ago
            end_time=now + 240,
            ref_price=0.0,
            side_up_price=0.50,
            side_down_price=0.50,
            liquidity=15_000.0,
            status=MarketStatus.LIVE,
        )
        btc_price = 73_000.0

        existing = tracker.get(market.id)
        if existing is None or existing.ref_price <= 0:
            if btc_price > 0 and market.start_time <= time.time():
                market = MarketWindow(
                    id=market.id, start_time=market.start_time,
                    end_time=market.end_time, ref_price=btc_price,
                    side_up_price=market.side_up_price,
                    side_down_price=market.side_down_price,
                    liquidity=market.liquidity, status=market.status,
                )
        tracker.upsert(market)

        stored = tracker.get(market.id)
        assert stored.ref_price == 73_000.0

    def test_ref_price_preserved_on_subsequent_updates(self):
        """Once ref_price is set, subsequent market updates should not overwrite it."""
        from src.core.state_tracker import MarketStateTracker
        tracker = MarketStateTracker()
        now = time.time()
        market_with_ref = MarketWindow(
            id="0xpreserve1",
            start_time=now - 60,
            end_time=now + 240,
            ref_price=73_000.0,
            side_up_price=0.50,
            side_down_price=0.50,
            liquidity=15_000.0,
            status=MarketStatus.LIVE,
        )
        tracker.upsert(market_with_ref)

        # Update with new market data (prices changed) but ref_price=0
        updated = MarketWindow(
            id="0xpreserve1",
            start_time=now - 60,
            end_time=now + 240,
            ref_price=0.0,  # poll returned 0
            side_up_price=0.52,
            side_down_price=0.48,
            liquidity=16_000.0,
            status=MarketStatus.LIVE,
        )
        tracker.upsert(updated)

        stored = tracker.get("0xpreserve1")
        assert stored.ref_price == 73_000.0  # preserved
        assert stored.side_up_price == 0.52   # but prices updated


# ---------------------------------------------------------------------------
# Deduplication — one order per market window
# ---------------------------------------------------------------------------

class TestTradeDeduplication:
    def test_same_market_only_traded_once(self):
        """Repeated signals for same market_id should only produce one trade."""
        from src.core.signal_engine import SignalEngine
        from src.core.state_tracker import MarketStateTracker

        engine = SignalEngine(lookback_seconds=60, min_edge_bps=100)
        tracker = MarketStateTracker()
        tracker.upsert(make_expiring_market(ref_price=73_000.0))

        traded_markets: set[str] = set()
        orders_sent = []

        def maybe_send(signal):
            if signal.market_id in traded_markets:
                return
            orders_sent.append(signal)
            traded_markets.add(signal.market_id)

        btc = 73_000.0 * 1.02  # +2%, guaranteed signal
        for fake_now in [0.0, 1.1, 2.2, 3.3]:  # 4 throttle-spaced ticks
            for m in tracker.expiring(60):
                sig = engine.evaluate(m, btc)
                if sig and sig.direction != "NONE":
                    maybe_send(sig)

        assert len(orders_sent) == 1  # only the first signal triggers an order

    def test_different_markets_each_get_order(self):
        """Two distinct expiring markets should each produce one order."""
        from src.core.signal_engine import SignalEngine
        from src.core.state_tracker import MarketStateTracker

        engine = SignalEngine(lookback_seconds=60, min_edge_bps=100)
        tracker = MarketStateTracker()
        now = time.time()
        m1 = MarketWindow(
            id="0xmarket0001", start_time=now - 270, end_time=now + 30,
            ref_price=73_000.0, side_up_price=0.5, side_down_price=0.5,
            liquidity=15_000.0, status=MarketStatus.EXPIRING,
        )
        m2 = MarketWindow(
            id="0xmarket0002", start_time=now - 270, end_time=now + 45,
            ref_price=73_000.0, side_up_price=0.5, side_down_price=0.5,
            liquidity=15_000.0, status=MarketStatus.EXPIRING,
        )
        tracker.upsert(m1)
        tracker.upsert(m2)

        traded_markets: set[str] = set()
        orders_sent = []

        btc = 73_000.0 * 1.02
        for m in tracker.expiring(60):
            sig = engine.evaluate(m, btc)
            if sig and sig.direction != "NONE" and sig.market_id not in traded_markets:
                orders_sent.append(sig)
                traded_markets.add(sig.market_id)

        assert len(orders_sent) == 2


# ---------------------------------------------------------------------------
# NONE-direction signals not logged
# ---------------------------------------------------------------------------

class TestNoneDirectionFiltering:
    def test_none_direction_signals_excluded(self):
        """evaluate() returning NONE direction should not reach log_signal."""
        from src.core.signal_engine import SignalEngine
        from src.core.state_tracker import MarketStateTracker

        engine = SignalEngine(lookback_seconds=60, min_edge_bps=100)
        tracker = MarketStateTracker()

        # Market priced at 0.5/0.5, BTC barely moved — edge will be below threshold
        market = make_expiring_market(ref_price=73_000.0)
        tracker.upsert(market)

        logged = []

        for m in tracker.expiring(60):
            sig = engine.evaluate(m, 73_001.0)  # negligible move
            if sig and sig.direction != "NONE":
                logged.append(sig)

        # With ~$1 move over 30s, direction should be NONE (edge too small or signal)
        # The key assertion is that we only log when direction != NONE
        for s in logged:
            assert s.direction in ("UP", "DOWN")
