"""In-memory registry of all live markets and their state."""
import logging
import time
from typing import Optional

from src.models import MarketWindow, MarketStatus

logger = logging.getLogger(__name__)


class MarketStateTracker:
    def __init__(self) -> None:
        self._markets: dict[str, MarketWindow] = {}

    def upsert(self, market: MarketWindow) -> None:
        """Add or update a market. Preserves ref_price from first seen."""
        existing = self._markets.get(market.id)

        if existing and existing.ref_price and not market.ref_price:
            # Preserve ref_price and token IDs from first snapshot
            market = MarketWindow(
                id=market.id,
                start_time=market.start_time,
                end_time=market.end_time,
                ref_price=existing.ref_price,
                side_up_price=market.side_up_price,
                side_down_price=market.side_down_price,
                liquidity=market.liquidity,
                status=market.status,
                up_token_id=market.up_token_id or existing.up_token_id,
                down_token_id=market.down_token_id or existing.down_token_id,
            )

        self._markets[market.id] = market

    def get(self, market_id: str) -> Optional[MarketWindow]:
        return self._markets.get(market_id)

    def expiring(self, lookback_seconds: float) -> list[MarketWindow]:
        """Return markets within lookback_seconds of expiry."""
        now = time.time()
        return [
            m for m in self._markets.values()
            if m.status != MarketStatus.SETTLED
            and 0 < m.end_time - now <= lookback_seconds
        ]

    def purge_settled(self) -> int:
        """Remove settled/expired markets. Returns count removed."""
        now = time.time()
        to_remove = [
            mid for mid, m in self._markets.items()
            if m.end_time < now - 60  # keep 60s buffer after expiry
        ]
        for mid in to_remove:
            del self._markets[mid]
        return len(to_remove)

    @property
    def active_count(self) -> int:
        return sum(1 for m in self._markets.values() if m.status != MarketStatus.SETTLED)
