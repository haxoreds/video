import os

# Telegram Bot Configuration
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'your_bot_token_here')

# File Management
TEMP_DIR = "temp_videos"
ARCHIVE_DIR = os.path.join(TEMP_DIR, "archives")
TELEGRAM_MAX_FILE_SIZE = 2000 * 1024 * 1024  # 2GB - максимальный размер файла для Telegram
SUPPORTED_VIDEO_FORMATS = ['.mp4', '.avi', '.mkv', '.mov']

# Scene Detection
MIN_SCENE_LENGTH = 2.5  # минимальная длина сцены в секундах (увеличено для уменьшения количества сцен)
THRESHOLD = 35.0  # порог чувствительности для определения изменения сцены (увеличено для уменьшения количества сцен)