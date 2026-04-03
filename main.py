import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Set

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3), name="MSK")
DAILY_TIME = time(8, 0)
FINAL_TIME = time(9, 0)

START_COMMAND = "start"
HELP_COMMAND = "help"
STATUS_COMMAND = "status"
TODAY_COMMAND = "today"
SETDAY_COMMAND = "setday"
START_CHALLENGE_COMMAND = "start_challenge"
STOP_CHALLENGE_COMMAND = "stop_challenge"
RESTART_CHALLENGE_COMMAND = "restart_challenge"

BTN_STATUS = "Статус"
BTN_TODAY = "Сегодня"
BTN_START = "Запустить"
BTN_STOP = "Остановить"
BTN_RESTART = "Перезапустить"
BTN_HELP = "Помощь"
KNOWN_BUTTON_LABELS = (BTN_STATUS, BTN_TODAY, BTN_START, BTN_STOP, BTN_RESTART, BTN_HELP)
BUTTON_TEXT_REGEX = re.compile(rf"^({'|'.join(re.escape(label) for label in KNOWN_BUTTON_LABELS)})$")


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
    state_path: Path
    admin_ids: Set[int]


@dataclass
class BotState:
    challenge_start_date: date
    challenge_active: bool = True
    last_daily_sent_for: Optional[date] = None
    final_sent_for: Optional[date] = None


