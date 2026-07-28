# Systemd: бот + админка (Linux VPS)

Пути по умолчанию: `/home/petro2561/Visametric`, пользователь `root`.

## Подготовка на сервере

```bash
cd /home/petro2561/Visametric
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium   # если нужно
cp .env.example .env               # и заполнить BOT_TOKEN / ADMIN_*
```

## Установка unit-файлов

Важно: пробелы в команде `cp` обязательны.

```bash
cd /home/petro2561/Visametric
sudo cp deploy/systemd/visametric-bot.service \
        deploy/systemd/visametric-admin.service \
        deploy/systemd/visametric.target \
        /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now visametric-bot visametric-admin
# или: sudo systemctl enable --now visametric.target
```

## Диагностика

```bash
systemctl status visametric-bot visametric-admin --no-pager
journalctl -u visametric-bot -n 50 --no-pager
journalctl -u visametric-admin -n 50 --no-pager
```

Админка: http://SERVER_IP:8010/admin  
Для доступа снаружи в `.env`: `ADMIN_HOST=0.0.0.0`
