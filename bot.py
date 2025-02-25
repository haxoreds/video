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

        status_message = await message.reply_text("⏳ Загрузка видео с YouTube... 0%")

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
            success, result = await DownloadManager.download_from_youtube(text, temp_dir)

            if not success:
                error_msg = result
                logger.error(f"YouTube download failed: {error_msg}")
                cleanup_temp_files(temp_dir)
                await status_message.edit_text(f"❌ {error_msg}")
                return

            logger.info(f"Successfully downloaded YouTube video to: {result}")
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

        status_message = await message.reply_text("⏳ Начинаем загрузку видео...")
        temp_dir = create_temp_dir()
        logger.info(f"Created temporary directory for video: {temp_dir}")

        try:
            async def progress_callback(current, total):
                try:
                    percent = int(current * 100 / total) if total > 0 else 0
                    progress_text = f"⏳ Загрузка видео... {percent}%\n{format_progress_bar(percent)}"
                    await status_message.edit_text(progress_text)
                except Exception as e:
                    logger.error(f"Error updating progress: {e}")

            # Get file_id and size from either video or document
            if message.video:
                file_id = message.video.file_id
                file_size = message.video.file_size
                logger.info(f"Processing video: size={file_size/(1024*1024):.1f}MB")
            else:
                file_id = message.document.file_id
                file_size = message.document.file_size
                logger.info(f"Processing document: size={file_size/(1024*1024):.1f}MB")

            success, result = await DownloadManager.save_telegram_video(file_id, temp_dir, context.bot, progress_callback)
            if not success:
                logger.error(f"Failed to save video: {result}")
                await status_message.edit_text(f"❌ {result}")
                cleanup_temp_files(temp_dir)
                return

            logger.info(f"Successfully saved video to: {result}")
            await self.process_video_and_show_options(result, status_message, temp_dir)

        except Exception as e:
            logger.exception("Error processing video file")
            error_msg = str(e)
            await status_message.edit_text(f"❌ Произошла ошибка: {error_msg}")
            cleanup_temp_files(temp_dir)

    async def process_video_and_show_options(self, video_path: str, status_message, temp_dir: str):
        """Process video and show delivery options."""
        try:
            logger.info(f"Starting video processing for: {video_path}")

            is_valid, error = VideoProcessor.validate_video(video_path)
            if not is_valid:
                logger.error(f"Video validation failed: {error}")
                await status_message.edit_text(f"❌ {error}")
                cleanup_temp_files(temp_dir)  # Clean up on validation error
                return

            await status_message.edit_text("🎬 Определение и разделение сцен...\n" + format_progress_bar(0))

            try:
                async def progress_callback(progress: int, stage: str = ""):
                    logger.info(f"Processing progress: {progress}% - {stage}")
                    progress_text = f"🎬 {stage}\n{format_progress_bar(progress)}"
                    return await status_message.edit_text(progress_text)

                # Добавляем таймаут в 10 минут для процесса обработки видео
                async with asyncio.timeout(600):  # 10 минут
                    success, scenes = await VideoProcessor.detect_and_split_scenes(
                        video_path,
                        temp_dir,
                        progress_callback
                    )

                    if not success:
                        logger.error(f"Scene detection failed: {scenes[0]}")
                        await status_message.edit_text(f"❌ {scenes[0]}")
                        cleanup_temp_files(temp_dir)  # Clean up on detection failure
                        return

                    logger.info(f"Successfully split video into {len(scenes)} scenes")

                    # Create inline keyboard with two buttons
                    keyboard = [
                        [
                            InlineKeyboardButton("📤 Получить в Telegram", callback_data=f"telegram|{temp_dir}"),
                            InlineKeyboardButton("📦 Скачать архивом", callback_data=f"archive|{temp_dir}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await status_message.edit_text(
                        f"✅ Видео успешно разделено на {len(scenes)} сцен!\n"
                        "Выберите способ получения:",
                        reply_markup=reply_markup
                    )

            except asyncio.TimeoutError:
                logger.error("Video processing timed out")
                await status_message.edit_text(
                    "❌ Превышено время обработки видео. Пожалуйста, попробуйте видео меньшей длительности "
                    "или свяжитесь с администратором."
                )
                cleanup_temp_files(temp_dir)  # Clean up on timeout
                return

        except Exception as e:
            logger.exception("Error in video processing")
            await status_message.edit_text(f"❌ Произошла ошибка при обработке видео: {str(e)}")
            cleanup_temp_files(temp_dir)  # Clean up on any other error

    async def send_scenes_telegram(self, message, temp_dir: str):
        """Send scenes via Telegram."""
        try:
            # Get all scene files and sort them numerically
            scenes = [f for f in os.listdir(temp_dir) if f.endswith('.mp4')]
            scenes.sort(key=lambda x: int(x.split('-')[1].split('.')[0]))
            scene_paths = [os.path.join(temp_dir, scene) for scene in scenes]

            logger.info(f"Отправка сцен в порядке: {', '.join(scenes)}")

            await message.edit_text(f"📤 Отправка {len(scenes)} сцен... 0%")

            # Process scenes sequentially
            total_scenes = len(scenes)
            scenes_sent = 0

            # Send scenes one by one to maintain order
            for scene_path in scene_paths:
                try:
                    with open(scene_path, 'rb') as video:
                        scene_number = int(os.path.basename(scene_path).split('-')[1].split('.')[0])
                        await self.application.bot.send_video(
                            chat_id=message.chat_id,
                            video=video,
                            caption=f"Сцена {scene_number}",
                            supports_streaming=True
                        )
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
            try:
                cleanup_temp_files(temp_dir)
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {str(cleanup_error)}")

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

            # Check if archive already exists and is complete
            if os.path.exists(archive_path):
                logger.info(f"Found existing archive: {archive_path}")
                await message.edit_text("📦 Найден существующий архив. Начинаем отправку...")
            else:
                # Calculate total size of scenes
                total_size = sum(os.path.getsize(os.path.join(temp_dir, scene)) for scene in scenes)
                logger.info(f"Total size of scenes to archive: {total_size/(1024*1024):.1f}MB")

                # Create archive command with faster compression settings
                scene_paths = ' '.join([os.path.abspath(os.path.join(temp_dir, scene)) for scene in scenes])
                # Use -1 for fastest compression
                zip_command = f"zip -1 -j '{archive_path}' {scene_paths}"

                logger.info(f"Running zip command: {zip_command}")
                await message.edit_text("📦 Создание архива...\nЭто может занять несколько минут.")

                process = await asyncio.create_subprocess_shell(
                    zip_command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                try:
                    # Start a background task to update the message periodically
                    update_msg_task = asyncio.create_task(
                        self._update_archive_progress(message, archive_path)
                    )

                    # Wait for the process with a 5-minute timeout
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)

                    # Cancel the progress update task
                    update_msg_task.cancel()
                    try:
                        await update_msg_task
                    except asyncio.CancelledError:
                        pass

                    if stdout:
                        logger.info(f"zip stdout: {stdout.decode()}")
                    if stderr:
                        logger.warning(f"zip stderr: {stderr.decode()}")

                    if process.returncode != 0:
                        error_msg = stderr.decode() if stderr else "Unknown error"
                        logger.error(f"zip process failed with return code {process.returncode}: {error_msg}")
                        await message.edit_text(
                            f"❌ Ошибка при создании архива: {error_msg}\n"
                            "Попробуйте еще раз или используйте опцию отправки сцен по отдельности."
                        )
                        return

                except asyncio.TimeoutError:
                    if process and process.returncode is None:
                        process.kill()
                    logger.error("Archive creation timed out")
                    await message.edit_text(
                        "❌ Превышено время создания архива. "
                        "Попробуйте еще раз или используйте опцию отправки сцен по отдельности."
                    )
                    return

            try:
                if not os.path.exists(archive_path):
                    logger.error(f"Archive not found at path: {archive_path}")
                    await message.edit_text("❌ Архив не был создан")
                    return

                archive_size = os.path.getsize(archive_path)
                logger.info(f"Archive size: {archive_size/(1024*1024):.1f}MB")

                if archive_size > TELEGRAM_MAX_FILE_SIZE:
                    logger.warning(
                        f"Archive size {archive_size/(1024*1024):.1f}MB exceeds "
                        f"Telegram limit {TELEGRAM_MAX_FILE_SIZE/(1024*1024)}MB"
                    )
                    await message.edit_text(
                        f"❌ Размер архива ({archive_size/(1024*1024):.1f}MB) превышает лимит Telegram (2GB). "
                        "Пожалуйста, используйте опцию отправки сцен по отдельности."
                    )
                    return

                await message.edit_text("📤 Отправка архива...")

                # Multiple attempts to send the file with exponential backoff
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        # Each attempt gets more time
                        timeout = 600 * (attempt + 1)  # 10, 20, 30 minutes
                        logger.info(f"Attempt {attempt + 1}/{max_retries} with {timeout}s timeout")

                        async with asyncio.timeout(timeout):
                            with open(archive_path, 'rb') as archive:
                                sent_message = await message.reply_document(
                                    document=archive,
                                    filename=archive_name,
                                    caption=f"📦 Архив со сценами - {len(scenes)} сцен",
                                    read_timeout=timeout,
                                    write_timeout=timeout,
                                    connect_timeout=60
                                )

                            if sent_message:
                                await message.edit_text("✅ Архив успешно отправлен!")
                                logger.info("Archive sent successfully")
                                # Clean up the archive after successful send
                                try:
                                    os.unlink(archive_path)
                                    logger.info(f"Cleaned up archive file: {archive_path}")
                                except Exception as e:
                                    logger.error(f"Error cleaning up archive: {e}")
                                break
                            else:
                                raise Exception("Failed to send archive - no response from Telegram")

                    except asyncio.TimeoutError:
                        logger.error(f"Timeout on attempt {attempt + 1}")
                        if attempt < max_retries - 1:
                            wait_time = 30 * (attempt + 1)  # 30, 60, 90 seconds
                            await message.edit_text(
                                f"⚠️ Таймаут при отправке архива (попытка {attempt + 1}/{max_retries}).\n"
                                f"Повторная попытка через {wait_time} секунд..."
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            await message.edit_text(
                                "❌ Не удалось отправить архив после нескольких попыток.\n"
                                "Архив сохранен. После перезапуска бота нажмите 'Скачать архивом' для повторной попытки."
                            )
                    except Exception as e:
                        logger.error(f"Error on attempt {attempt + 1}: {str(e)}")
                        if attempt < max_retries - 1:
                            wait_time = 30 * (attempt + 1)
                            await message.edit_text(
                                f"⚠️ Ошибка при отправке архива (попытка {attempt + 1}/{max_retries}).\n"
                                f"Повторная попытка через {wait_time} секунд..."
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            await message.edit_text(
                                "❌ Не удалось отправить архив после нескольких попыток.\n"
                                "Архив сохранен. После перезапуска бота нажмите 'Скачать архивом' для повторной попытки."
                            )

            except Exception as e:
                logger.exception(f"Error in send_scenes_archive: {str(e)}")
                await message.edit_text(f"❌ Ошибка при работе с архивом: {str(e)}")
        finally:
            try:
                cleanup_temp_files(temp_dir)
                logger.debug(f"Cleaned up temporary directory: {temp_dir}")
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {str(cleanup_error)}")

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
            filters.TEXT & ~filters.COMMAND,
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
        self.application.run_polling()

if __name__ == "__main__":
    bot = SceneDetectionBot()
    bot.run()