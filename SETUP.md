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

## Шаг 9: Настроить Google Slides экспорт (опционально)

Каждый день PPTX автоматически загружается на Google Drive и конвертируется в Google Slides.

### 9.1 Создать Google Cloud проект
1. Перейди на https://console.cloud.google.com
2. Создай новый проект (напр. `appodeal-pulse`)
3. В поиске набери **Google Drive API** → **Enable**

### 9.2 Создать Service Account
1. IAM & Admin → **Service Accounts** → **Create Service Account**
2. Имя: `pulse-bot`, Role: не нужна
3. Нажми на созданный аккаунт → **Keys** → **Add Key** → **Create new key** → **JSON**
4. Скачается файл `appodeal-pulse-xxxxx.json` — это credentials

### 9.3 Настроить Google Drive папку
1. Создай папку в Google Drive (напр. `Pulse Archive`)
2. Открой папку → скопируй **Folder ID** из URL: `https://drive.google.com/drive/folders/FOLDER_ID_HERE`
3. Нажми **Share** на папке → добавь email Service Account (из JSON файла, поле `client_email`) → дай права **Editor**

### 9.4 Добавить secrets в GitHub
1. Перейди в Settings → Secrets → Actions в репо
2. Добавь:
   - `GOOGLE_SERVICE_ACCOUNT_JSON` — вставь **полное содержимое** JSON файла
   - `GOOGLE_DRIVE_FOLDER_ID` — ID папки из шага 9.3

### 9.5 Для локального запуска
```bash
# Добавь в .env:
GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here
```

После настройки каждый день в папке будет появляться новая Google Slides презентация `Pulse YYYY-MM-DD`.

## API Endpoints

- `GET /` — Слайдшоу (основная страница)
- `GET /api/refresh` — Пересобрать контент из Slack
- `GET /api/status` — Статус (сколько слайдов, когда собрано)
- `GET /api/health` — Проверка что сервер жив
