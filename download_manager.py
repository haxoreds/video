import os
import logging
import asyncio
from typing import List, Tuple, Callable, Optional
import time
import requests
import shutil
from urllib.parse import urlparse
import yt_dlp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DownloadManager:
    @staticmethod
    async def cleanup_temp_files(directory: str) -> None:
        """Clean up temporary files in the given directory."""
        try:
            if os.path.exists(directory):
                for file in os.listdir(directory):
                    file_path = os.path.join(directory, file)
                    try:
                        if os.path.isfile(file_path):
                            os.unlink(file_path)
                            logger.info(f"Удален файл: {file_path}")
                    except Exception as e:
                        logger.error(f"Ошибка при удалении файла {file_path}: {str(e)}")
        except Exception as e:
            logger.error(f"Ошибка при очистке временных файлов: {str(e)}")

    @staticmethod
    async def download_from_youtube(url: str, output_path: str) -> Tuple[bool, str]:
        """Download video from YouTube URL using yt-dlp."""
        try:
            # Clean up the output directory before download
            await DownloadManager.cleanup_temp_files(output_path)

            def download_video():
                ydl_opts = {
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
                    'quiet': True,
                    'no_warnings': True,
                    'noplaylist': True,
                    'extract_flat': False,
                }

                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        logger.info("Получение информации о видео...")
                        info = ydl.extract_info(url, download=False)

                        if info.get('duration', 0) > 3600:
                            raise Exception("Видео слишком длинное (более 1 часа). Пожалуйста, выберите видео меньшей длительности.")

                        logger.info("Начинаем загрузку видео...")
                        info = ydl.extract_info(url, download=True)
                        video_path = ydl.prepare_filename(info)

                        if not os.path.exists(video_path):
                            raise Exception("Файл не был создан после загрузки")

                        logger.info(f"Видео загружено: {video_path}")
                        return video_path

                except Exception as e:
                    if "Disk quota exceeded" in str(e):
                        logger.error("Превышена квота диска")
                        raise Exception("Превышена квота диска. Пожалуйста, выберите видео меньшего размера.")
                    raise

            loop = asyncio.get_event_loop()
            file_path = await asyncio.wait_for(
                loop.run_in_executor(None, download_video),
                timeout=600  # 10 minutes timeout
            )

            return True, file_path

        except asyncio.TimeoutError:
            await DownloadManager.cleanup_temp_files(output_path)
            return False, "Превышено время ожидания загрузки видео. Попробуйте видео меньшей длительности."

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Ошибка загрузки видео: {error_msg}", exc_info=True)

            # Clean up on error
            await DownloadManager.cleanup_temp_files(output_path)

            if "quota exceeded" in error_msg.lower():
                return False, "Превышена квота диска. Пожалуйста, выберите видео меньшего размера."
            elif "private video" in error_msg.lower():
                return False, "Это приватное видео, доступ к нему ограничен"
            elif "not available" in error_msg.lower():
                return False, "Это видео недоступно или было удалено"
            elif "network" in error_msg.lower():
                return False, "Ошибка сетевого подключения. Пожалуйста, проверьте подключение к интернету"
            else:
                return False, f"Ошибка загрузки видео: {error_msg}"

    @staticmethod
    async def save_telegram_video(file, output_path: str, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """Save video file received from Telegram."""
        try:
            logger.info("Начинаем сохранение видеофайла из Telegram")
            file_path = os.path.join(output_path, "telegram_video.mp4")

            # Download file using the correct method
            if progress_callback:
                logger.info("Загрузка файла с отслеживанием прогресса")
                try:
                    await file.download_to_drive(file_path)
                except TypeError:
                    # If download_to_drive doesn't accept progress callback
                    await file.download_to_drive(file_path)
            else:
                logger.info("Загрузка файла без отслеживания прогресса")
                await file.download_to_drive(file_path)

            file_size = os.path.getsize(file_path) / (1024 * 1024)
            logger.info(f"Видеофайл успешно сохранен. Размер: {file_size:.1f}МБ")

            return True, file_path
        except Exception as e:
            logger.error(f"Ошибка сохранения видео из Telegram: {str(e)}", exc_info=True)
            return False, f"Ошибка сохранения видео: {str(e)}"