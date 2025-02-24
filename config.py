import os

# Telegram Bot Configuration
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'your_bot_token_here')

# File Management
TEMP_DIR = "temp_videos"
ARCHIVE_DIR = os.path.join(TEMP_DIR, "archives")
MAX_VIDEO_SIZE = 2000 * 1024 * 1024  # 2GB - увеличен для поддержки видео высокого качества
SUPPORTED_VIDEO_FORMATS = ['.mp4', '.avi', '.mkv', '.mov']

# Scene Detection
MIN_SCENE_LENGTH = 2.0  # minimum scene length in seconds
THRESHOLD = 27.0  # threshold for scene detection (adjusted for better detection)

# YouTube Download
MAX_RESOLUTION = "720p"