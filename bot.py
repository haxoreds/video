import os
import asyncio
import logging
from typing import List
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import BOT_TOKEN, TEMP_DIR, ARCHIVE_DIR, TELEGRAM_MAX_FILE_SIZE
from download_manager import DownloadManager
from video_processor import VideoProcessor
from utils import create_temp_dir, cleanup_temp_files, split_list
import httpx

# Configure logging to show debug level messages and format
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)

# Create loggers for main components
logger = logging.getLogger(__name__)
video_processor_logger = logging.getLogger('video_processor')
video_processor_logger.setLevel(logging.DEBUG)

SUPPORTED_VIDEO_FORMATS = ('.mp4', '.avi', '.mkv', '.mov')

def ensure_directories():
    """Create necessary directories if they don't exist."""
    os.makedirs(TEMP_DIR, mode=0o755, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, mode=0o755, exist_ok=True)
    logger.info(f"Created temporary directories: {TEMP_DIR}, {ARCHIVE_DIR}")

def format_progress_bar(progress: int, width: int = 20) -> str:
    """Create a Unicode progress bar."""
    filled = int(width * progress / 100)
    bar = '█' * filled + '░' * (width - filled)
    return f"[{bar}] {progress}%"

class SceneDetectionBot:
    def __init__(self):
        # Configure longer timeouts for large file uploads
        self.application = (
            Application.builder()
            .token(BOT_TOKEN)
            .connect_timeout(60.0)  # 60 seconds for establishing connection
            .read_timeout(1800.0)   # 30 minutes for reading response
            .write_timeout(1800.0)  # 30 minutes for sending data
            .pool_timeout(1800.0)   # 30 minutes for connection pool
            .build()
        )
        ensure_directories()
        self._cleanup_on_start()  # Clean up on start
        self._setup_handlers()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        try:
            # Clean up temporary directories
            logger.info("Cleaning up temporary directories on /start command...")
            cleanup_temp_files(TEMP_DIR)
            cleanup_temp_files(ARCHIVE_DIR)
            logger.info("Temporary directories cleaned successfully")
        except Exception as e:
            logger.error(f"Error cleaning temporary directories: {str(e)}")

        welcome_text = (
            "👋 Привет! Я бот для определения и разделения сцен в видео!\n\n"
            "Я могу помочь разделить видео на отдельные сцены. Вы можете:\n"
            "1. Отправить мне ссылку на YouTube\n"
            "2. Загрузить видеофайл напрямую\n\n"
            "Используйте /help для получения дополнительной информации."
        )
        await update.message.reply_text(welcome_text)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        help_text = (
            "🎥 Как использовать этого бота:\n\n"
            "1. Для видео с YouTube:\n"
            "   - Просто вставьте ссылку на YouTube\n"
            "   - Выберите способ получения: в Telegram или архивом\n\n"
            "2. Для ваших видео:\n"
            "   - Загрузите видеофайл напрямую\n"
            "   - Поддерживаемые форматы: MP4, AVI, MKV, MOV\n"
            "   - Максимальный размер файла: 50МБ\n\n"
            "После обработки вы сможете:\n"
            "✅ Получить сцены отдельными видео в Telegram\n"
            "✅ Скачать все сцены одним архивом\n\n"
            "Я обработаю видео и отправлю вам сцены выбранным способом!"
        )
        await update.message.reply_text(help_text)

    async def button_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button clicks."""
        query = update.callback_query
        await query.answer()  # Acknowledge the button click

        # Get data from callback_data
        data = query.data.split('|')
        action = data[0]
        temp_dir = data[1]

        if action == "telegram":
            # Process and send scenes via Telegram
            await self.send_scenes_telegram(query.message, temp_dir)
        elif action == "archive":
            # Create and send RAR archive
            await self.send_scenes_archive(query.message, temp_dir)

    async def handle_youtube_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle YouTube link messages."""
        message = update.message
        text = message.text.strip()

        logger.debug(f"Processing potential YouTube link: {text}")

        youtube_patterns = [
            'youtube.com/watch?v=',
            'youtu.be/',
            'm.youtube.com/watch?v=',
            'youtube.com/v/',
            'youtube.com/embed/'
        ]

        if not any(pattern in text for pattern in youtube_patterns):
            logger.debug("Message is not a YouTube link")
            await message.reply_text("❌ Пожалуйста, отправьте корректную ссылку на YouTube видео.\nПример: https://youtube.com/watch?v=...")
            return

        status_message = await message.reply_text("⏳ Загрузка видео с YouTube...")

        # Clean up temp directories before starting
        try:
            logger.info("Cleaning up temporary directories before YouTube download...")
            cleanup_temp_files(TEMP_DIR)
            cleanup_temp_files(ARCHIVE_DIR)
            logger.info("Temporary directories cleaned successfully")
        except Exception as e:
            logger.error(f"Error cleaning temporary directories: {str(e)}")

        temp_dir = create_temp_dir()
        logger.info(f"Created temporary directory for YouTube download: {temp_dir}")

        try:
            success, result = await DownloadManager.download_from_youtube(text, temp_dir, context.bot)

            if not success:
                error_msg = result
                logger.error(f"YouTube download failed: {error_msg}")
                cleanup_temp_files(temp_dir)
                await status_message.edit_text(f"❌ {error_msg}")
                return

            logger.info(f"Successfully processed YouTube video: {result}")
            await self.process_video_and_show_options(result, status_message, temp_dir)

        except Exception as e:
            logger.exception("Error processing YouTube link")
            error_msg = str(e)
            await status_message.edit_text(f"❌ Произошла ошибка: {error_msg}")
            cleanup_temp_files(temp_dir)

    async def handle_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle video file uploads."""
        message = update.message
        logger.info("Получено видео сообщение")

        if not (message.video or message.document):
            logger.warning("Message contains neither video nor document")
            return

        # Check file format for documents
        if message.document:
            file_name = message.document.file_name.lower()
            if not any(file_name.endswith(ext) for ext in SUPPORTED_VIDEO_FORMATS):
                await message.reply_text(
                    f"❌ Неподдерживаемый формат файла. Поддерживаемые форматы: {', '.join(SUPPORTED_VIDEO_FORMATS)}"
                )
                return

        # Get file info and size
        if message.video:
            file_id = message.video.file_id
            file_size = message.video.file_size
            duration = message.video.duration if hasattr(message.video, 'duration') else None
        else:
            file_id = message.document.file_id
            file_size = message.document.file_size
            duration = None

        logger.info(f"Processing video: size={file_size/(1024*1024):.1f}MB, duration={duration}s if duration else 'unknown'")

        # Show initial message
        status_message = await message.reply_text(
            "⏳ Начинаем обработку видео...\n\n"
            f"📊 Размер файла: {file_size/(1024*1024):.1f}MB\n"
            "Пожалуйста, подождите..."
        )

        temp_dir = create_temp_dir()
        logger.info(f"Created temporary directory for video: {temp_dir}")

        try:
            await self.process_video_and_show_options(file_id, status_message, temp_dir)

        except Exception as e:
            logger.exception("Error processing video file")
            error_msg = str(e)
            if "too big" in error_msg.lower():
                await status_message.edit_text(
                    "❌ Видео слишком большое для обработки.\n"
                    "Попробуйте видео меньшего размера или длительности."
                )
            else:
                await status_message.edit_text(
                    "❌ Произошла ошибка при обработке видео.\n"
                    "Пожалуйста, убедитесь что:\n"
                    "1. Видео не повреждено\n"
                    "2. Формат видео поддерживается\n"
                    f"\nДетали ошибки: {error_msg}"
                )
            cleanup_temp_files(temp_dir)

    async def process_video_and_show_options(self, video_path: str, status_message, temp_dir: str):
        """Process video and show delivery options."""
        try:
            logger.info(f"Starting video processing for: {video_path}")

            await status_message.edit_text("🎬 Загрузка и обработка видео...\n" + format_progress_bar(0))

            try:
                async def progress_callback(progress: int, stage: str = ""):
                    progress_text = (
                        f"🎬 {stage}\n"
                        f"{format_progress_bar(progress)}\n\n"
                        "⏳ Пожалуйста, подождите, процесс может занять несколько минут..."
                    )
                    return await status_message.edit_text(progress_text)

                # Add timeout for video processing
                async with asyncio.timeout(600):  # 10 minutes
                    success, scenes = await VideoProcessor.process_telegram_stream(
                        video_path,  # This is actually file_id
                        temp_dir,
                        self.application.bot,
                        progress_callback
                    )

                    if not success:
                        logger.error(f"Video processing failed: {scenes[0]}")
                        await status_message.edit_text(
                            f"❌ {scenes[0]}\n\n"
                            "📝 Рекомендации:\n"
                            "1. Убедитесь, что видео не повреждено\n"
                            "2. Попробуйте загрузить видео заново\n"
                            "3. Проверьте формат видео (поддерживаются MP4, AVI, MKV, MOV)"
                        )
                        cleanup_temp_files(temp_dir)
                        return

                    logger.info(f"Successfully processed video: {scenes[0]}")

                    # Create inline keyboard with options
                    keyboard = [
                        [
                            InlineKeyboardButton("📤 Получить в Telegram", callback_data=f"telegram|{temp_dir}"),
                            InlineKeyboardButton("📦 Скачать архивом", callback_data=f"archive|{temp_dir}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await status_message.edit_text(
                        "✅ Видео успешно загружено!\n"
                        "Выберите способ получения:",
                        reply_markup=reply_markup
                    )

            except asyncio.TimeoutError:
                logger.error("Video processing timed out")
                await status_message.edit_text(
                    "❌ Превышено время обработки видео. Пожалуйста, попробуйте видео меньшей длительности."
                )
                cleanup_temp_files(temp_dir)
                return

        except Exception as e:
            logger.exception("Error in video processing")
            await status_message.edit_text(f"❌ Произошла ошибка при обработке видео: {str(e)}")
            cleanup_temp_files(temp_dir)

    async def send_scenes_telegram(self, message, temp_dir: str):
        """Send scenes via Telegram."""
        try:
            # Get all scene files and sort them numerically
            scenes = [f for f in os.listdir(temp_dir) if f.endswith('.mp4')]
            scenes.sort(key=lambda x: int(x.split('-')[1].split('.')[0]))
            scene_paths = [os.path.join(temp_dir, scene) for scene in scenes]

            logger.info(f"Отправка сцен в порядке: {', '.join(scenes)}")

            if len(scenes) == 0:
                logger.error("No scenes found for sending")
                await message.edit_text("❌ Не удалось разделить видео на сцены. Попробуйте ещё раз.")
                return

            await message.edit_text(f"📤 Отправка {len(scenes)} сцен... 0%")

            # Process scenes sequentially
            total_scenes = len(scenes)
            scenes_sent = 0

            # Send scenes one by one
            for scene_path in scene_paths:
                try:
                    # For large scenes, check size first
                    if os.path.exists(scene_path):
                        scene_size = os.path.getsize(scene_path)
                        if scene_size > 50 * 1024 * 1024:  # > 50MB
                            logger.info(f"Large scene detected ({scene_size/(1024*1024):.1f}MB), uploading first")
                            success, result = await DownloadManager.upload_to_telegram(scene_path, self.application.bot)
                            if success:
                                logger.info("Successfully uploaded large scene")
                                await self.application.bot.send_video(
                                    chat_id=message.chat_id,
                                    video=result,
                                    caption=f"Сцена {scenes_sent + 1}",
                                    supports_streaming=True
                                )
                            else:
                                raise Exception(f"Failed to upload scene: {result}")
                        else:
                            # For smaller scenes, send directly
                            logger.info(f"Sending scene directly ({scene_size/(1024*1024):.1f}MB)")
                            with open(scene_path, 'rb') as video:
                                await self.application.bot.send_video(
                                    chat_id=message.chat_id,
                                    video=video,
                                    caption=f"Сцена {scenes_sent + 1}",
                                    supports_streaming=True
                                )
                                logger.info("Scene sent successfully")

                    scenes_sent += 1
                    progress = int(scenes_sent * 100 / total_scenes)
                    if progress % 10 == 0:  # Update progress every 10%
                        await message.edit_text(f"📤 Отправка сцен... {progress}%")

                except Exception as e:
                    logger.error(f"Ошибка при отправке сцены {scene_path}: {str(e)}")
                    await message.reply_text(f"❌ Не удалось отправить сцену {os.path.basename(scene_path)}: {str(e)}")

            await message.edit_text("✅ Все сцены успешно отправлены!")
        except Exception as e:
            await message.edit_text(f"❌ Произошла ошибка при отправке сцен: {str(e)}")
        finally:
            # Cleanup all temporary files
            cleanup_temp_files(temp_dir)

    async def send_scenes_archive(self, message, temp_dir: str):
        """Create and send zip archive with scenes."""
        try:
            # Get all scene files
            scenes = [f for f in os.listdir(temp_dir) if f.endswith('.mp4')]
            if not scenes:
                logger.warning("No scenes found for archiving")
                await message.edit_text("❌ Не найдены сцены для архивации")
                return

            await message.edit_text("📦 Подготовка к созданию архива...")

            # Create archive name and path
            archive_name = f"scenes_{len(scenes)}.zip"
            archive_path = os.path.join(ARCHIVE_DIR, archive_name)

            # Calculate total size of scenes
            total_size = sum(os.path.getsize(os.path.join(temp_dir, scene)) for scene in scenes)
            logger.info(f"Total size of scenes to archive: {total_size/(1024*1024):.1f}MB")

            # Create archive with fast compression
            scene_paths = ' '.join([os.path.abspath(os.path.join(temp_dir, scene)) for scene in scenes])
            zip_command = f"zip -1 -j '{archive_path}' {scene_paths}"

            logger.info(f"Running zip command: {zip_command}")
            await message.edit_text("📦 Создание архива...\nЭто может занять несколько минут.")

            process = await asyncio.create_subprocess_shell(
                zip_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                # Wait for the process with a timeout
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)

                if process.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    logger.error(f"zip process failed: {error_msg}")
                    await message.edit_text(
                        "❌ Ошибка при создании архива.\n"
                        "Попробуйте использовать опцию отправки сцен по отдельности."
                    )
                    return

                if not os.path.exists(archive_path):
                    logger.error("Archive not found after creation")
                    await message.edit_text("❌ Не удалось создать архив")
                    return

                # Get archive size
                archive_size = os.path.getsize(archive_path)
                if archive_size > TELEGRAM_MAX_FILE_SIZE:
                    await message.edit_text(
                        f"❌ Размер архива ({archive_size/(1024*1024):.1f}MB) превышает лимит Telegram (2GB).\n"
                        "Пожалуйста, используйте опцию отправки сцен по отдельности."
                    )
                    return

                await message.edit_text("📤 Отправка архива...")

                # Send archive with large chunk size and timeouts
                with open(archive_path, 'rb') as archive:
                    sent_message = await message.reply_document(
                        document=archive,
                        filename=archive_name,
                        caption=f"📦 Архив со сценами - {len(scenes)} сцен",
                        read_timeout=3600,  # 1 hour
                        write_timeout=3600,  # 1 hour
                        connect_timeout=60,  # 1 minute
                        chunk_size=20 * 1024 * 1024  # 20MB chunks
                    )

                if sent_message:
                    await message.edit_text("✅ Архив успешно отправлен!")
                    try:
                        os.unlink(archive_path)
                    except Exception as e:
                        logger.error(f"Error cleaning up archive: {e}")
                else:
                    raise Exception("Failed to send archive")

            except asyncio.TimeoutError:
                logger.error("Archive operation timed out")
                await message.edit_text(
                    "❌ Превышено время операции с архивом.\n"
                    "Попробуйте использовать опцию отправки сцен по отдельности."
                )

        except Exception as e:
            logger.error(f"Error in send_scenes_archive: {str(e)}")
            await message.edit_text(
                "❌ Ошибка при работе с архивом.\n"
                "Попробуйте использовать опцию отправки сцен по отдельности."
            )
        finally:
            cleanup_temp_files(temp_dir)

    async def check_7zip_available(self):
        """Check if 7zip is available in the system."""
        try:
            process = await asyncio.create_subprocess_shell(
                "7z i",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            logger.info(f"7zip version check result: {stdout.decode() if stdout else ''}")
            return process.returncode == 0
        except Exception as e:
            logger.error(f"Error checking 7zip availability: {str(e)}")
            return False

    async def send_scene_chunk(self, chat_id: int, scene_paths: List[str]):
        """Send a chunk of scene videos."""
        for scene_path in scene_paths:
            try:
                with open(scene_path, 'rb') as video:
                    scene_number = int(os.path.basename(scene_path).split('-')[1].split('.')[0])
                    await self.application.bot.send_video(
                        chat_id=chat_id,
                        video=video,
                        caption=f"Сцена {scene_number}",
                        supports_streaming=True
                    )
            except Exception as e:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Не удалось отправить сцену {os.path.basename(scene_path)}: {str(e)}"
                )

    async def _update_archive_progress(self, message, archive_path):
        """Update archive creation progress message periodically."""
        try:
            while True:
                if os.path.exists(archive_path):
                    size = os.path.getsize(archive_path) / (1024 * 1024)  # Size in MB
                    await message.edit_text(
                        f"📦 Создание архива...\n"
                        f"Текущий размер: {size:.1f}MB\n"
                        "Пожалуйста, подождите..."
                    )
                await asyncio.sleep(3)  # Update every 3 seconds
        except Exception as e:
            logger.error(f"Error updating archive progress: {e}")

    def _cleanup_on_start(self):
        """Clean up temporary directories on bot start."""
        try:
            logger.info("Cleaning up temporary directories on start...")
            cleanup_temp_files(TEMP_DIR)
            cleanup_temp_files(ARCHIVE_DIR)
            # Recreate archive directory
            os.makedirs(ARCHIVE_DIR, mode=0o755, exist_ok=True)
            logger.info("Temporary directories cleaned successfully")
        except Exception as e:
            logger.error(f"Error cleaning temporary directories on start: {str(e)}")

    def _setup_handlers(self):
        """Set up message handlers."""
        # Handle YouTube links first
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Regex(r'youtube\.com|youtu\.be'),
            self.handle_youtube_link
        ))

        # Then handle video files
        self.application.add_handler(MessageHandler(
            (filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND,
            self.handle_video
        ))

        # Basic commands
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))

        # Add callback query handler for buttons
        self.application.add_handler(CallbackQueryHandler(self.button_click))

    def run(self):
        """Run the bot."""
        logger.info("Starting bot polling...")
        self.application.run_polling()


if __name__ == "__main__":
    bot = SceneDetectionBot()
    bot.run()