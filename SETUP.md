# Appodeal Pulse — Setup Guide

## Шаг 1: Создать Slack Bot

1. Перейди на https://api.slack.com/apps
2. Нажми **Create New App** → **From scratch**
3. Имя: `Appodeal Pulse Bot`, Workspace: `Appodeal`
4. В левом меню → **OAuth & Permissions**
5. Добавь Bot Token Scopes:
   - `channels:history` — читать сообщения в каналах
   - `channels:read` — список каналов
   - `users:read` — имена пользователей
6. Нажми **Install to Workspace** → **Allow**
7. Скопируй **Bot User OAuth Token** (начинается с `xoxb-...`)

## Шаг 2: Получить Anthropic API Key

1. Перейди на https://console.anthropic.com/settings/keys
2. Создай новый ключ (начинается с `sk-ant-...`)

## Шаг 3: Настроить переменные окружения

Создай файл `.env` в папке проекта:
```bash
cd ~/appodeal-pulse
cp .env.example .env
# Отредактируй .env — впиши токены
```

Для запуска с `.env` файлом:
```bash
export $(cat .env | xargs) && python3 server.py
```

## Шаг 4: Установить зависимости

```bash
cd ~/appodeal-pulse
pip3 install -r requirements.txt
```

## Шаг 5: Протестировать локально

```bash
# Запустить сервер
export $(cat .env | xargs) && python3 server.py

# В другом терминале — обновить контент
curl http://localhost:8080/api/refresh

# Открыть в браузере
open http://localhost:8080
```

## Шаг 6: Настроить ежедневный запуск (macOS)

```bash
# Скопировать launchd plist
cp ~/appodeal-pulse/com.appodeal.pulse.plist ~/Library/LaunchAgents/

# Загрузить (запуск каждый день в 8:00)
launchctl load ~/Library/LaunchAgents/com.appodeal.pulse.plist

# Проверить статус
launchctl list | grep pulse

# Выгрузить если нужно
launchctl unload ~/Library/LaunchAgents/com.appodeal.pulse.plist
```

## Шаг 7: Деплой на Render

1. Создай GitHub репо и запуши код:
```bash
cd ~/appodeal-pulse
git init
git add -A
git commit -m "Appodeal Pulse — wall newspaper"
gh repo create appodeal-pulse --private --push --source .
```

2. На https://dashboard.render.com:
   - New → Web Service
   - Connect GitHub repo
   - Runtime: Python
   - Build: `pip install -r requirements.txt`
   - Start: `python server.py`
   - Add env vars: `SLACK_BOT_TOKEN`, `ANTHROPIC_API_KEY`

3. URL будет типа: `https://appodeal-pulse.onrender.com`

## Шаг 8: Настроить ТВ

На любом ТВ с браузером:
```bash
# Chrome kiosk mode (fullscreen, no UI)
google-chrome --kiosk https://appodeal-pulse.onrender.com
```

## API Endpoints

- `GET /` — Слайдшоу (основная страница)
- `GET /api/refresh` — Пересобрать контент из Slack
- `GET /api/status` — Статус (сколько слайдов, когда собрано)
- `GET /api/health` — Проверка что сервер жив
