import os
import asyncio
import logging
from typing import List
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from config import BOT_TOKEN, TEMP_DIR, MAX_VIDEO_SIZE, ARCHIVE_DIR
from download_manager import DownloadManager
from video_processor import VideoProcessor
from utils import create_temp_dir, cleanup_temp_files, split_list
import shutil

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

SUPPORTED_VIDEO_FORMATS = ('.mp4', '.avi', '.mkv', '.mov')

def ensure_directories():
    """Create necessary directories if they don't exist."""
    os.makedirs(TEMP_DIR, mode=0o755, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, mode=0o755, exist_ok=True)
    logger.info(f"Created temporary directories: {TEMP_DIR}, {ARCHIVE_DIR}")

class SceneDetectionBot:
    def __init__(self):
        self.application = Application.builder().token(BOT_TOKEN).build()
        ensure_directories()
        self._cleanup_on_start()  # Add cleanup on start
        self._setup_handlers()

    def _cleanup_on_start(self):
        """Clean up temporary directories on bot start."""
        try:
            logger.info("Cleaning up temporary directories on start...")
            cleanup_temp_files(TEMP_DIR)
            cleanup_temp_files(ARCHIVE_DIR)
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

        logger.debug(f"Received message type: video={bool(message.video)}, document={bool(message.document)}")

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

        status_message = await message.reply_text("⏳ Получение видеофайла... 0%")
        temp_dir = create_temp_dir()
        logger.info(f"Created temporary directory for video: {temp_dir}")

        try:
            # Get file_id from either video or document
            file_id = message.video.file_id if message.video else message.document.file_id
            logger.info(f"Processing file with ID: {file_id}")

            file = await context.bot.get_file(file_id)
            logger.debug(f"Retrieved file object: {file}")

            # Check file size
            if file.file_size > MAX_VIDEO_SIZE:
                await status_message.edit_text(
                    f"❌ Видеофайл слишком большой. Максимальный размер: {MAX_VIDEO_SIZE/(1024*1024):.1f}МБ"
                )
                cleanup_temp_files(temp_dir)
                return

            async def progress(current, total):
                percent = int(current * 100 / total)
                await status_message.edit_text(f"⏳ Загрузка видеофайла... {percent}%")

            success, result = await DownloadManager.save_telegram_video(file, temp_dir, progress)
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
            if "file is too big" in error_msg.lower():
                await status_message.edit_text(
                    f"❌ Видеофайл слишком большой. Максимальный размер: {MAX_VIDEO_SIZE/(1024*1024):.1f}МБ"
                )
            else:
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

            await status_message.edit_text("🎬 Определение и разделение сцен... 0%")

            try:
                # Добавляем таймаут в 10 минут для процесса обработки видео
                async with asyncio.timeout(600):  # 10 минут
                    success, scenes = await VideoProcessor.detect_and_split_scenes(
                        video_path,
                        temp_dir,
                        lambda progress: status_message.edit_text(f"🎬 Обработка видео... {progress}%")
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
        """Create and send 7z archive with scenes."""
        try:
            # Check if 7zip is available
            if not await self.check_7zip_available():
                logger.error("7zip is not available in the system")
                await message.edit_text("❌ Ошибка: архиватор 7zip недоступен в системе")
                return

            # Get all scene files
            scenes = [f for f in os.listdir(temp_dir) if f.endswith('.mp4')]
            if not scenes:
                logger.warning("No scenes found for archiving")
                await message.edit_text("❌ Не найдены сцены для архивации")
                return

            await message.edit_text("📦 Создание архива со сценами...")

            # Clean up archive directory before starting
            try:
                logger.info("Cleaning up archive directory before creating new archive...")
                cleanup_temp_files(ARCHIVE_DIR)
                logger.info("Archive directory cleaned successfully")
            except Exception as e:
                logger.error(f"Error cleaning archive directory: {str(e)}")
                await message.edit_text("❌ Ошибка при подготовке к созданию архива")
                return

            # Create archive name and path
            archive_name = "scenes.7z"
            archive_path = os.path.join(ARCHIVE_DIR, archive_name)

            # Ensure archive directory exists
            os.makedirs(os.path.dirname(archive_path), exist_ok=True)

            # Create simple archive command
            scene_paths = ' '.join([os.path.join(temp_dir, scene) for scene in scenes])
            seven_zip_command = f"7z a {archive_path} {scene_paths}"

            logger.info(f"Running 7zip command: {seven_zip_command}")

            process = await asyncio.create_subprocess_shell(
                seven_zip_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                # Wait for the process with timeout
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)  # 10 minutes timeout

                if stdout:
                    logger.info(f"7zip stdout: {stdout.decode()}")
                if stderr:
                    logger.error(f"7zip stderr: {stderr.decode()}")

                if process.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    logger.error(f"7zip process failed with return code {process.returncode}: {error_msg}")
                    await message.edit_text(
                        f"❌ Ошибка при создании архива. Пожалуйста, попробуйте использовать "
                        "опцию отправки сцен по отдельности."
                    )
                    return

                if os.path.exists(archive_path):
                    archive_size = os.path.getsize(archive_path)
                    logger.info(f"Archive created successfully. Size: {archive_size/(1024*1024):.1f}MB")

                    try:
                        with open(archive_path, 'rb') as archive:
                            await message.reply_document(
                                document=archive,
                                filename=archive_name,
                                caption=f"📦 Архив со сценами - {len(scenes)} сцен"
                            )
                        await message.edit_text("✅ Архив успешно отправлен!")
                        logger.info("Archive sent successfully")
                    except Exception as send_error:
                        logger.error(f"Error sending archive: {str(send_error)}")
                        await message.edit_text(
                            "❌ Ошибка при отправке архива.\n"
                            "Попробуйте использовать опцию отправки сцен по отдельности."
                        )
                else:
                    logger.error(f"Archive not found at path: {archive_path}")
                    await message.edit_text("❌ Архив не был создан")

            except asyncio.TimeoutError:
                logger.error("7zip process timed out")
                if process.returncode is None:
                    process.kill()
                await message.edit_text(
                    "❌ Превышено время создания архива. "
                    "Попробуйте создать архив с меньшим количеством сцен."
                )

        except Exception as e:
            logger.exception(f"Error creating archive: {str(e)}")
            await message.edit_text(f"❌ Ошибка при создании архива: {str(e)}")
        finally:
            # Cleanup all temporary files
            try:
                cleanup_temp_files(temp_dir)
                if os.path.exists(archive_path):
                    os.unlink(archive_path)
                    logger.debug(f"Cleaned up archive file: {archive_path}")
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

    def run(self):
        """Run the bot."""
        self.application.run_polling()

if __name__ == "__main__":
    bot = SceneDetectionBot()
    bot.run()