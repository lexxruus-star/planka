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
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
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
for noisy_logger_name in ("httpx", "httpcore", "telegram", "telegram.ext"):
    logging.getLogger(noisy_logger_name).setLevel(logging.WARNING)

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
CHATID_COMMAND = "chatid"

BTN_STATUS = "Статус"
BTN_TODAY = "Сегодня"
BTN_START = "Запустить"
BTN_STOP = "Остановить"
BTN_RESTART = "Перезапустить"
BTN_CONFIGURE_START = "Настроить старт"
BTN_HELP = "Помощь"
KNOWN_BUTTON_LABELS = (BTN_STATUS, BTN_TODAY, BTN_START, BTN_STOP, BTN_RESTART, BTN_CONFIGURE_START, BTN_HELP)
BUTTON_TEXT_REGEX = re.compile(rf"^({'|'.join(re.escape(label) for label in KNOWN_BUTTON_LABELS)})$")

START_ACTION_MONDAY = "start:monday"
START_ACTION_TOMORROW = "start:tomorrow"
START_ACTION_TODAY = "start:today"
START_ACTION_MANUAL = "start:manual"
START_ACTION_CANCEL = "start:cancel"
START_DATE_INPUT_KEY = "awaiting_start_date_input"


STANDING_PHRASES = [
    "Ну что, снова стоим.",
    "Доброе утро. Пора немного пострадать.",
    "Сегодня без отмазок, поехали.",
    "Встаём, собираемся, держим.",
]

DAY_MESSAGES: Dict[int, str] = {
    5: "Доброе утро. Сегодня продолжаем.\nДень 5.\nСегодня стоим 40 сек.\nСегодня, кроме основной нормы, есть спецзадание.",
    6: "Сегодня отдых. Это тоже часть плана.\nА вы знали, что планка — это упражнение, где мышцы работают почти без движения?\nСнаружи всё выглядит спокойно, а внутри корпус уже активно включается в работу.",
    7: "Новый день — новая норма.\nДень 7.\nСегодня стоим 45 сек.",
    8: "Сегодня идём дальше по плану.\nДень 8.\nСегодня стоим 45 сек.",
    9: "Спокойно, уверенно, поехали.\nДень 9.\nСегодня стоим 1 мин.",
    10: "Доброе утро. Сегодня продолжаем.\nДень 10.\nСегодня стоим 1 мин.\nСегодня день со спецзаданием.",
    11: "Сегодня делаем свою норму.\nДень 11.\nСегодня стоим 1 мин.",
    12: "Новый день — новая норма.\nДень 12.\nСегодня стоим 1 мин 30 сек.",
    13: "Сегодня отдых — можно спокойно выдохнуть.\nА вы знали, что в планке работает не только пресс, а сразу много мышц корпуса?\nПоэтому она считается упражнением не на одну зону, а сразу на целую команду мышц.",
    14: "Сегодня идём дальше по плану.\nДень 14.\nСегодня стоим 1 мин 40 сек.",
    15: "Спокойно, уверенно, поехали.\nДень 15.\nСегодня стоим 1 мин 50 сек.\nСегодня к основной норме добавляется спецзадание.",
    16: "Доброе утро. Сегодня продолжаем.\nДень 16.\nСегодня стоим 2 мин.",
    17: "Сегодня делаем свою норму.\nДень 17.\nСегодня стоим 2 мин.",
    18: "Новый день — новая норма.\nДень 18.\nСегодня стоим 2 мин 30 сек.",
    19: "Сегодня отдых. Восстанавливаемся и набираемся сил.\nА вы знали, что у планки есть целое семейство вариантов?\nНа локтях, на прямых руках, боковая — упражнение одно, а способов выполнять его довольно много.",
    20: "Сегодня идём дальше по плану.\nДень 20.\nСегодня стоим 2 мин 30 сек.\nСегодня, кроме основной нормы, есть спецзадание.",
    21: "Спокойно, уверенно, поехали.\nДень 21.\nСегодня стоим 2 мин 30 сек.",
    22: "Доброе утро. Сегодня продолжаем.\nДень 22.\nСегодня стоим 3 мин.",
    23: "Сегодня делаем свою норму.\nДень 23.\nСегодня стоим 3 мин.",
    24: "Новый день — новая норма.\nДень 24.\nСегодня стоим 3 мин 30 сек.",
    25: "Сегодня идём дальше по плану.\nДень 25.\nСегодня стоим 3 мин 30 сек.\nСегодня день со спецзаданием.",
    26: "Сегодня отдых. Завтра продолжим.\nА вы знали, что главный смысл планки — не просто простоять нужное время, а научить корпус держаться стабильно?\nПоэтому здесь важны не только секунды, но и ощущение ровной, устойчивой позиции.",
    27: "Спокойно, уверенно, поехали.\nДень 27.\nСегодня стоим 4 мин.",
    28: "Доброе утро. Сегодня продолжаем.\nДень 28.\nСегодня стоим 4 мин.",
    29: "Сегодня делаем свою норму.\nДень 29.\nСегодня стоим 4 мин 30 сек.",
    30: "Новый день — новая норма.\nДень 30.\nСегодня стоим 5 мин.\nСегодня к основной норме добавляется спецзадание.",
}

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

