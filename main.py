import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3), name="MSK")
DAILY_TIME = time(8, 0)
FINAL_TIME = time(9, 0)


STANDING_PHRASES = [
    "Ну что, снова стоим.",
    "Доброе утро. Пора немного пострадать.",
    "Сегодня без отмазок, поехали.",
    "Встаём, собираемся, держим.",
    "Ну всё, пришло время планки.",
    "Погнали, пока энтузиазм не передумал.",
    "Опять она. Планка.",
    "Сегодня коротко: сделали и свободны.",
    "Пора немного напрячь красивое.",
    "Поехали, пока не нашли причину отложить.",
    "Сегодня просто берём и делаем.",
    "Так, собрались. Сегодня день планки.",
    "Погнали держать лицо и корпус.",
    "Планка сама себя не постоит.",
    "Сегодня работаем без героизма, но честно.",
    "Ну что, стоим как взрослые люди.",
    "Секунд немного, нытья тоже много не надо.",
    "Сегодня просто не филоним.",
    "Пора встать в планку, а не в позу.",
    "Сегодня стоим красиво. Ну или хотя бы стоим.",
]

REST_PHRASES = [
    "Сегодня официальный день ничегонеделания.",
    "Всё, сегодня можно не дрожать.",
    "Сегодня лежим с чистой совестью.",
    "Сегодня день без локтей и страданий.",
]

SPECIAL_PHRASES = [
    "Сегодня ещё и бонус — спецзадание.",
    "Мало не покажется: сегодня спецзадание.",
    "А вот и сюрприз — сегодня спецзадание.",
    "Сегодня программа с добавкой: есть спецзадание.",
    "Кто хотел поинтереснее — сегодня спецзадание.",
    "Сегодня комплект полный: планка и спецзадание.",
]

DAY_PLAN: Dict[int, Dict[str, str]] = {
    1: {"type": "stand", "time": "20 сек"},
    2: {"type": "stand", "time": "20 сек"},
    3: {"type": "stand", "time": "30 сек"},
    4: {"type": "stand", "time": "30 сек"},
    5: {"type": "special", "time": "40 сек"},
    6: {"type": "rest"},
    7: {"type": "stand", "time": "45 сек"},
    8: {"type": "stand", "time": "45 сек"},
    9: {"type": "stand", "time": "1 мин"},
    10: {"type": "special", "time": "1 мин"},
    11: {"type": "stand", "time": "1 мин"},
    12: {"type": "stand", "time": "1 мин 30 сек"},
    13: {"type": "rest"},
    14: {"type": "stand", "time": "1 мин 40 сек"},
    15: {"type": "special", "time": "1 мин 50 сек"},
    16: {"type": "stand", "time": "2 мин"},
    17: {"type": "stand", "time": "2 мин"},
    18: {"type": "stand", "time": "2 мин 30 сек"},
    19: {"type": "rest"},
    20: {"type": "special", "time": "2 мин 30 сек"},
    21: {"type": "stand", "time": "2 мин 30 сек"},
    22: {"type": "stand", "time": "3 мин"},
    23: {"type": "stand", "time": "3 мин"},
    24: {"type": "stand", "time": "3 мин 30 сек"},
    25: {"type": "special", "time": "3 мин 30 сек"},
    26: {"type": "rest"},
    27: {"type": "stand", "time": "4 мин"},
    28: {"type": "stand", "time": "4 мин"},
    29: {"type": "stand", "time": "4 мин 30 сек"},
    30: {"type": "special", "time": "5 мин"},
}

STANDING_DAYS = [1, 2, 3, 4, 7, 8, 9, 11, 12, 14, 16, 17, 18, 21, 22, 23, 24, 27, 28, 29]
REST_DAYS = [6, 13, 19, 26]
SPECIAL_DAYS = [5, 10, 15, 20, 25, 30]


@dataclass
class AppConfig:
    bot_token: str
    chat_id: int



def load_config() -> AppConfig:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    chat_id_raw = os.getenv("CHAT_ID", "").strip()

    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not set")
    if not chat_id_raw:
        raise RuntimeError("CHAT_ID is not set")

    try:
        chat_id = int(chat_id_raw)
    except ValueError as exc:
        raise RuntimeError("CHAT_ID must be an integer") from exc

    return AppConfig(bot_token=bot_token, chat_id=chat_id)


