# Инструкция по установке и настройке Video Scene Bot

## Системные требования

### Минимальные требования к серверу
- CPU: 2 ядра
- RAM: 4 GB
- Диск: 10 GB свободного места
- ОС: Ubuntu 20.04 или новее

### Системные зависимости
```bash
# Обновление пакетов
sudo apt-get update

# Python 3.11 и зависимости
sudo apt-get install -y python3.11 python3.11-dev python3.11-venv

# FFmpeg
sudo apt-get install -y ffmpeg

# Зависимости для OpenCV
sudo apt-get install -y libgl1-mesa-glx libglib2.0-0
```

## Python зависимости
Все зависимости указаны в pyproject.toml:
- ffmpeg-python==0.2.0
- opencv-python-headless==4.11.0.86
- python-telegram-bot==21.10
- pytube==15.0.0
- scenedetect==0.6.5.2
- yt-dlp==2025.2.19

## Настройка проекта

1. Клонирование репозитория:
```bash
gh repo clone haxoreds/video
cd video-scene-bot
```

2. Создание виртуального окружения:
```bash
python3.11 -m venv venv
source venv/bin/activate
```

3. Установка зависимостей:
```bash
pip install .
```

4. Настройка переменных окружения:
```bash
cp .env.example .env
# Отредактируйте .env, добавив:
# - TELEGRAM_BOT_TOKEN
# - Настройте другие параметры при необходимости
```

5. Создание временной директории:
```bash
mkdir -p temp_videos/archives
chmod 755 temp_videos
```

## Настройка systemd сервиса

1. Создайте файл сервиса:
```bash
sudo nano /etc/systemd/system/scene-bot.service
```

2. Добавьте следующее содержимое:
```ini
[Unit]
Description=Telegram Scene Detection Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/your/bot
Environment=PYTHONPATH=/path/to/your/bot
EnvironmentFile=/path/to/your/bot/.env
ExecStart=/path/to/your/bot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

3. Активация и запуск сервиса:
```bash
sudo systemctl enable scene-bot
sudo systemctl start scene-bot
```

## Мониторинг и обслуживание

### Просмотр логов
```bash
sudo journalctl -u scene-bot -f
```

### Очистка временных файлов
Добавьте в crontab:
```bash
0 * * * * find /path/to/your/bot/temp_videos -type f -mtime +1 -delete
```

### Обновление бота
```bash
cd /path/to/your/bot
git pull
source venv/bin/activate
pip install .
sudo systemctl restart scene-bot
```

## Проверка работоспособности

1. Проверка статуса сервиса:
```bash
sudo systemctl status scene-bot
```

2. Проверка логов на наличие ошибок:
```bash
sudo journalctl -u scene-bot -n 50 --no-pager
```

3. Проверка доступа к временной директории:
```bash
ls -la /path/to/your/bot/temp_videos
```