STANDING_DAYS = [1, 2, 3, 4]


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
                [BTN_CONFIGURE_START],
                [BTN_HELP],
            ],
            resize_keyboard=True,
        )

    @staticmethod
    def _build_start_config_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Ближайший понедельник", callback_data=START_ACTION_MONDAY)],
                [InlineKeyboardButton("Завтра", callback_data=START_ACTION_TOMORROW)],
                [InlineKeyboardButton("Сегодня", callback_data=START_ACTION_TODAY)],
                [InlineKeyboardButton("Ввести дату", callback_data=START_ACTION_MANUAL)],
                [InlineKeyboardButton("Отмена", callback_data=START_ACTION_CANCEL)],
            ]
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
        if sorted(DAY_MESSAGES.keys()) != list(range(5, 31)):
            raise RuntimeError("DAY_MESSAGES must contain all days from 5 to 30")

        for day in STANDING_DAYS:
            if DAY_PLAN[day]["type"] != "stand":
                raise RuntimeError(f"Day {day} must be stand day")

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
        if day_number in DAY_MESSAGES:
            return DAY_MESSAGES[day_number]

        day_info = DAY_PLAN[day_number]
        day_type = day_info["type"]

        if day_type == "stand":
            phrase = self._standing_phrase_by_day[day_number]
            return f"{phrase}\nДень {day_number}.\nСегодня стоим {day_info['time']}."

        raise ValueError(f"Unknown day type: {day_type}")

    @staticmethod
    def _build_final_message() -> str:
        return "Всё, бобры, доплыли 🦫\nЧеллендж завершён.\nСпасибо всем за участие."

    def _build_status_message(self) -> str:
        now = self._current_msk_datetime()
        day_number = self._day_number_for_date(now.date())
        state_text = "запущен" if self.state.challenge_active else "остановлен"
        has_started = day_number >= 1
        progress_text = f"начался, текущий день: {day_number}" if has_started else "ещё не начался (ожидает старта)"
        return (
            f"Статус: {state_text}.\n"
            f"Челлендж: {progress_text}.\n"
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

    @staticmethod
    def _is_private_chat(update: Update) -> bool:
        chat = update.effective_chat
        return bool(chat and chat.type == "private")

    async def _deny_non_admin_or_non_private(self, update: Update) -> bool:
        if not self._is_private_chat(update):
            return True
        if self._is_admin(update):
            return False
        if update.effective_message:
            await update.effective_message.reply_text("У вас нет доступа к управлению этим ботом.")
        return True

    async def _deny_non_admin(self, update: Update) -> bool:
        if self._is_admin(update):
            return False
        if update.effective_message:
            await update.effective_message.reply_text("У вас нет доступа к управлению этим ботом.")
        return True

    @staticmethod
    def _nearest_monday_from(current_date: date) -> date:
        days_ahead = (0 - current_date.weekday()) % 7
        return current_date + timedelta(days=days_ahead)

    def _set_start_date(self, start_date: date) -> None:
        self.state.challenge_start_date = start_date
        self.state.last_daily_sent_for = None
        self.state.final_sent_for = None
        self._persist_state()

    async def _apply_start_date_change(self, start_date: date) -> None:
        self._set_start_date(start_date)
        await self.send_daily_message_if_needed(allow_late=True)
        await self.send_final_message_if_needed(allow_late=True)

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
        if await self._deny_non_admin_or_non_private(update):
            return

        await update.effective_message.reply_text(
            "Бот управления челленджем готов. Используйте /help или кнопки ниже.",
            reply_markup=self._build_keyboard(),
        )

    async def cmd_help(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin_or_non_private(update):
            return

        help_text = (
            "Доступные команды:\n"
            "/start — показать клавиатуру\n"
            "/help — помощь\n"
            "/status — состояние бота и челленджа\n"
            "/today — план на текущий день\n"
            "/setday N — установить текущий день (1..30)\n"
            "/configure_start — настроить дату дня 1\n"
            "/chatid — показать chat id (и thread id, если есть)\n"
            "/start_challenge — запустить цикл\n"
            "/stop_challenge — остановить цикл\n"
            "/restart_challenge — перезапустить челлендж с дня 1 сегодня"
        )
        await update.effective_message.reply_text(help_text, reply_markup=self._build_keyboard())

    async def cmd_status(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin_or_non_private(update):
            return
        await update.effective_message.reply_text(self._build_status_message(), reply_markup=self._build_keyboard())

    async def cmd_today(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin_or_non_private(update):
            return

        today = self._current_msk_datetime().date()
        day_number = self._day_number_for_date(today)
        if self._is_in_challenge_range(day_number):
            text = self._build_daily_message(day_number)
        else:
            text = f"Сегодня вне диапазона челленджа (день {day_number})."
        await update.effective_message.reply_text(text, reply_markup=self._build_keyboard())

    async def cmd_setday(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin_or_non_private(update):
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
        if await self._deny_non_admin_or_non_private(update):
            return

        self.start_challenge()
        await update.effective_message.reply_text("Челлендж запущен.")
        await self.send_daily_message_if_needed(allow_late=True)
        await self.send_final_message_if_needed(allow_late=True)

    async def cmd_stop_challenge(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin_or_non_private(update):
            return

        self.stop_challenge()
        await update.effective_message.reply_text("Челлендж остановлен.")

    async def cmd_restart_challenge(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin_or_non_private(update):
            return

        self.restart_challenge()
        await update.effective_message.reply_text(
            f"Челлендж перезапущен. День 1 установлен на {self.state.challenge_start_date.isoformat()}."
        )

    async def cmd_configure_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin_or_non_private(update):
            return

        context.user_data.pop(START_DATE_INPUT_KEY, None)
        await update.effective_message.reply_text(
            "Выберите дату для дня 1:",
            reply_markup=self._build_start_config_keyboard(),
        )

    async def handle_start_date_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return

        if await self._deny_non_admin_or_non_private(update):
            await query.answer()
            return

        now_date = self._current_msk_datetime().date()
        action = query.data
        context.user_data.pop(START_DATE_INPUT_KEY, None)

        if action == START_ACTION_CANCEL:
            await query.answer("Отменено")
            await query.edit_message_text("Настройка старта отменена.")
            return

        if action == START_ACTION_MANUAL:
            context.user_data[START_DATE_INPUT_KEY] = True
            await query.answer()
            await query.edit_message_text("Введите дату дня 1 в формате YYYY-MM-DD.")
            return

        if action == START_ACTION_MONDAY:
            start_date = self._nearest_monday_from(now_date)
        elif action == START_ACTION_TOMORROW:
            start_date = now_date + timedelta(days=1)
        elif action == START_ACTION_TODAY:
            start_date = now_date
        else:
            await query.answer()
            return

        await self._apply_start_date_change(start_date)
        await query.answer("Дата обновлена")
        await query.edit_message_text(
            f"День 1 теперь: {self.state.challenge_start_date.isoformat()}.\n"
            f"Финальный день: {self.final_date.isoformat()}."
        )

    async def handle_manual_start_date_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin_or_non_private(update):
            return

        if not context.user_data.get(START_DATE_INPUT_KEY):
            return

        raw_value = (update.effective_message.text or "").strip()
        if raw_value.lower() == "отмена":
            context.user_data.pop(START_DATE_INPUT_KEY, None)
            await update.effective_message.reply_text("Настройка старта отменена.", reply_markup=self._build_keyboard())
            return

        try:
            start_date = _parse_iso_date(raw_value, "manual start date")
        except RuntimeError:
            await update.effective_message.reply_text(
                "Неверный формат даты. Используйте YYYY-MM-DD или отправьте «Отмена»."
            )
            return

        context.user_data.pop(START_DATE_INPUT_KEY, None)
        await self._apply_start_date_change(start_date)
        await update.effective_message.reply_text(
            f"День 1 теперь: {self.state.challenge_start_date.isoformat()}.\n"
            f"Финальный день: {self.final_date.isoformat()}.",
            reply_markup=self._build_keyboard(),
        )

    async def cmd_chatid(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._deny_non_admin(update):
            return

        chat = update.effective_chat
        message = update.effective_message
        user = update.effective_user

        if not chat or not message:
            return

        lines = [f"Chat ID: {chat.id}"]
        if chat.type == "private" and user:
            lines.append(f"User ID: {user.id}")
        if message.message_thread_id is not None:
            lines.append(f"Message Thread ID: {message.message_thread_id}")

        await message.reply_text("\n".join(lines))

    async def handle_buttons(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = (update.effective_message.text or "").strip()
        if text not in KNOWN_BUTTON_LABELS:
            return

        if await self._deny_non_admin_or_non_private(update):
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
        elif text == BTN_CONFIGURE_START:
            await self.cmd_configure_start(update, context)
        elif text == BTN_HELP:
            await self.cmd_help(update, context)

    def register_handlers(self, application: Application) -> None:
        application.add_handler(CommandHandler(START_COMMAND, self.cmd_start))
        application.add_handler(CommandHandler(HELP_COMMAND, self.cmd_help))
        application.add_handler(CommandHandler(STATUS_COMMAND, self.cmd_status))
        application.add_handler(CommandHandler(TODAY_COMMAND, self.cmd_today))
        application.add_handler(CommandHandler(SETDAY_COMMAND, self.cmd_setday))
        application.add_handler(CommandHandler(CHATID_COMMAND, self.cmd_chatid))
        application.add_handler(CommandHandler(START_CHALLENGE_COMMAND, self.cmd_start_challenge))
        application.add_handler(CommandHandler(STOP_CHALLENGE_COMMAND, self.cmd_stop_challenge))
        application.add_handler(CommandHandler(RESTART_CHALLENGE_COMMAND, self.cmd_restart_challenge))
        application.add_handler(CommandHandler("configure_start", self.cmd_configure_start))
        application.add_handler(CallbackQueryHandler(self.handle_start_date_callback, pattern=r"^start:"))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(BUTTON_TEXT_REGEX), self.handle_buttons)
        )
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_manual_start_date_input))

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
