"""Binance WebSocket BTC/USDT feed — normalizes ticks into a shared queue."""
import asyncio
import json
import logging
import time
from typing import Callable, Awaitable

import websockets

from src.models import Tick

logger = logging.getLogger(__name__)

BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"
RECONNECT_DELAY = 3  # seconds


class BTCFeedListener:
    def __init__(
        self,
        on_tick: Callable[[Tick], Awaitable[None]],
        ws_url: str = BINANCE_WS,
    ):
        self._on_tick = on_tick
        self._ws_url = ws_url
        self._running = False
        self.last_price: float | None = None
        self.last_ts: float | None = None

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._connect()
            except Exception as exc:
                logger.warning("BTC feed disconnected: %s — reconnecting in %ds", exc, RECONNECT_DELAY)
                await asyncio.sleep(RECONNECT_DELAY)

    async def stop(self) -> None:
        self._running = False

    async def _connect(self) -> None:
        async with websockets.connect(self._ws_url, ping_interval=20) as ws:
            logger.info("BTC feed connected: %s", self._ws_url)
            async for raw in ws:
                if not self._running:
                    break
                tick = self._parse(raw)
                if tick:
                    self.last_price = tick.price
                    self.last_ts = tick.ts
                    await self._on_tick(tick)

    @staticmethod
    def _parse(raw: str) -> Tick | None:
        try:
            msg = json.loads(raw)
            return Tick(
                exchange="binance",
                symbol="BTCUSDT",
                ts=msg["T"] / 1000.0,
                price=float(msg["p"]),
            )
        except Exception as exc:
            logger.debug("Failed to parse tick: %s", exc)
            return None
