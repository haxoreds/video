import os
import logging
import asyncio
from typing import Tuple, Optional, Callable
import httpx
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHUNK_SIZE = 8 * 1024 * 1024  # 8MB chunks
MAX_RETRIES = 3
TELEGRAM_MAX_SIZE = 2 * 1024 * 1024 * 1024  # 2GB

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
    async def upload_to_telegram(file_path: str, bot) -> Tuple[bool, str]:
        """Upload file to Telegram and get file_id."""
        try:
            file_size = os.path.getsize(file_path)
            logger.info(f"Starting upload to Telegram. File size: {file_size/(1024*1024):.1f}MB")

            if file_size > TELEGRAM_MAX_SIZE:
                logger.error(f"File size {file_size/(1024*1024):.1f}MB exceeds Telegram limit of {TELEGRAM_MAX_SIZE/(1024*1024)}MB")
                return False, "Файл слишком большой для загрузки в Telegram (максимум 2GB)"

            logger.info("Uploading file to Telegram...")

            for attempt in range(MAX_RETRIES):
                try:
                    with open(file_path, 'rb') as video_file:
                        # Use longer timeouts for large files
                        response = await bot.send_document(
                            chat_id=bot.id,  # Send to bot itself
                            document=video_file,
                            disable_content_type_detection=True,
                            read_timeout=3600,  # 60 minutes
                            write_timeout=3600,  # 60 minutes
                            connect_timeout=60,  # 1 minute for connection
                            pool_timeout=3600,  # 60 minutes for connection pool
                            chunk_size=CHUNK_SIZE  # Use larger chunks for faster upload
                        )

                        if response and response.document:
                            file_id = response.document.file_id
                            logger.info(f"Successfully uploaded file to Telegram. Received file_id: {file_id}")
                            return True, file_id
                        else:
                            raise Exception("Failed to get file_id from upload response")

                except Exception as e:
                    error_msg = str(e)
                    logger.warning(f"Upload attempt {attempt + 1} failed: {error_msg}")
                    if attempt < MAX_RETRIES - 1:
                        wait_time = (attempt + 1) * 60  # Exponential backoff: 60s, 120s, 180s
                        logger.info(f"Waiting {wait_time} seconds before retry...")
                        await asyncio.sleep(wait_time)
                    else:
                        raise

            raise Exception("Failed to upload after all retries")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error uploading to Telegram: {error_msg}", exc_info=True)
            return False, f"Ошибка загрузки в Telegram: {error_msg}"

    @staticmethod
    async def save_telegram_video(file_id: str, output_path: str, bot, progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """Process video files from Telegram."""
        try:
            logger.info(f"Processing video with file_id: {file_id}")

            # For large files that can't be downloaded directly, return the file_id
            try:
                file = await bot.get_file(file_id)
                file_size = file.file_size if hasattr(file, 'file_size') else None
                logger.info(f"File size from Telegram: {file_size/(1024*1024):.1f}MB" if file_size else "File size unknown")

                if file_size and file_size > 50 * 1024 * 1024:  # > 50MB
                    logger.info("Large file detected (>50MB), using file_id for processing")
                    return True, file_id

            except Exception as e:
                if "File is too big" in str(e):
                    logger.info("Large file detected via error, using file_id for processing")
                    return True, file_id
                else:
                    raise

            # For smaller files, download as usual
            file_path = os.path.join(output_path, "telegram_video.mp4")
            logger.info(f"Downloading file to: {file_path}")

            try:
                await file.download_to_drive(file_path)
                if os.path.exists(file_path):
                    actual_size = os.path.getsize(file_path)
                    logger.info(f"Successfully downloaded file. Size on disk: {actual_size/(1024*1024):.1f}MB")
                    return True, file_path
                else:
                    raise FileNotFoundError("Downloaded file not found on disk")

            except Exception as download_error:
                logger.error(f"Error downloading file: {str(download_error)}", exc_info=True)
                if "File is too big" in str(download_error):
                    logger.info("Large file detected during download, using file_id for processing")
                    return True, file_id
                return False, f"Ошибка при скачивании файла: {str(download_error)}"

        except Exception as e:
            error_msg = str(e)
            if "File is too big" in error_msg:
                logger.info("Large file detected from error, using file_id for processing")
                return True, file_id
            else:
                logger.error(f"Error processing video: {error_msg}", exc_info=True)
                return False, f"Ошибка обработки видео: {error_msg}"

    @staticmethod
    async def download_from_youtube(url: str, output_path: str, bot) -> Tuple[bool, str]:
        """Download video from YouTube URL."""
        try:
            # Clean up the output directory before download
            await DownloadManager.cleanup_temp_files(output_path)
            logger.info(f"Starting YouTube download: {url}")

            import yt_dlp
            ydl_opts = {
                'format': 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4',
                'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
                'socket_timeout': 60,  # Socket timeout increased to 60 seconds
                'retries': 10,  # Number of retries for http/https requests
                'fragment_retries': 10,  # Number of retries for fragments
                'extractor_retries': 10,  # Number of retries for extractors
                'file_access_retries': 10,  # Number of retries for file access
                'http_chunk_size': 10485760,  # 10MB chunks for download
                'progress_hooks': [lambda d: logger.info(f"YouTube download progress: {d.get('_percent_str', 'N/A')} - {d.get('status', 'N/A')}")],
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    # First try to extract info without downloading
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        raise Exception("Could not get video information")

                    # Get estimated file size
                    file_size = info.get('filesize') or info.get('filesize_approx')
                    if file_size:
                        logger.info(f"Estimated video size: {file_size/(1024*1024):.1f}MB")

                    # Now download
                    info = ydl.extract_info(url, download=True)
                    video_path = ydl.prepare_filename(info)

                    if os.path.exists(video_path):
                        file_size = os.path.getsize(video_path)
                        logger.info(f"Downloaded YouTube video. Size: {file_size/(1024*1024):.1f}MB")

                        # For large files, upload to Telegram first
                        if file_size > 50 * 1024 * 1024:  # > 50MB
                            logger.info("Large file detected, uploading to Telegram first")
                            success, result = await DownloadManager.upload_to_telegram(video_path, bot)
                            if success:
                                logger.info("Successfully uploaded to Telegram, returning file_id")
                                return True, result  # Return file_id
                            else:
                                return False, result  # Result contains error message

                        return True, video_path
                    else:
                        raise FileNotFoundError("File not found after download")

                except Exception as download_error:
                    logger.error(f"Error during YouTube download: {str(download_error)}", exc_info=True)
                    raise

        except Exception as e:
            error_msg = str(e)
            logger.error(f"YouTube download failed: {error_msg}", exc_info=True)

            if "Video unavailable" in error_msg:
                return False, "Это видео недоступно или было удалено"
            elif "region" in error_msg.lower():
                return False, "Видео недоступно в вашем регионе"
            elif "copyright" in error_msg.lower():
                return False, "Видео недоступно из-за авторских прав"
            elif "private" in error_msg.lower():
                return False, "Это приватное видео"
            elif "Timed out" in error_msg:
                return False, "Превышено время ожидания при загрузке. Пожалуйста, попробуйте еще раз."
            else:
                return False, f"Ошибка загрузки видео: {error_msg}"