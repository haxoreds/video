import os

# Telegram Bot Configuration
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'your_bot_token_here')

# File Management
TEMP_DIR = "temp_videos"
ARCHIVE_DIR = os.path.join(TEMP_DIR, "archives")
TELEGRAM_MAX_FILE_SIZE = 2000 * 1024 * 1024  # 2GB - максимальный размер файла для Telegram
SUPPORTED_VIDEO_FORMATS = ['.mp4', '.avi', '.mkv', '.mov']

# Scene Detection
MIN_SCENE_LENGTH = 2.5  # increased from 2.0 to reduce number of small scenes
THRESHOLD = 30.0  # increased from 27.0 to be less sensitive to minor changes