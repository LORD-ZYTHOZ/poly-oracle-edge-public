"""Polymarket CLOB execution client — wraps py-clob-client."""
import asyncio
import logging
import os
from typing import Optional

from src.models import Trade, TradingMode

logger = logging.getLogger(__name__)

# CLOB order timeout — prevents blocking on Polygon congestion
ORDER_TIMEOUT_S = 10


class PolymarketClient:
    def __init__(self, mode: TradingMode = TradingMode.WATCH) -> None:
        self._mode = mode
        self._client = None

        if mode == TradingMode.LIVE:
            self._init_client()

    def _init_client(self) -> None:
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.constants import POLYGON

            key = os.environ.get("POLY_PRIVATE_KEY")
            if not key:
                raise ValueError("POLY_PRIVATE_KEY not set")

            self._client = ClobClient(
                host="https://clob.polymarket.com",
                key=key,
                chain_id=POLYGON,
            )
            logger.info("Polymarket CLOB client initialised (LIVE mode)")
        except ImportError:
            raise RuntimeError("py-clob-client not installed — run: pip install py-clob-client")

    async def place_order(self, trade: Trade) -> Optional[str]:
        """
        Place order. Returns tx_hash on success, None on failure.
        In WATCH/PAPER mode, logs and returns a simulated hash.
        """
        if self._mode == TradingMode.WATCH:
            logger.info("[WATCH] Would place %s %s @ %.4f size=%.2f",
                        trade.side, trade.market_id, trade.entry_price, trade.size)
            return None

        if self._mode == TradingMode.PAPER:
            fake_hash = f"paper_{trade.market_id[:8]}_{trade.side}"
            logger.info("[PAPER] Simulated order: %s", fake_hash)
            return fake_hash

        return await self._submit_live(trade)

    async def _submit_live(self, trade: Trade) -> Optional[str]:
        if not self._client:
            raise RuntimeError("CLOB client not initialised")

        for attempt in range(1, 4):
            try:
                from py_clob_client.clob_types import OrderArgs

                # Use the outcome token_id, NOT the conditionId (market_id)
                args = OrderArgs(
                    token_id=trade.token_id,
                    price=trade.entry_price,
                    size=trade.size,
                    side=trade.side,
                )

                # Wrap in asyncio timeout to prevent blocking on Polygon congestion
                loop = asyncio.get_event_loop()
                resp = await asyncio.wait_for(
                    loop.run_in_executor(None, self._client.create_and_post_order, args),
                    timeout=ORDER_TIMEOUT_S,
                )
                tx_hash = resp.get("orderID") or resp.get("transactionHash")
                logger.info("Order placed: %s (attempt %d)", tx_hash, attempt)
                return tx_hash

            except asyncio.TimeoutError:
                logger.warning("Order attempt %d timed out after %ds", attempt, ORDER_TIMEOUT_S)
            except Exception as exc:
                logger.warning("Order attempt %d failed: %s", attempt, exc)

            if attempt < 3:
                await asyncio.sleep(0.3)

        logger.error("All order attempts failed for %s", trade.market_id)
        return None
