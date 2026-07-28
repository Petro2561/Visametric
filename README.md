# Visametric RU — просмотр слотов + Telegram-бот

Проходит капчу, выбирает город/офис на шаге 1 и показывает ближайшие даты. Запись не создаётся.

## CLI

```bash
source .venv/bin/activate
python main.py
```

## Telegram-бот

В `.env`: `BOT_TOKEN=...`

```bash
python bot.py
```

Команды:
- `/start` — регистрация в БД
- `/select_dates` — добавить или удалить дату поиска
- `/my_dates` — список ваших дат
- `/slots` — проверить свободные слоты на сайте

## Админка (SQLAdmin)

Общая БД с ботом: `data/users.sqlite`. Логин/пароль в `.env`:

- `ADMIN_LOGIN` / `ADMIN_PASSWORD` / `ADMIN_SECRET`
- `ADMIN_HOST` / `ADMIN_PORT` (по умолчанию `127.0.0.1:8000`)

```bash
python -m admin
```

Откройте http://127.0.0.1:8000/admin — пользователи и даты поиска.
