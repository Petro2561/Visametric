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
- `/start` — регистрация и выбор города
- `/city` — Москва / Санкт-Петербург / Екатеринбург / Новосибирск
- `/select_dates` — крайняя дата (уведомление, если слот раньше)
- `/my_dates` — город и даты
- `/slots` — проверить свободные слоты сейчас

## Админка (SQLAdmin)

Общая БД с ботом: `data/users.sqlite`. Логин/пароль в `.env`:

- `ADMIN_LOGIN` / `ADMIN_PASSWORD` / `ADMIN_SECRET`
- `ADMIN_HOST` / `ADMIN_PORT` (по умолчанию `127.0.0.1:8010`)

```bash
python -m admin
```

Откройте http://127.0.0.1:8010/admin — пользователи и даты поиска.
