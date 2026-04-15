"""Posts signals from M1 scanner to USA VPS executor."""
import hashlib
import hmac
import json
import logging
import os

import aiohttp

from src.models import Signal, TradingMode

logger = logging.getLogger(__name__)


class SignalSender:
    def __init__(
        self,
        executor_url: str,
        secret: str,
        mode: TradingMode = TradingMode.WATCH,
    ) -> None:
        self._url = executor_url.rstrip("/") + "/signal"
        self._secret = secret
        self._mode = mode
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5)
        )

    async def stop(self) -> None:
        if self._session:
            await self._session.close()

    async def send(self, signal: Signal, size: float, entry_price: float) -> dict | None:
        if self._mode == TradingMode.WATCH:
            logger.info("[WATCH] Signal not sent — watch mode")
            return None

        payload = {
            "market_id": signal.market_id,
            "direction": signal.direction,
            "entry_price": entry_price,
            "size": size,
            "edge": signal.edge,
            "time_to_expiry": signal.time_to_expiry,
            "btc_price": signal.btc_price,
            "ref_price": signal.ref_price,
            "ts": signal.ts,
            "token_id": signal.token_id,
        }

        body = json.dumps(payload).encode()
        sig = hmac.new(self._secret.encode(), body, hashlib.sha256).hexdigest()

        try:
            async with self._session.post(
                self._url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": sig,
                },
            ) as resp:
                result = await resp.json()
                logger.info(
                    "EXECUTOR | status=%s | tx=%s",
                    result.get("status"), result.get("tx_hash"),
                )
                return result
        except Exception as exc:
            logger.error("Failed to send signal to executor: %s", exc)
            return None
