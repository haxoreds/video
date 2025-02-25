import os
import logging
import asyncio
from typing import Tuple, Optional, Callable
import httpx
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
                    'format': 'bestvideo*+bestaudio/best',  # Get best quality available
                    'format_sort': ['res:2160', 'res:1440', 'res:1080', 'res:720'],  # Prioritize higher resolutions
                    'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
                    'merge_output_format': 'mp4',  # Ensure final format is mp4
                    'postprocessor_args': ['-c:v', 'copy', '-c:a', 'copy'],  # Copy streams without re-encoding
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

                        logger.info("Начинаем загрузку видео в максимальном качестве...")
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
    async def save_telegram_video(file_id: str, output_path: str, bot, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """Download video files from Telegram with progress tracking."""
        try:
            logger.info(f"Starting download for file_id: {file_id}")
            file_path = os.path.join(output_path, "telegram_video.mp4")

            # Get file object directly from bot
            try:
                file = await bot.get_file(file_id)
                logger.info("Successfully got file object")

                # Download the file directly without getting URL
                await file.download_to_drive(custom_path=file_path)

                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    logger.info(f"Download completed. File size: {file_size/(1024*1024):.1f}MB")
                    return True, file_path
                else:
                    raise FileNotFoundError("Downloaded file not found")

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Download failed: {error_msg}", exc_info=True)
                if "file is too big" in error_msg.lower():
                    logger.info("File is too big for direct download, trying chunked download...")
                    try:
                        # Try alternative chunked download method
                        chunks = []
                        chunk_size = 64 * 1024  # 64KB chunks
                        offset = 0

                        with open(file_path, 'wb') as f:
                            while True:
                                chunk = await bot.download_file_by_id(
                                    file_id,
                                    offset=offset,
                                    limit=chunk_size
                                )
                                if not chunk:
                                    break

                                f.write(chunk)
                                offset += len(chunk)

                                if progress_callback:
                                    try:
                                        await progress_callback(offset, file.file_size)
                                    except Exception as e:
                                        logger.error(f"Progress callback error: {e}")

                        if os.path.exists(file_path):
                            actual_size = os.path.getsize(file_path)
                            logger.info(f"Chunked download completed. File size: {actual_size/(1024*1024):.1f}MB")
                            return True, file_path

                    except Exception as chunk_error:
                        logger.error(f"Chunked download failed: {str(chunk_error)}", exc_info=True)
                        raise
                else:
                    raise

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Download failed: {error_msg}", exc_info=True)
            return False, f"Ошибка загрузки видео: {error_msg}"