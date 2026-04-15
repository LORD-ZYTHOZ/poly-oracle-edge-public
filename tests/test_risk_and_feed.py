"""Tests for RiskManager, poly_feed._parse_market, state_tracker coverage."""
import time
import pytest
from dataclasses import replace

from src.models import MarketWindow, MarketStatus, Signal, Trade, TradingMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_signal(direction="UP", edge=0.20, market_price_up=0.50,
                token_id="0xtoken_up"):
    return Signal(
        market_id="0xmkt001",
        ts=time.time(),
        btc_price=73_000.0,
        ref_price=72_000.0,
        delta=1_000.0,
        implied_prob_up=0.70,
        market_price_up=market_price_up,
        edge=edge,
        direction=direction,
        time_to_expiry=30.0,
        liquidity=15_000.0,
        token_id=token_id,
    )


def make_risk(bankroll=1000.0, **kwargs):
    from src.risk.risk_manager import RiskManager
    return RiskManager(starting_bankroll=bankroll, mode=TradingMode.PAPER, **kwargs)


# ---------------------------------------------------------------------------
# RiskManager
# ---------------------------------------------------------------------------

class TestRiskManager:
    def test_basic_trade_returned(self):
        rm = make_risk()
        trade = rm.evaluate(make_signal())
        assert trade is not None
        assert trade.side == "UP"
        assert trade.size > 0

    def test_none_direction_skipped(self):
        rm = make_risk()
        assert rm.evaluate(make_signal(direction="NONE")) is None

    def test_token_id_propagated_to_trade(self):
        rm = make_risk()
        trade = rm.evaluate(make_signal(token_id="0xfoo"))
        assert trade.token_id == "0xfoo"

    def test_down_direction_entry_price(self):
        rm = make_risk()
        trade = rm.evaluate(make_signal(direction="DOWN", market_price_up=0.60))
        assert abs(trade.entry_price - 0.40) < 1e-9  # 1 - 0.60

    def test_daily_stop_loss_halts(self):
        rm = make_risk(bankroll=1000.0, daily_stop_loss=0.05)
        # Inject a daily loss of 5%
        from dataclasses import replace as dc_replace
        rm.state = dc_replace(rm.state, daily_pnl=-50.0)
        assert rm.evaluate(make_signal()) is None
        assert rm.state.halted

    def test_halted_skips_all(self):
        rm = make_risk()
        from dataclasses import replace as dc_replace
        rm.state = dc_replace(rm.state, halted=True)
        assert rm.evaluate(make_signal()) is None

    def test_exposure_cap(self):
        rm = make_risk(bankroll=1000.0, max_open_exposure=0.02)
        # Fill exposure to cap
        from dataclasses import replace as dc_replace
        rm.state = dc_replace(rm.state, open_exposure=20.0)  # already at cap
        assert rm.evaluate(make_signal()) is None

    def test_kelly_sizing_capped_at_max_risk(self):
        rm = make_risk(bankroll=1000.0, max_risk_per_trade=0.02)
        trade = rm.evaluate(make_signal(edge=0.50))  # huge edge → kelly would be large
        assert trade.size <= 1000.0 * 0.02 + 1e-9  # capped at 2%

    def test_settlement_win_pnl_correct(self):
        """Win PnL = size * (1/price - 1) — returns proportional to stake."""
        rm = make_risk(bankroll=1000.0)
        trade = Trade(
            market_id="0xm", side="UP", size=20.0, entry_price=0.5,
            expected_value=4.0, mode=TradingMode.PAPER, token_id=""
        )
        rm.state = replace(rm.state, open_exposure=20.0)
        rm.record_settlement(trade, won=True)
        # pnl = 20 * (1/0.5 - 1) = 20 * 1.0 = 20
        assert abs(rm.state.bankroll - 1020.0) < 1e-9
        assert abs(rm.state.daily_pnl - 20.0) < 1e-9

    def test_settlement_loss_pnl_correct(self):
        """Loss PnL = -size (entire stake lost)."""
        rm = make_risk(bankroll=1000.0)
        trade = Trade(
            market_id="0xm", side="UP", size=20.0, entry_price=0.5,
            expected_value=4.0, mode=TradingMode.PAPER, token_id=""
        )
        rm.state = replace(rm.state, open_exposure=20.0)
        rm.record_settlement(trade, won=False)
        assert abs(rm.state.bankroll - 980.0) < 1e-9
        assert abs(rm.state.daily_pnl - (-20.0)) < 1e-9

    def test_settlement_reduces_exposure(self):
        rm = make_risk(bankroll=1000.0)
        trade = Trade(
            market_id="0xm", side="UP", size=20.0, entry_price=0.5,
            expected_value=4.0, mode=TradingMode.PAPER, token_id=""
        )
        rm.state = replace(rm.state, open_exposure=20.0)
        rm.record_settlement(trade, won=True)
        assert rm.state.open_exposure == 0.0

    def test_settlement_increments_trade_count(self):
        rm = make_risk()
        trade = Trade(
            market_id="0xm", side="UP", size=10.0, entry_price=0.5,
            expected_value=2.0, mode=TradingMode.PAPER, token_id=""
        )
        rm.record_settlement(trade, won=False)
        assert rm.state.trade_count == 1

    def test_pnl_win_at_0_9_price(self):
        """At 0.9 price, win profit = 20*(1/0.9 - 1) ≈ 2.22."""
        rm = make_risk(bankroll=1000.0)
        trade = Trade(
            market_id="0xm", side="UP", size=20.0, entry_price=0.9,
            expected_value=1.0, mode=TradingMode.PAPER, token_id=""
        )
        rm.state = replace(rm.state, open_exposure=20.0)
        rm.record_settlement(trade, won=True)
        expected_pnl = 20.0 * (1.0 / 0.9 - 1.0)
        assert abs(rm.state.bankroll - (1000.0 + expected_pnl)) < 1e-6


