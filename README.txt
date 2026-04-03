Файлы проекта:

1. main.py — основной файл бота (расписание + команды + кнопки + ACL админов).
2. requirements.txt — зависимости.
3. .env.example — пример переменных окружения.
4. bot_state.json — файл состояния (создаётся автоматически, хранить в volume).

Переменные окружения:
- BOT_TOKEN (обязательно)
- CHAT_ID (обязательно, integer)
- STATE_PATH (обязательно для прода: путь к JSON-файлу состояния)
- ADMIN_IDS (обязательно: список Telegram user id через запятую)
- CHALLENGE_START_DATE (опционально, YYYY-MM-DD; учитывается только при первом запуске, если state ещё нет)

Команды (только для ADMIN_IDS):
- /start
- /help
- /status
- /today
- /setday N
- /start_challenge
- /stop_challenge
- /restart_challenge

Кнопки (только для ADMIN_IDS):
- Статус
- Сегодня
- Запустить
- Остановить
- Перезапустить
- Помощь

Логика:
- Расписание MSK сохранено: дневное сообщение 08:00, финальное 09:00.
- /setday N выставляет текущий день челленджа вручную (1..30).
- /start_challenge включает цикл.
- /stop_challenge отключает цикл.
- /restart_challenge перезапускает челлендж с дня 1 (сегодня).
- В state сохраняются: дата старта, активность цикла, отметки отправок дневного/финального сообщений.
- После рестарта приложения бот продолжает работу из STATE_PATH без сброса прогресса.

Запуск локально:
1. Установить Python 3.9+.
2. Установить зависимости:
   pip install -r requirements.txt
3. Заполнить env (можно из .env.example).
4. Запустить:
   python main.py

Запуск на Railway:
1. Загрузить main.py, requirements.txt, README.txt в репозиторий.
2. Добавить Variables: BOT_TOKEN, CHAT_ID, ADMIN_IDS, STATE_PATH.
3. Подключить volume и направить STATE_PATH в volume (иначе прогресс потеряется при рестарте).
4. Start Command: python main.py
