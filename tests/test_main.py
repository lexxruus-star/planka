import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from main import (
    BUTTON_TEXT_REGEX,
    DAY_MESSAGES,
    DAY_PLAN,
    DAILY_WEEKDAY_TIME,
    DAILY_WEEKEND_TIME,
    KNOWN_BUTTON_LABELS,
    AppConfig,
    BotState,
    DAILY_TIME,
    FINAL_TIME,
    MSK,
    PlankChallengeBot,
    _parse_admin_ids,
    load_config,
)


class MainTests(unittest.TestCase):
    def test_calculate_challenge_start_date_uses_tomorrow_msk(self):
        now = datetime(2026, 4, 3, 21, 0, tzinfo=MSK)
        self.assertEqual(PlankChallengeBot._calculate_challenge_start_date(now), date(2026, 4, 4))

    def test_day_number_math(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(bot_token="t", chat_id=1, state_path=Path(tmp) / "state.json", admin_ids={1})
            bot = PlankChallengeBot(config)
            bot.state = BotState(challenge_start_date=date(2026, 4, 4))

            self.assertEqual(bot._day_number_for_date(date(2026, 4, 4)), 1)
            self.assertEqual(bot._day_number_for_date(date(2026, 5, 3)), 30)
            self.assertEqual(bot._day_number_for_date(date(2026, 5, 4)), 31)

    def test_state_persists_and_reloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            config = AppConfig(bot_token="t", chat_id=1, state_path=state_path, admin_ids={1})
            bot = PlankChallengeBot(config)
            bot.state.last_daily_sent_for = date(2026, 4, 8)
            bot.state.challenge_active = False
            bot._save_state(bot.state)

            bot2 = PlankChallengeBot(config)
            self.assertEqual(bot2.state.last_daily_sent_for, date(2026, 4, 8))
            self.assertFalse(bot2.state.challenge_active)
            self.assertEqual(bot2.state.challenge_start_date, bot.state.challenge_start_date)

    def test_time_gate_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(bot_token="t", chat_id=1, state_path=Path(tmp) / "state.json", admin_ids={1})
            bot = PlankChallengeBot(config)
            early = datetime(2026, 4, 4, DAILY_TIME.hour - 1, 0, tzinfo=MSK)
            late = datetime(2026, 4, 4, FINAL_TIME.hour, FINAL_TIME.minute, tzinfo=MSK)
            self.assertFalse(bot._is_after_or_equal(early, DAILY_TIME))
            self.assertTrue(bot._is_after_or_equal(late, FINAL_TIME))

    def test_daily_time_by_weekday_in_msk(self):
        self.assertEqual(PlankChallengeBot._daily_time_for_date(date(2026, 4, 9)), DAILY_WEEKDAY_TIME)  # Thursday
        self.assertEqual(PlankChallengeBot._daily_time_for_date(date(2026, 4, 11)), DAILY_WEEKEND_TIME)  # Saturday

    def test_admin_ids_parse(self):
        self.assertEqual(_parse_admin_ids("1, 2,3"), {1, 2, 3})

    def test_load_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "BOT_TOKEN": "abc",
                    "CHAT_ID": "42",
                    "STATE_PATH": str(Path(tmp) / "s.json"),
                    "ADMIN_IDS": "1,2",
                },
                clear=True,
            ):
                cfg = load_config()
                self.assertEqual(cfg.bot_token, "abc")
                self.assertEqual(cfg.chat_id, 42)
                self.assertEqual(cfg.admin_ids, {1, 2})
                self.assertTrue(str(cfg.state_path).endswith("s.json"))

    def test_button_regex_matches_only_known_labels(self):
        for label in KNOWN_BUTTON_LABELS:
            self.assertIsNotNone(BUTTON_TEXT_REGEX.match(label))

        self.assertIsNone(BUTTON_TEXT_REGEX.match("Привет"))
        self.assertIsNone(BUTTON_TEXT_REGEX.match("/status"))

    def test_register_handlers_routes_button_text_before_manual_date_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(bot_token="t", chat_id=1, state_path=Path(tmp) / "state.json", admin_ids={1})
            bot = PlankChallengeBot(config)

            class DummyApplication:
                def __init__(self):
                    self.handlers = []

                def add_handler(self, handler):
                    self.handlers.append(handler)

            application = DummyApplication()
            bot.register_handlers(application)

            callback_order = [handler.callback.__name__ for handler in application.handlers if hasattr(handler, "callback")]
            self.assertIn("handle_buttons", callback_order)
            self.assertIn("handle_manual_start_date_input", callback_order)
            self.assertLess(
                callback_order.index("handle_buttons"),
                callback_order.index("handle_manual_start_date_input"),
            )

    def test_setday_and_restart_keep_state_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(bot_token="t", chat_id=1, state_path=Path(tmp) / "state.json", admin_ids={1})
            bot = PlankChallengeBot(config)
            bot.state.last_daily_sent_for = date(2026, 4, 10)
            bot.state.final_sent_for = date(2026, 5, 10)

            bot.set_challenge_day(10, reference_date=date(2026, 4, 20))
            self.assertEqual(bot.state.challenge_start_date, date(2026, 4, 11))
            self.assertIsNone(bot.state.last_daily_sent_for)
            self.assertIsNone(bot.state.final_sent_for)

            bot.restart_challenge(reference_date=date(2026, 4, 30))
            self.assertEqual(bot.state.challenge_start_date, date(2026, 4, 30))
            self.assertTrue(bot.state.challenge_active)

    def test_nearest_monday(self):
        self.assertEqual(PlankChallengeBot._nearest_monday_from(date(2026, 4, 3)), date(2026, 4, 6))
        self.assertEqual(PlankChallengeBot._nearest_monday_from(date(2026, 4, 6)), date(2026, 4, 6))

    def test_set_start_date_resets_send_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(bot_token="t", chat_id=1, state_path=Path(tmp) / "state.json", admin_ids={1})
            bot = PlankChallengeBot(config)
            bot.state.last_daily_sent_for = date(2026, 4, 10)
            bot.state.final_sent_for = date(2026, 5, 10)

            bot._set_start_date(date(2026, 4, 21))
            self.assertEqual(bot.state.challenge_start_date, date(2026, 4, 21))
            self.assertIsNone(bot.state.last_daily_sent_for)
            self.assertIsNone(bot.state.final_sent_for)

    def test_status_shows_waiting_before_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(bot_token="t", chat_id=1, state_path=Path(tmp) / "state.json", admin_ids={1})
            bot = PlankChallengeBot(config)
            bot.state.challenge_start_date = date(2026, 4, 10)

            with patch.object(bot, "_current_msk_datetime", return_value=datetime(2026, 4, 3, 8, 0, tzinfo=MSK)):
                status = bot._build_status_message()

            self.assertIn("ещё не начался", status)

    def test_day_plan_matches_agreed_schedule(self):
        expected = {
            1: ("stand", "20 сек"),
            2: ("stand", "20 сек"),
            3: ("stand", "30 сек"),
            4: ("stand", "30 сек"),
            5: ("special", "40 сек"),
            6: ("rest", None),
            7: ("stand", "45 сек"),
            8: ("stand", "45 сек"),
            9: ("stand", "1 мин"),
            10: ("special", "1 мин"),
            11: ("stand", "1 мин"),
            12: ("stand", "1 мин 30 сек"),
            13: ("rest", None),
            14: ("stand", "1 мин 40 сек"),
            15: ("special", "1 мин 50 сек"),
            16: ("stand", "2 мин"),
            17: ("stand", "2 мин"),
            18: ("stand", "2 мин 30 сек"),
            19: ("rest", None),
            20: ("special", "2 мин 30 сек"),
            21: ("stand", "2 мин 30 сек"),
            22: ("stand", "3 мин"),
            23: ("stand", "3 мин"),
            24: ("stand", "3 мин 30 сек"),
            25: ("special", "3 мин 30 сек"),
            26: ("rest", None),
            27: ("stand", "4 мин"),
            28: ("stand", "4 мин"),
            29: ("stand", "4 мин 30 сек"),
            30: ("special", "5 мин"),
        }
        for day, (day_type, duration) in expected.items():
            self.assertEqual(DAY_PLAN[day]["type"], day_type)
            if duration is None:
                self.assertNotIn("time", DAY_PLAN[day])
            else:
                self.assertEqual(DAY_PLAN[day]["time"], duration)

    def test_soft_messages_are_set_for_days_5_to_30(self):
        self.assertEqual(sorted(DAY_MESSAGES.keys()), list(range(5, 31)))
        self.assertEqual(
            DAY_MESSAGES[6],
            "Сегодня отдых. Это тоже часть плана.\n"
            "А вы знали, что планка — это упражнение, где мышцы работают почти без движения?\n"
            "Снаружи всё выглядит спокойно, а внутри корпус уже активно включается в работу.",
        )
        self.assertEqual(
            DAY_MESSAGES[13],
            "Сегодня отдых — можно спокойно выдохнуть.\n"
            "А вы знали, что мировой рекорд по удержанию планки на локтях среди мужчин составляет 9 часов 38 минут 47 секунд?\n"
            "Этот результат установил Йозеф Шалек из Чехии.",
        )
        self.assertIn("Сегодня день со спецзаданием.", DAY_MESSAGES[10])
        self.assertIn("Сегодня к основной норме добавляется спецзадание.", DAY_MESSAGES[30])

    def test_daily_message_builder_uses_new_texts_and_keeps_days_1_to_4(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig(bot_token="t", chat_id=1, state_path=Path(tmp) / "state.json", admin_ids={1})
            bot = PlankChallengeBot(config)
            self.assertEqual(
                bot._build_daily_message(5),
                "Доброе утро. Сегодня продолжаем.\nДень 5.\nСегодня стоим 40 сек.\nСегодня, кроме основной нормы, есть спецзадание.",
            )
            self.assertIn("День 1.", bot._build_daily_message(1))


class MainAsyncTests(unittest.IsolatedAsyncioTestCase):
    def _create_bot(self):
        tmp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(tmp.cleanup)
        config = AppConfig(bot_token="t", chat_id=777, state_path=Path(tmp.name) / "state.json", admin_ids={42})
        bot = PlankChallengeBot(config)
        bot.application = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
        return bot

    async def test_start_today_after_8_sends_catchup(self):
        bot = self._create_bot()
        with patch.object(bot, "_current_msk_datetime", return_value=datetime(2026, 4, 3, 8, 30, tzinfo=MSK)):
            await bot._apply_start_date_change(date(2026, 4, 3))
        bot.application.bot.send_message.assert_awaited_once()
        self.assertEqual(bot.state.last_daily_sent_for, date(2026, 4, 3))

    async def test_start_weekend_before_9_does_not_send_catchup(self):
        bot = self._create_bot()
        with patch.object(bot, "_current_msk_datetime", return_value=datetime(2026, 4, 11, 8, 30, tzinfo=MSK)):
            await bot._apply_start_date_change(date(2026, 4, 11))
        bot.application.bot.send_message.assert_not_called()
        self.assertIsNone(bot.state.last_daily_sent_for)

    async def test_start_weekend_after_9_sends_catchup(self):
        bot = self._create_bot()
        with patch.object(bot, "_current_msk_datetime", return_value=datetime(2026, 4, 11, 9, 10, tzinfo=MSK)):
            await bot._apply_start_date_change(date(2026, 4, 11))
        bot.application.bot.send_message.assert_awaited_once()
        self.assertEqual(bot.state.last_daily_sent_for, date(2026, 4, 11))

    async def test_manual_start_date_input_updates_state(self):
        bot = self._create_bot()
        context = SimpleNamespace(user_data={"awaiting_start_date_input": True})
        reply_text = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(type="private"),
            effective_message=SimpleNamespace(text="2026-04-11", reply_text=reply_text),
        )
        with patch.object(bot, "_current_msk_datetime", return_value=datetime(2026, 4, 3, 7, 30, tzinfo=MSK)):
            await bot.handle_manual_start_date_input(update, context)
        self.assertEqual(bot.state.challenge_start_date, date(2026, 4, 11))
        self.assertNotIn("awaiting_start_date_input", context.user_data)
        reply_text.assert_awaited_once()

    async def test_cancel_start_configuration(self):
        bot = self._create_bot()
        query = SimpleNamespace(
            data="start:cancel",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        context = SimpleNamespace(user_data={"awaiting_start_date_input": True})
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(type="private"),
            effective_message=None,
        )
        await bot.handle_start_date_callback(update, context)
        query.answer.assert_awaited_once()
        query.edit_message_text.assert_awaited_once()
        self.assertNotIn("awaiting_start_date_input", context.user_data)

    async def test_future_start_date_does_not_send_daily(self):
        bot = self._create_bot()
        with patch.object(bot, "_current_msk_datetime", return_value=datetime(2026, 4, 3, 8, 30, tzinfo=MSK)):
            await bot._apply_start_date_change(date(2026, 4, 10))
        bot.application.bot.send_message.assert_not_called()
        self.assertIsNone(bot.state.last_daily_sent_for)

    async def test_nearest_monday_callback_uses_same_day_when_monday(self):
        bot = self._create_bot()
        query = SimpleNamespace(
            data="start:monday",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        context = SimpleNamespace(user_data={})
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(type="private"),
            effective_message=None,
        )
        with patch.object(bot, "_current_msk_datetime", return_value=datetime(2026, 4, 6, 10, 0, tzinfo=MSK)):
            await bot.handle_start_date_callback(update, context)
        self.assertEqual(bot.state.challenge_start_date, date(2026, 4, 6))

    async def test_chatid_private_shows_chat_and_user_ids(self):
        bot = self._create_bot()
        reply_text = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(id=42001, type="private"),
            effective_message=SimpleNamespace(message_thread_id=None, reply_text=reply_text),
        )

        await bot.cmd_chatid(update, SimpleNamespace())
        sent_text = reply_text.await_args.args[0]
        self.assertIn("Chat ID: 42001", sent_text)
        self.assertIn("User ID: 42", sent_text)

    async def test_chatid_group_shows_group_id(self):
        bot = self._create_bot()
        reply_text = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(id=-10012345, type="supergroup"),
            effective_message=SimpleNamespace(message_thread_id=None, reply_text=reply_text),
        )

        await bot.cmd_chatid(update, SimpleNamespace())
        sent_text = reply_text.await_args.args[0]
        self.assertIn("Chat ID: -10012345", sent_text)
        self.assertNotIn("User ID:", sent_text)

    async def test_chatid_topic_shows_thread_id(self):
        bot = self._create_bot()
        reply_text = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(id=-100999, type="supergroup"),
            effective_message=SimpleNamespace(message_thread_id=77, reply_text=reply_text),
        )

        await bot.cmd_chatid(update, SimpleNamespace())
        sent_text = reply_text.await_args.args[0]
        self.assertIn("Chat ID: -100999", sent_text)
        self.assertIn("Message Thread ID: 77", sent_text)

    async def test_start_and_help_commands_work_for_admin_in_private(self):
        bot = self._create_bot()
        reply_text = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(type="private"),
            effective_message=SimpleNamespace(reply_text=reply_text),
        )

        await bot.cmd_start(update, SimpleNamespace())
        await bot.cmd_help(update, SimpleNamespace())
        self.assertEqual(reply_text.await_count, 2)

    async def test_status_and_today_commands_work_for_admin_in_private(self):
        bot = self._create_bot()
        reply_text = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(type="private"),
            effective_message=SimpleNamespace(reply_text=reply_text),
        )

        with patch.object(bot, "_current_msk_datetime", return_value=datetime(2026, 4, 3, 8, 30, tzinfo=MSK)):
            await bot.cmd_status(update, SimpleNamespace())
            await bot.cmd_today(update, SimpleNamespace())
        self.assertEqual(reply_text.await_count, 2)

    async def test_setday_start_stop_restart_commands_persist_and_reply(self):
        bot = self._create_bot()
        reply_text = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(type="private"),
            effective_message=SimpleNamespace(reply_text=reply_text),
        )

        await bot.cmd_setday(update, SimpleNamespace(args=["7"]))
        await bot.cmd_start_challenge(update, SimpleNamespace())
        await bot.cmd_stop_challenge(update, SimpleNamespace())
        await bot.cmd_restart_challenge(update, SimpleNamespace())
        self.assertGreaterEqual(reply_text.await_count, 4)

    async def test_configure_start_and_manual_input_flow(self):
        bot = self._create_bot()
        reply_text = AsyncMock()
        query = SimpleNamespace(
            data="start:manual",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        context = SimpleNamespace(user_data={})
        callback_update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(type="private"),
            effective_message=None,
        )

        await bot.handle_start_date_callback(callback_update, context)
        self.assertTrue(context.user_data.get("awaiting_start_date_input"))

        input_update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(type="private"),
            effective_message=SimpleNamespace(text="2026-04-12", reply_text=reply_text),
        )
        with patch.object(bot, "_current_msk_datetime", return_value=datetime(2026, 4, 3, 9, 0, tzinfo=MSK)):
            await bot.handle_manual_start_date_input(input_update, context)
        self.assertEqual(bot.state.challenge_start_date, date(2026, 4, 12))
        self.assertNotIn("awaiting_start_date_input", context.user_data)

    async def test_buttons_handler_processes_only_known_buttons(self):
        bot = self._create_bot()
        reply_text = AsyncMock()
        update_unknown = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(type="private"),
            effective_message=SimpleNamespace(text="Привет", reply_text=reply_text),
        )
        update_known = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(type="private"),
            effective_message=SimpleNamespace(text="Статус", reply_text=reply_text),
        )

        await bot.handle_buttons(update_unknown, SimpleNamespace())
        self.assertEqual(reply_text.await_count, 0)
        await bot.handle_buttons(update_known, SimpleNamespace())
        self.assertEqual(reply_text.await_count, 1)

    async def test_admin_only_restrictions_for_private_commands_and_chatid(self):
        bot = self._create_bot()
        denied_reply = AsyncMock()
        private_non_admin = SimpleNamespace(
            effective_user=SimpleNamespace(id=999),
            effective_chat=SimpleNamespace(type="private", id=100),
            effective_message=SimpleNamespace(reply_text=denied_reply, text="/status", message_thread_id=None),
        )
        group_admin = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(type="supergroup", id=-100),
            effective_message=SimpleNamespace(reply_text=denied_reply, text="/status", message_thread_id=None),
        )

        await bot.cmd_status(private_non_admin, SimpleNamespace())
        await bot.cmd_help(group_admin, SimpleNamespace())
        self.assertGreaterEqual(denied_reply.await_count, 1)

        chatid_non_admin = SimpleNamespace(
            effective_user=SimpleNamespace(id=999),
            effective_chat=SimpleNamespace(type="private", id=100),
            effective_message=SimpleNamespace(reply_text=denied_reply, message_thread_id=None),
        )
        await bot.cmd_chatid(chatid_non_admin, SimpleNamespace())
        self.assertGreaterEqual(denied_reply.await_count, 2)

    async def test_daily_and_final_delivery_with_scheduler_paths(self):
        bot = self._create_bot()
        bot.state.challenge_start_date = date(2026, 4, 3)

        with patch.object(bot, "_current_msk_datetime", return_value=datetime(2026, 4, 3, 8, 0, tzinfo=MSK)):
            await bot.send_daily_message_if_needed()
        self.assertEqual(bot.state.last_daily_sent_for, date(2026, 4, 3))

        bot.state.challenge_start_date = date(2026, 3, 4)  # final date 2026-04-03
        with patch.object(bot, "_current_msk_datetime", return_value=datetime(2026, 4, 3, 9, 0, tzinfo=MSK)):
            await bot.send_final_message_if_needed()
        self.assertEqual(bot.state.final_sent_for, date(2026, 4, 3))

    async def test_no_duplicate_daily_messages_between_scheduler_and_catchup(self):
        bot = self._create_bot()
        bot.state.challenge_start_date = date(2026, 4, 11)  # Saturday, day 1
        with patch.object(bot, "_current_msk_datetime", return_value=datetime(2026, 4, 11, 9, 0, tzinfo=MSK)):
            await bot.send_daily_message_if_needed()
        with patch.object(bot, "_current_msk_datetime", return_value=datetime(2026, 4, 11, 9, 5, tzinfo=MSK)):
            await bot.send_daily_message_if_needed(allow_late=True)
        bot.application.bot.send_message.assert_awaited_once()
        self.assertEqual(bot.state.last_daily_sent_for, date(2026, 4, 11))

    async def test_existing_state_not_reset_by_daily_schedule_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            original = {
                "challenge_start_date": "2026-04-06",
                "challenge_active": True,
                "last_daily_sent_for": "2026-04-09",
                "final_sent_for": None,
            }
            state_path.write_text(json.dumps(original), encoding="utf-8")
            config = AppConfig(bot_token="t", chat_id=777, state_path=state_path, admin_ids={42})
            bot = PlankChallengeBot(config)
            self.assertEqual(bot.state.challenge_start_date, date(2026, 4, 6))
            self.assertEqual(bot.state.last_daily_sent_for, date(2026, 4, 9))
            self.assertIsNone(bot.state.final_sent_for)


if __name__ == "__main__":
    unittest.main()
