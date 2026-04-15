"""Optional Telegram alerter — sends trade notifications to a chat."""
import logging

logger = logging.getLogger(__name__)


class TelegramAlerter:
    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id
        self._bot = None

        if token and chat_id:
            try:
                from telegram import Bot
                self._bot = Bot(token=token)
                logger.info("Telegram alerter initialised (chat_id=%s)", chat_id)
            except ImportError:
                logger.warning("python-telegram-bot not installed — alerts disabled")

    async def send(self, message: str) -> None:
        if not self._bot:
            return
        try:
            await self._bot.send_message(chat_id=self._chat_id, text=message)
        except Exception as exc:
            logger.warning("Telegram send failed: %s", exc)