def _parse_iso_date(value: str, source_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError(f"{source_name} must be in YYYY-MM-DD format") from exc


def _parse_admin_ids(value: str) -> Set[int]:
    ids: Set[int] = set()
    raw_items = [item.strip() for item in value.split(",") if item.strip()]
    if not raw_items:
        raise RuntimeError("ADMIN_IDS must contain at least one integer user id")

    for raw in raw_items:
        try:
            ids.add(int(raw))
        except ValueError as exc:
            raise RuntimeError("ADMIN_IDS must be comma-separated integers") from exc
    return ids


def load_config() -> AppConfig:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    chat_id_raw = os.getenv("CHAT_ID", "").strip()
    state_path_raw = os.getenv("STATE_PATH", "bot_state.json").strip()
    admin_ids_raw = os.getenv("ADMIN_IDS", "").strip()

    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not set")
    if not chat_id_raw:
        raise RuntimeError("CHAT_ID is not set")
    if not admin_ids_raw:
        raise RuntimeError("ADMIN_IDS is not set")

    try:
        chat_id = int(chat_id_raw)
    except ValueError as exc:
        raise RuntimeError("CHAT_ID must be an integer") from exc

    state_path = Path(state_path_raw).expanduser()
    if not state_path.is_absolute():
        state_path = Path.cwd() / state_path

    admin_ids = _parse_admin_ids(admin_ids_raw)
    return AppConfig(bot_token=bot_token, chat_id=chat_id, state_path=state_path, admin_ids=admin_ids)


class PlankChallengeBot:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.application: Optional[Application] = None
        self.scheduler = AsyncIOScheduler(timezone=MSK)
        self._send_lock = asyncio.Lock()
        self._validate_configuration()

        self._standing_phrase_by_day = dict(zip(STANDING_DAYS, STANDING_PHRASES))
        self._rest_phrase_by_day = dict(zip(REST_DAYS, REST_PHRASES))
        self._special_phrase_by_day = dict(zip(SPECIAL_DAYS, SPECIAL_PHRASES))

        self.state = self._load_or_create_state()

    @staticmethod
    def _calculate_challenge_start_date(now: Optional[datetime] = None) -> date:
        current = now.astimezone(MSK) if now else datetime.now(MSK)
        return current.date() + timedelta(days=1)

    @property
    def final_date(self) -> date:
        return self.state.challenge_start_date + timedelta(days=30)

    @staticmethod
    def _build_keyboard() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            [
                [BTN_STATUS, BTN_TODAY],
                [BTN_START, BTN_STOP, BTN_RESTART],
                [BTN_HELP],
            ],
            resize_keyboard=True,
        )

    def _load_or_create_state(self) -> BotState:
        if self.config.state_path.exists():
            try:
                raw = json.loads(self.config.state_path.read_text(encoding="utf-8"))
                state = BotState(
                    challenge_start_date=_parse_iso_date(raw["challenge_start_date"], "state.challenge_start_date"),
                    challenge_active=bool(raw.get("challenge_active", True)),
                    last_daily_sent_for=(
                        _parse_iso_date(raw["last_daily_sent_for"], "state.last_daily_sent_for")
                        if raw.get("last_daily_sent_for")
                        else None
                    ),
                    final_sent_for=(
                        _parse_iso_date(raw["final_sent_for"], "state.final_sent_for")
                        if raw.get("final_sent_for")
                        else None
                    ),
                )
                logger.info("Loaded state from %s", self.config.state_path)
                return state
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                raise RuntimeError(
                    f"Invalid state file at {self.config.state_path}. Fix or remove the file."
                ) from exc

        configured_start = os.getenv("CHALLENGE_START_DATE", "").strip()
        if configured_start:
            challenge_start_date = _parse_iso_date(configured_start, "CHALLENGE_START_DATE")
        else:
            challenge_start_date = self._calculate_challenge_start_date()

        state = BotState(challenge_start_date=challenge_start_date)
        self._save_state(state)
        logger.info("Initialized state in %s", self.config.state_path)
        return state

    def _save_state(self, state: BotState) -> None:
        self.config.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "challenge_start_date": state.challenge_start_date.isoformat(),
            "challenge_active": state.challenge_active,
            "last_daily_sent_for": state.last_daily_sent_for.isoformat() if state.last_daily_sent_for else None,
            "final_sent_for": state.final_sent_for.isoformat() if state.final_sent_for else None,
        }
        self.config.state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _persist_state(self) -> None:
        self._save_state(self.state)

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
        return (target_date - self.state.challenge_start_date).days + 1

    def set_challenge_day(self, day_number: int, *, reference_date: Optional[date] = None) -> None:
        if day_number < 1 or day_number > 30:
            raise ValueError("Day number must be between 1 and 30")
        current_date = reference_date if reference_date else self._current_msk_datetime().date()
        self.state.challenge_start_date = current_date - timedelta(days=day_number - 1)
        self.state.last_daily_sent_for = None
        self.state.final_sent_for = None
        self._persist_state()

    def start_challenge(self) -> None:
        self.state.challenge_active = True
        self._persist_state()

    def stop_challenge(self) -> None:
        self.state.challenge_active = False
        self._persist_state()

    def restart_challenge(self, *, reference_date: Optional[date] = None) -> None:
        current_date = reference_date if reference_date else self._current_msk_datetime().date()
        self.state.challenge_start_date = current_date
        self.state.challenge_active = True
        self.state.last_daily_sent_for = None
        self.state.final_sent_for = None
        self._persist_state()

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

    def _build_status_message(self) -> str:
        now = self._current_msk_datetime()
        day_number = self._day_number_for_date(now.date())
        state_text = "запущен" if self.state.challenge_active else "остановлен"
        return (
            f"Статус: {state_text}.\n"
            f"Текущий день: {day_number}.\n"
            f"Дата старта: {self.state.challenge_start_date.isoformat()}.\n"
            f"Дата финала: {self.final_date.isoformat()}.\n"
            f"Последняя дневная отправка: {self.state.last_daily_sent_for or '-'}\n"
            f"Финальная отправка: {self.state.final_sent_for or '-'}"
        )

    @staticmethod
    def _is_after_or_equal(now: datetime, target: time) -> bool:
        return (now.hour, now.minute) >= (target.hour, target.minute)

    @staticmethod
    def _is_in_challenge_range(day_number: int) -> bool:
        return 1 <= day_number <= 30

    def _is_admin(self, update: Update) -> bool:
        user = update.effective_user
        return bool(user and user.id in self.config.admin_ids)

    async def _deny_non_admin(self, update: Update) -> bool:
        if self._is_admin(update):
            return False
        if update.effective_message:
            await update.effective_message.reply_text("У вас нет доступа к управлению этим ботом.")
        return True

    async def send_daily_message_if_needed(self, *, allow_late: bool = False) -> None:
        async with self._send_lock:
            if not self.application:
                return

            if not self.state.challenge_active:
                logger.info("Challenge is stopped; daily message skipped")
                return

            now = self._current_msk_datetime()
            today = now.date()

            if self.state.last_daily_sent_for == today:
                logger.info("Daily message for %s already sent", today)
                return

            day_number = self._day_number_for_date(today)
            if not self._is_in_challenge_range(day_number):
                logger.info("No daily message scheduled for %s (day_number=%s)", today, day_number)
                return

            if allow_late and not self._is_after_or_equal(now, DAILY_TIME):
                logger.info("Daily catch-up not needed before %s", DAILY_TIME)
                return

            message = self._build_daily_message(day_number)
            await self.application.bot.send_message(chat_id=self.config.chat_id, text=message)
            self.state.last_daily_sent_for = today
            self._persist_state()
            logger.info("Sent daily message for day %s", day_number)

    async def send_final_message_if_needed(self, *, allow_late: bool = False) -> None:
        async with self._send_lock:
            if not self.application:
                return

            if not self.state.challenge_active:
                logger.info("Challenge is stopped; final message skipped")
                return

            now = self._current_msk_datetime()
            today = now.date()

            if self.state.final_sent_for == today:
                logger.info("Final message for %s already sent", today)
                return

            if today != self.final_date:
                logger.info("No final message scheduled for %s", today)
                return

            if allow_late and not self._is_after_or_equal(now, FINAL_TIME):
                logger.info("Final catch-up not needed before %s", FINAL_TIME)
                return

            await self.application.bot.send_message(chat_id=self.config.chat_id, text=self._build_final_message())
            self.state.final_sent_for = today
            self._persist_state()
            logger.info("Sent final message")

    async def cmd_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin(update):
            return

        await update.effective_message.reply_text(
            "Бот управления челленджем готов. Используйте /help или кнопки ниже.",
            reply_markup=self._build_keyboard(),
        )

    async def cmd_help(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin(update):
            return

        help_text = (
            "Доступные команды:\n"
            "/start — показать клавиатуру\n"
            "/help — помощь\n"
            "/status — состояние бота и челленджа\n"
            "/today — план на текущий день\n"
            "/setday N — установить текущий день (1..30)\n"
            "/start_challenge — запустить цикл\n"
            "/stop_challenge — остановить цикл\n"
            "/restart_challenge — перезапустить челлендж с дня 1 сегодня"
        )
        await update.effective_message.reply_text(help_text, reply_markup=self._build_keyboard())

    async def cmd_status(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin(update):
            return
        await update.effective_message.reply_text(self._build_status_message(), reply_markup=self._build_keyboard())

    async def cmd_today(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin(update):
            return

        today = self._current_msk_datetime().date()
        day_number = self._day_number_for_date(today)
        if self._is_in_challenge_range(day_number):
            text = self._build_daily_message(day_number)
        else:
            text = f"Сегодня вне диапазона челленджа (день {day_number})."
        await update.effective_message.reply_text(text, reply_markup=self._build_keyboard())

    async def cmd_setday(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin(update):
            return

        if not context.args:
            await update.effective_message.reply_text("Использование: /setday N, где N от 1 до 30")
            return

        try:
            day_number = int(context.args[0])
            self.set_challenge_day(day_number)
        except ValueError:
            await update.effective_message.reply_text("N должен быть целым числом от 1 до 30")
            return

        await update.effective_message.reply_text(
            f"Текущий день установлен на {day_number}. Новый старт: {self.state.challenge_start_date.isoformat()}"
        )

    async def cmd_start_challenge(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin(update):
            return

        self.start_challenge()
        await update.effective_message.reply_text("Челлендж запущен.")
        await self.send_daily_message_if_needed(allow_late=True)
        await self.send_final_message_if_needed(allow_late=True)

    async def cmd_stop_challenge(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin(update):
            return

        self.stop_challenge()
        await update.effective_message.reply_text("Челлендж остановлен.")

    async def cmd_restart_challenge(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin(update):
            return

        self.restart_challenge()
        await update.effective_message.reply_text(
            f"Челлендж перезапущен. День 1 установлен на {self.state.challenge_start_date.isoformat()}."
        )

    async def handle_buttons(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = (update.effective_message.text or "").strip()
        if text not in KNOWN_BUTTON_LABELS:
            return

        if await self._deny_non_admin(update):
            return

        if text == BTN_STATUS:
            await self.cmd_status(update, context)
        elif text == BTN_TODAY:
            await self.cmd_today(update, context)
        elif text == BTN_START:
            await self.cmd_start_challenge(update, context)
        elif text == BTN_STOP:
            await self.cmd_stop_challenge(update, context)
        elif text == BTN_RESTART:
            await self.cmd_restart_challenge(update, context)
        elif text == BTN_HELP:
            await self.cmd_help(update, context)

    def register_handlers(self, application: Application) -> None:
        application.add_handler(CommandHandler(START_COMMAND, self.cmd_start))
        application.add_handler(CommandHandler(HELP_COMMAND, self.cmd_help))
        application.add_handler(CommandHandler(STATUS_COMMAND, self.cmd_status))
        application.add_handler(CommandHandler(TODAY_COMMAND, self.cmd_today))
        application.add_handler(CommandHandler(SETDAY_COMMAND, self.cmd_setday))
        application.add_handler(CommandHandler(START_CHALLENGE_COMMAND, self.cmd_start_challenge))
        application.add_handler(CommandHandler(STOP_CHALLENGE_COMMAND, self.cmd_stop_challenge))
        application.add_handler(CommandHandler(RESTART_CHALLENGE_COMMAND, self.cmd_restart_challenge))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(BUTTON_TEXT_REGEX), self.handle_buttons)
        )

    def start_scheduler(self) -> None:
        self.scheduler.add_job(
            self.send_daily_message_if_needed,
            CronTrigger(hour=DAILY_TIME.hour, minute=DAILY_TIME.minute, timezone=MSK),
            id="daily_message",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=3600,
        )
        self.scheduler.add_job(
            self.send_final_message_if_needed,
            CronTrigger(hour=FINAL_TIME.hour, minute=FINAL_TIME.minute, timezone=MSK),
            id="final_message",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=3600,
        )
        self.scheduler.start()
        logger.info(
            "Scheduler started. challenge_start_date=%s final_date=%s active=%s",
            self.state.challenge_start_date,
            self.final_date,
            self.state.challenge_active,
        )

    async def run(self) -> None:
        self.application = ApplicationBuilder().token(self.config.bot_token).build()
        self.register_handlers(self.application)

        await self.application.initialize()
        await self.application.start()
        if not self.application.updater:
            raise RuntimeError("Updater is not available for polling")

        await self.application.updater.start_polling(drop_pending_updates=False)
        me = await self.application.bot.get_me()
        logger.info("Bot started: @%s", me.username)

        self.start_scheduler()

        await self.send_daily_message_if_needed(allow_late=True)
        await self.send_final_message_if_needed(allow_late=True)

        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
            if self.application.updater.running:
                await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()


async def main() -> None:
    config = load_config()
    app = PlankChallengeBot(config)
    await app.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
