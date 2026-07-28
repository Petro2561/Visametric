# Systemd: бот + админка

Файлы в этой папке рассчитаны на Linux. На macOS systemd нет — там запускайте вручную или через launchd.

## Установка

Подправьте в `.service` при необходимости:
- `User` / `Group`
- `WorkingDirectory`
- путь к `.venv/bin/python`
- `PLAYWRIGHT_BROWSERS_PATH` (на Linux обычно `~/.cache/ms-playwright`)

```bash
sudo cp deploy/systemd/visametric-bot.service /etc/systemd/system/
sudo cp deploy/systemd/visametric-admin.service /etc/systemd/system/
sudo cp deploy/systemd/visametric.target /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now visametric.target
```

Или по отдельности:

```bash
sudo systemctl enable --now visametric-bot
sudo systemctl enable --now visametric-admin
```

## Управление

```bash
sudo systemctl status visametric-bot visametric-admin
sudo systemctl restart visametric-bot
sudo systemctl restart visametric-admin
journalctl -u visametric-bot -f
journalctl -u visametric-admin -f
```

Админка: http://127.0.0.1:8000/admin (хост/порт из `.env`: `ADMIN_HOST`, `ADMIN_PORT`).
