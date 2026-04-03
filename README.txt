Файлы для запуска бота:

1. main.py — основной файл бота.
2. requirements.txt — зависимости.
3. .env.example — пример переменных окружения.

Запуск локально:
1. Установить Python 3.9+.
2. Установить зависимости:
   pip install -r requirements.txt
3. Задать переменные окружения BOT_TOKEN и CHAT_ID.
4. Запустить:
   python main.py

Запуск на Railway:
1. Загрузить main.py и requirements.txt в репозиторий.
2. В Variables добавить BOT_TOKEN и CHAT_ID.
3. Railway сам запустит main.py, либо указать Start Command: python main.py