class PlankChallengeBot:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.scheduler = AsyncIOScheduler(timezone=MSK)
        self.challenge_start_date = self._calculate_challenge_start_date()
        self.final_date = self.challenge_start_date + timedelta(days=30)
        self.last_daily_sent_for: Optional[date] = None
        self.final_sent_for: Optional[date] = None

        self._validate_configuration()
        self._standing_phrase_by_day = dict(zip(STANDING_DAYS, STANDING_PHRASES))
        self._rest_phrase_by_day = dict(zip(REST_DAYS, REST_PHRASES))
        self._special_phrase_by_day = dict(zip(SPECIAL_DAYS, SPECIAL_PHRASES))

    @staticmethod
    def _calculate_challenge_start_date(now: Optional[datetime] = None) -> date:
        current = now.astimezone(MSK) if now else datetime.now(MSK)
        return current.date() + timedelta(days=1)

    def _validate_configuration(self) -> None:
        if sorted(DAY_PLAN.keys()) != list(range(1, 31)):
            raise RuntimeError("DAY_PLAN must contain all days from 1 to 30")

        if len(STANDING_DAYS) != len(STANDING_PHRASES):
            raise RuntimeError("Standing phrases count does not match standing days count")
        if len(REST_DAYS) != len(REST_PHRASES):
            raise RuntimeError("Rest phrases count does not match rest days count")
        if len(SPECIAL_DAYS) != len(SPECIAL_PHRASES):
            raise RuntimeError("Special phrases count does not match special days count")

        for day in STANDING_DAYS:
            if DAY_PLAN[day]["type"] != "stand":
                raise RuntimeError(f"Day {day} must be stand day")
        for day in REST_DAYS:
            if DAY_PLAN[day]["type"] != "rest":
                raise RuntimeError(f"Day {day} must be rest day")
        for day in SPECIAL_DAYS:
            if DAY_PLAN[day]["type"] != "special":
                raise RuntimeError(f"Day {day} must be special day")

    @staticmethod
    def _current_msk_datetime() -> datetime:
        return datetime.now(MSK)

    def _day_number_for_date(self, target_date: date) -> int:
        return (target_date - self.challenge_start_date).days + 1

    def _build_daily_message(self, day_number: int) -> str:
        day_info = DAY_PLAN[day_number]
        day_type = day_info["type"]

        if day_type == "stand":
            phrase = self._standing_phrase_by_day[day_number]
            return f"{phrase}\nДень {day_number}.\nСегодня стоим {day_info['time']}."

        if day_type == "rest":
            phrase = self._rest_phrase_by_day[day_number]
            return f"{phrase}\nДень {day_number}.\nСегодня отдых."

        if day_type == "special":
            phrase = self._special_phrase_by_day[day_number]
            return (
                f"{phrase}\n"
                f"День {day_number}.\n"
                f"Сегодня стоим {day_info['time']}.\n"
                f"Сегодня есть спецзадание."
            )

        raise ValueError(f"Unknown day type: {day_type}")

    @staticmethod
    def _build_final_message() -> str:
        return "Всё, бобры, доплыли 🦫\nЧеллендж завершён.\nСпасибо всем за участие."

    async def send_daily_message_if_needed(self, bot: Bot) -> None:
        now = self._current_msk_datetime()
        today = now.date()

        if today == self.last_daily_sent_for:
            logger.info("Daily message for %s already sent", today)
            return

        day_number = self._day_number_for_date(today)
        if day_number < 1 or day_number > 30:
            logger.info("No daily message scheduled for %s (day_number=%s)", today, day_number)
            return

        message = self._build_daily_message(day_number)
        await bot.send_message(chat_id=self.config.chat_id, text=message)
        self.last_daily_sent_for = today
        logger.info("Sent daily message for day %s", day_number)

    async def send_final_message_if_needed(self, bot: Bot) -> None:
        now = self._current_msk_datetime()
        today = now.date()

        if today == self.final_sent_for:
            logger.info("Final message for %s already sent", today)
            return

        if today != self.final_date:
            logger.info("No final message scheduled for %s", today)
            return

        await bot.send_message(chat_id=self.config.chat_id, text=self._build_final_message())
        self.final_sent_for = today
        logger.info("Sent final message")

    def start_scheduler(self, bot: Bot) -> None:
        self.scheduler.add_job(
            self.send_daily_message_if_needed,
            CronTrigger(hour=DAILY_TIME.hour, minute=DAILY_TIME.minute, timezone=MSK),
            args=[bot],
            id="daily_message",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=3600,
        )
        self.scheduler.add_job(
            self.send_final_message_if_needed,
            CronTrigger(hour=FINAL_TIME.hour, minute=FINAL_TIME.minute, timezone=MSK),
            args=[bot],
            id="final_message",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=3600,
        )
        self.scheduler.start()
        logger.info(
            "Scheduler started. challenge_start_date=%s final_date=%s",
            self.challenge_start_date,
            self.final_date,
        )

    async def run(self) -> None:
        async with Bot(token=self.config.bot_token) as bot:
            me = await bot.get_me()
            logger.info("Bot started: @%s", me.username)
            self.start_scheduler(bot)

            try:
                while True:
                    await asyncio.sleep(3600)
            finally:
                if self.scheduler.running:
                    self.scheduler.shutdown(wait=False)


async def main() -> None:
    config = load_config()
    app = PlankChallengeBot(config)
    await app.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
