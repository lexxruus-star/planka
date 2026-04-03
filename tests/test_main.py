import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from main import (
    BUTTON_TEXT_REGEX,
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


if __name__ == "__main__":
    unittest.main()
