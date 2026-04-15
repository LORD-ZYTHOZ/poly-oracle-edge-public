"""Polls Polymarket CLOB API for active 5-minute BTC markets."""
import asyncio
import logging
import time
from typing import Callable, Awaitable

import aiohttp

from src.models import MarketWindow, MarketStatus

logger = logging.getLogger(__name__)

CLOB_BASE = "https://clob.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"

# Search keyword for 5-min BTC up/down markets
BTC_SEARCH = "bitcoin up or down"


class PolymarketFeedListener:
    def __init__(
        self,
        on_market_update: Callable[[MarketWindow], Awaitable[None]],
        poll_interval: float = 5.0,
    ):
        self._on_market_update = on_market_update
        self._poll_interval = poll_interval
        self._running = False
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        self._running = True
        async with aiohttp.ClientSession() as session:
            self._session = session
            while self._running:
                try:
                    await self._poll()
                except Exception as exc:
                    logger.warning("Polymarket poll error: %s", exc)
                await asyncio.sleep(self._poll_interval)

    async def stop(self) -> None:
        self._running = False

    async def _poll(self) -> None:
        markets = await self._fetch_active_markets()
        for raw in markets:
            market = self._parse_market(raw)
            if market:
                await self._on_market_update(market)

    async def _fetch_active_markets(self) -> list[dict]:
        """Fetch active BTC 5-min markets from Gamma API."""
        from datetime import datetime, timezone

        params = {
            "limit": 500,
            "order": "startDate",
            "ascending": "false",
        }
        async with self._session.get(f"{GAMMA_BASE}/markets", params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()
            markets = data.get("markets", data) if isinstance(data, dict) else data
            now = datetime.now(timezone.utc)
            return [
                m for m in markets
                if BTC_SEARCH in m.get("question", "").lower()
                and not m.get("closed", True)
                and datetime.fromisoformat(m["endDate"].replace("Z", "+00:00")) > now
            ]

    @staticmethod
    def _parse_market(raw: dict) -> MarketWindow | None:
        try:
            import json as _json
            from datetime import datetime, timezone

            # Parse outcome prices — "[\"0.505\", \"0.495\"]"
            outcomes = _json.loads(raw.get("outcomes", '["Up","Down"]'))
            prices_raw = _json.loads(raw.get("outcomePrices", '["0.5","0.5"]'))
            prices = [float(p) for p in prices_raw]

            up_idx = next((i for i, o in enumerate(outcomes) if o.lower() == "up"), 0)
            down_idx = next((i for i, o in enumerate(outcomes) if o.lower() == "down"), 1)

            side_up_price = prices[up_idx] if up_idx < len(prices) else 0.5
            side_down_price = prices[down_idx] if down_idx < len(prices) else 0.5

            # Parse timestamps
            def parse_ts(s: str) -> float:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()

            end_time = parse_ts(raw["endDate"])
            # Fallback: if no startDate, assume 5-min window (300s before end)
            start_time = parse_ts(raw["startDate"]) if raw.get("startDate") else end_time - 300.0

            # Token IDs for order placement (ERC1155 outcome tokens, not conditionId)
            clob_ids = _json.loads(raw.get("clobTokenIds", "[]"))
            up_token_id = clob_ids[up_idx] if up_idx < len(clob_ids) else ""
            down_token_id = clob_ids[down_idx] if down_idx < len(clob_ids) else ""

            now = time.time()
            if end_time < now:
                status = MarketStatus.SETTLED
            elif end_time - now <= 20:
                status = MarketStatus.EXPIRING
            else:
                status = MarketStatus.LIVE

            return MarketWindow(
                id=str(raw["conditionId"]),
                start_time=start_time,
                end_time=end_time,
                ref_price=0.0,  # stamped from BTC feed at market start
                side_up_price=side_up_price,
                side_down_price=side_down_price,
                liquidity=float(raw.get("liquidityClob", raw.get("liquidity", 0))),
                status=status,
                up_token_id=up_token_id,
                down_token_id=down_token_id,
            )
        except Exception as exc:
            logger.debug("Failed to parse market %s: %s", raw.get("conditionId"), exc)
            return None