# ---------------------------------------------------------------------------
# poly_feed._parse_market
# ---------------------------------------------------------------------------

class TestParseMarket:
    from src.feeds.poly_feed import PolymarketFeedListener
    _parse = staticmethod(PolymarketFeedListener._parse_market)

    def _raw(self, **overrides):
        import json
        base = {
            "conditionId": "0xcondition001",
            "question": "Bitcoin Up or Down - Test",
            "outcomes": json.dumps(["Up", "Down"]),
            "outcomePrices": json.dumps(["0.55", "0.45"]),
            "endDate": "2026-03-17T15:30:00Z",
            "startDate": "2026-03-17T15:25:00Z",
            "clobTokenIds": json.dumps(["0xup_token", "0xdown_token"]),
            "liquidityClob": 15000.0,
            "closed": False,
        }
        base.update(overrides)
        return base

    def test_basic_parse(self):
        m = self._parse(self._raw())
        assert m is not None
        assert m.id == "0xcondition001"
        assert abs(m.side_up_price - 0.55) < 1e-9
        assert abs(m.side_down_price - 0.45) < 1e-9

    def test_token_ids_extracted(self):
        m = self._parse(self._raw())
        assert m.up_token_id == "0xup_token"
        assert m.down_token_id == "0xdown_token"

    def test_reversed_outcomes(self):
        import json
        m = self._parse(self._raw(
            outcomes=json.dumps(["Down", "Up"]),
            outcomePrices=json.dumps(["0.45", "0.55"]),
            clobTokenIds=json.dumps(["0xdown_token", "0xup_token"]),
        ))
        assert m is not None
        assert abs(m.side_up_price - 0.55) < 1e-9
        assert m.up_token_id == "0xup_token"
        assert m.down_token_id == "0xdown_token"

    def test_missing_start_date_defaults_to_end_minus_300(self):
        raw = self._raw()
        del raw["startDate"]
        m = self._parse(raw)
        assert m is not None
        assert abs(m.end_time - m.start_time - 300.0) < 1.0

    def test_returns_none_on_missing_condition_id(self):
        raw = self._raw()
        del raw["conditionId"]
        m = self._parse(raw)
        assert m is None

    def test_liquidity_fallback(self):
        raw = self._raw()
        del raw["liquidityClob"]
        raw["liquidity"] = 9999.0
        m = self._parse(raw)
        assert m.liquidity == 9999.0


# ---------------------------------------------------------------------------
# StateTracker — purge_settled and active_count
# ---------------------------------------------------------------------------

class TestStateTrackerCoverage:
    def _make_market(self, mid, tte=300.0, status=MarketStatus.LIVE):
        now = time.time()
        return MarketWindow(
            id=mid, start_time=now-60, end_time=now+tte,
            ref_price=73000.0, side_up_price=0.5, side_down_price=0.5,
            liquidity=10000.0, status=status,
        )

    def test_purge_settled_removes_expired(self):
        from src.core.state_tracker import MarketStateTracker
        tracker = MarketStateTracker()
        now = time.time()
        # Expired 2 minutes ago
        expired = MarketWindow(
            id="0xexpired", start_time=now-400, end_time=now-120,
            ref_price=73000.0, side_up_price=0.5, side_down_price=0.5,
            liquidity=10000.0,
        )
        live = self._make_market("0xlive", tte=300.0)
        tracker.upsert(expired)
        tracker.upsert(live)
        removed = tracker.purge_settled()
        assert removed == 1
        assert tracker.get("0xexpired") is None
        assert tracker.get("0xlive") is not None

    def test_purge_settled_keeps_recent_expired(self):
        """Markets expired <60s ago are kept (buffer)."""
        from src.core.state_tracker import MarketStateTracker
        tracker = MarketStateTracker()
        now = time.time()
        recent = MarketWindow(
            id="0xrecent", start_time=now-70, end_time=now-30,
            ref_price=73000.0, side_up_price=0.5, side_down_price=0.5,
            liquidity=10000.0,
        )
        tracker.upsert(recent)
        removed = tracker.purge_settled()
        assert removed == 0

    def test_active_count_excludes_settled(self):
        from src.core.state_tracker import MarketStateTracker
        tracker = MarketStateTracker()
        tracker.upsert(self._make_market("0xlive1"))
        tracker.upsert(self._make_market("0xlive2"))
        tracker.upsert(self._make_market("0xsettled", status=MarketStatus.SETTLED))
        assert tracker.active_count == 2
