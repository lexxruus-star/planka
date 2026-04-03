import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from main import (
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


if __name__ == "__main__":
    unittest.main()
