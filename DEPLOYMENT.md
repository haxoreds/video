# Руководство по развертыванию Telegram Bot для Определения Сцен

## Системные требования

### Операционная система
- Linux (рекомендуется Ubuntu 20.04 или новее)
- Минимум 4GB RAM
- Минимум 10GB свободного места на диске

### Системные зависимости
- Python 3.11
- FFmpeg
- Git

## Python зависимости
```txt
python-telegram-bot==21.10     # Основной функционал бота
opencv-python-headless==4.11.0.86  # Обработка видео без GUI
ffmpeg-python==0.2.0           # Работа с FFmpeg
scenedetect==0.6.5.2          # Определение сцен
yt-dlp==2025.2.19             # Загрузка видео с YouTube
pytube==15.0.0                # Альтернативный загрузчик YouTube
```

## Переменные окружения
Создайте файл `.env` со следующими переменными:
```env
# Обязательные
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Настройки обработки видео
TEMP_DIR=temp_videos
MAX_VIDEO_SIZE=2000000000  # 2GB в байтах
SUPPORTED_VIDEO_FORMATS=['.mp4', '.avi', '.mkv', '.mov']

# Параметры определения сцен
MIN_SCENE_LENGTH=1.5     # Минимальная длина сцены в секундах
THRESHOLD=25.0          # Порог определения сцен
```

## Настройка сервера

### Установка системных зависимостей
```bash
# Обновление пакетов
sudo apt-get update

# Установка Python 3.11
sudo apt-get install -y python3.11 python3.11-dev python3.11-venv

# Установка FFmpeg
sudo apt-get install -y ffmpeg

# Установка зависимостей для OpenCV
sudo apt-get install -y libgl1-mesa-glx libglib2.0-0
```

### Настройка службы systemd
1. Создайте файл службы `/etc/systemd/system/scene-bot.service`:
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

## Установка и запуск

1. Клонируйте репозиторий:
```bash
git clone https://github.com/your-repo/video-scene-bot.git
cd video-scene-bot
```

2. Создайте виртуальное окружение:
```bash
python3.11 -m venv venv
source venv/bin/activate
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Создайте необходимые директории:
```bash
mkdir -p temp_videos/archives
chmod 755 temp_videos
```

5. Настройте и запустите службу:
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
pip install -r requirements.txt
sudo systemctl restart scene-bot
```

## Решение проблем

### Ошибка ImportError: libGL.so.1
```bash
sudo apt-get install -y libgl1-mesa-glx libglib2.0-0
```

### Ошибки с FFmpeg
```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
ffmpeg -version
```

### Проблемы с определением сцен
1. Проверьте параметры `MIN_SCENE_LENGTH` и `THRESHOLD` в `.env`
2. Убедитесь, что видео поддерживается и не повреждено
3. Проверьте наличие свободного места на диске
