"""Core data models — immutable dataclasses throughout."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class MarketStatus(str, Enum):
    PENDING = "pending"
    LIVE = "live"
    EXPIRING = "expiring"   # within lookback_seconds of end
    SETTLED = "settled"


class TradeStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    FAILED = "failed"
    SETTLED = "settled"


class TradingMode(str, Enum):
    WATCH = "watch"
    PAPER = "paper"
    LIVE = "live"


@dataclass(frozen=True)
class MarketWindow:
    id: str
    start_time: float           # unix timestamp
    end_time: float             # unix timestamp
    ref_price: float            # BTC price at market start
    side_up_price: float        # current YES price (0–1)
    side_down_price: float      # current NO price (0–1)
    liquidity: float            # total USDC liquidity
    status: MarketStatus = MarketStatus.LIVE
    up_token_id: str = ""       # CLOB ERC1155 token ID for UP outcome
    down_token_id: str = ""     # CLOB ERC1155 token ID for DOWN outcome

    @property
    def time_to_expiry(self) -> float:
        return self.end_time - time.time()


@dataclass(frozen=True)
class Tick:
    exchange: str
    symbol: str
    ts: float                   # unix timestamp
    price: float
    bid: Optional[float] = None
    ask: Optional[float] = None


@dataclass(frozen=True)
class Signal:
    market_id: str
    ts: float
    btc_price: float
    ref_price: float
    delta: float                # btc_price - ref_price
    implied_prob_up: float      # model's fair probability of UP winning
    market_price_up: float      # current market price of UP
    edge: float                 # implied_prob_up - market_price_up
    direction: str              # "UP" | "DOWN" | "NONE"
    time_to_expiry: float
    liquidity: float
    token_id: str = ""          # CLOB outcome token ID for the chosen direction


@dataclass(frozen=True)
class Trade:
    market_id: str
    side: str                   # "UP" | "DOWN"
    size: float                 # USDC to stake
    entry_price: float          # 0–1
    expected_value: float
    mode: TradingMode
    token_id: str = ""          # CLOB outcome token ID (same as signal.token_id)
    ts: float = field(default_factory=time.time)
    status: TradeStatus = TradeStatus.PENDING
    fill_price: Optional[float] = None
    pnl: Optional[float] = None
    tx_hash: Optional[str] = None
