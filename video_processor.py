from typing import List, Tuple, Callable, Optional
import cv2
from scenedetect import detect, ContentDetector, split_video_ffmpeg
from config import MIN_SCENE_LENGTH, THRESHOLD, TELEGRAM_MAX_FILE_SIZE, SUPPORTED_VIDEO_FORMATS
import logging
import asyncio
import psutil
import os
import subprocess
import json
from urllib.parse import quote

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VideoProcessor:
    @staticmethod
    def validate_video(file_path: str) -> Tuple[bool, str]:
        """Validate if the file is a valid video."""
        try:
            logger.info(f"Starting video validation: {file_path}")

            if not os.path.isfile(file_path):
                return False, "Video file does not exist"

            if not os.access(file_path, os.R_OK):
                return False, "No access to video file"

            _, ext = os.path.splitext(file_path)
            if ext.lower() not in SUPPORTED_VIDEO_FORMATS:
                error_msg = f"Unsupported video format. Supported formats: {', '.join(SUPPORTED_VIDEO_FORMATS)}"
                logger.error(error_msg)
                return False, error_msg

            file_size = os.path.getsize(file_path)
            if file_size > TELEGRAM_MAX_FILE_SIZE:
                error_msg = f"Video file too large. Maximum size: {TELEGRAM_MAX_FILE_SIZE/(1024*1024)}MB"
                logger.error(error_msg)
                return False, error_msg

            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                logger.error("Could not open video file")
                return False, "Invalid video file"

            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count/fps if fps > 0 else 0

            logger.info(f"Video parameters: FPS={fps}, Frames={frame_count}, Duration={duration:.2f}s")

            if fps <= 0 or frame_count <= 0:
                logger.error("Invalid video parameters detected")
                return False, "Invalid video file: could not determine duration"

            if duration < MIN_SCENE_LENGTH:
                logger.error(f"Video too short: {duration:.2f}s < {MIN_SCENE_LENGTH}s")
                return False, f"Video too short. Minimum duration: {MIN_SCENE_LENGTH} seconds"

            cap.release()
            logger.info("Video validation completed successfully")
            return True, ""

        except Exception as e:
            logger.error(f"Error during video validation: {str(e)}")
            return False, f"Error during video validation: {str(e)}"

    @staticmethod
    async def detect_and_split_scenes(
        video_path: str, 
        output_dir: str,
        progress_callback: Callable[[int, str], None] = None
    ) -> Tuple[bool, List[str]]:
        """Detect and split video into scenes using PySceneDetect."""
        try:
            logger.info(f"Starting scene detection for video: {video_path}")
            logger.info(f"Output directory: {output_dir}")

            # Monitor memory usage
            process = psutil.Process()
            initial_memory = process.memory_info().rss / 1024 / 1024
            logger.info(f"Initial memory usage: {initial_memory:.1f}MB")

            if progress_callback:
                await progress_callback(5, "Чтение метаданных видео")

            # Validate video file
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise ValueError("Could not open video file")

            # Get and log video parameters
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = frame_count/fps if fps > 0 else 0

            logger.info(f"Video parameters: FPS={fps}, Frames={frame_count}, "
                      f"Resolution={width}x{height}, Duration={duration:.2f}s")
            logger.info(f"Scene detection parameters: threshold={THRESHOLD}, "
                      f"min_scene_length={MIN_SCENE_LENGTH}s")

            cap.release()

            if progress_callback:
                await progress_callback(10, "Инициализация определения сцен")

            # Run detection with progress updates
            logger.info("Starting scene detection...")

            # Monitor memory before detection
            pre_detect_memory = process.memory_info().rss / 1024 / 1024
            logger.info(f"Memory usage before detection: {pre_detect_memory:.1f}MB")

            if progress_callback:
                await progress_callback(15, "Анализ видеопотока")

            # Use improved detector settings
            detector = ContentDetector(
                threshold=THRESHOLD,
                min_scene_len=int(MIN_SCENE_LENGTH * fps)
            )

            # Run detection
            scenes = detect(video_path, detector)

            # Monitor memory after detection
            post_detect_memory = process.memory_info().rss / 1024 / 1024
            logger.info(f"Memory usage after detection: {post_detect_memory:.1f}MB")
            logger.info(f"Memory increase during detection: {post_detect_memory - pre_detect_memory:.1f}MB")

            if not scenes:
                logger.warning("No scenes detected")
                return False, ["Не удалось определить сцены в видео. Попробуйте настроить параметры чувствительности."]

            logger.info(f"Found {len(scenes)} scenes")
            total_scenes = len(scenes)

            # Log scene boundaries
            for i, scene in enumerate(scenes, 1):
                start_time = scene[0].get_seconds()
                end_time = scene[1].get_seconds()
                duration = end_time - start_time
                logger.info(f"Scene {i}/{total_scenes}: "
                          f"Start={start_time:.2f}s, End={end_time:.2f}s, "
                          f"Duration={duration:.2f}s")

                if progress_callback:
                    scene_progress = 15 + int((i / total_scenes) * 25)  # Progress from 15% to 40%
                    await progress_callback(scene_progress, f"Анализ сцены {i}/{total_scenes}")

            if progress_callback:
                await progress_callback(40, "Разделение на сцены")

            # Video splitting with detailed progress tracking
            logger.info("Starting video splitting...")
            try:
                async with asyncio.timeout(600):  # 10 minutes timeout
                    split_video_ffmpeg(
                        video_path, 
                        scenes, 
                        output_dir,
                        suppress_output=False,
                        arg_override="-c:v copy -c:a copy"  # Copy streams without re-encoding
                    )

                    # Verify each split scene
                    for i, scene in enumerate(scenes, 1):
                        if progress_callback:
                            split_progress = 40 + int((i / total_scenes) * 40)  # Progress from 40% to 80%
                            await progress_callback(split_progress, f"Сохранение сцены {i}/{total_scenes}")

                        scene_file = os.path.join(output_dir, f"scene-{i:03d}.mp4")
                        if os.path.exists(scene_file):
                            scene_size = os.path.getsize(scene_file) / (1024 * 1024)
                            logger.info(f"Created scene file: {scene_file} (Size: {scene_size:.1f}MB)")
                        else:
                            logger.warning(f"Scene file not found: {scene_file}")

            except asyncio.TimeoutError:
                logger.error("Video splitting timed out")
                return False, ["Превышено время разделения видео. Попробуйте видео меньшей длительности."]

            if progress_callback:
                await progress_callback(80, "Финальная обработка")

            # Rename and verify scenes
            scene_files = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
            logger.info(f"Found {len(scene_files)} output files")

            renamed_files = []
            for i, old_name in enumerate(sorted(scene_files), 1):
                old_path = os.path.join(output_dir, old_name)
                new_name = f'scene-{i:03d}.mp4'
                new_path = os.path.join(output_dir, new_name)
                os.rename(old_path, new_path)
                renamed_files.append(new_path)
                logger.info(f"Renamed {old_name} to {new_name}")

            if not renamed_files:
                logger.error("No scene files were created")
                return False, ["Не удалось создать файлы сцен"]

            # Log final memory usage
            final_memory = process.memory_info().rss / 1024 / 1024
            logger.info(f"Final memory usage: {final_memory:.1f}MB")
            logger.info(f"Total memory change: {final_memory - initial_memory:.1f}MB")

            if progress_callback:
                await progress_callback(100, "Обработка завершена")

            logger.info(f"Successfully created {len(renamed_files)} scene files")
            return True, sorted(renamed_files)

        except Exception as e:
            logger.exception(f"Error processing scenes: {str(e)}")
            return False, [f"Ошибка обработки видео: {str(e)}"]

    @staticmethod
    def rename_scenes(output_dir: str) -> List[str]:
        """Rename scene files to have sequential numbers."""
        try:
            # Get all scene files
            scene_files = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
            scene_files.sort()

            renamed_files = []
            for i, old_name in enumerate(scene_files, 1):
                old_path = os.path.join(output_dir, old_name)
                new_name = f'scene-{i:03d}.mp4'  # Use 3 digits padding
                new_path = os.path.join(output_dir, new_name)

                os.rename(old_path, new_path)
                renamed_files.append(new_path)
                logger.info(f"Renamed file {old_name} to {new_name}")

            return renamed_files
        except Exception as e:
            logger.error(f"Error renaming scenes: {str(e)}")
            return []

    @staticmethod
    async def detect_and_split_scenes_from_file_id(
        file_id: str,
        output_dir: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        bot = None
    ) -> Tuple[bool, List[str]]:
        """Process large video files using chunks."""
        try:
            logger.info(f"Processing large file with file_id: {file_id}")

            if progress_callback:
                await progress_callback(10, "Подготовка к обработке большого файла")

            # Create chunks directory
            chunks_dir = os.path.join(output_dir, "chunks")
            os.makedirs(chunks_dir, exist_ok=True)

            # Get file info
            try:
                file = await bot.get_file(file_id)
                total_size = file.file_size if hasattr(file, 'file_size') else None
                if total_size:
                    logger.info(f"File size: {total_size/(1024*1024):.1f}MB")
                else:
                    logger.warning("Could not determine file size")

                if progress_callback:
                    await progress_callback(20, "Загрузка видео частями")

                # Download the file in chunks
                chunk_size = 20 * 1024 * 1024  # 20MB chunks
                downloaded = 0
                chunks = []

                while True:
                    try:
                        offset = len(chunks) * chunk_size
                        chunk_path = os.path.join(chunks_dir, f"chunk_{len(chunks):03d}.mp4")

                        # Get chunk with retries
                        for retry in range(3):
                            try:
                                chunk_data = await file.download_chunk(
                                    offset=offset,
                                    chunk_size=chunk_size,
                                    read_timeout=300,  # 5 minutes per chunk
                                    write_timeout=300
                                )
                                if chunk_data:
                                    break
                                if retry == 2:  # Last retry
                                    if not chunks:  # No chunks downloaded yet
                                        raise Exception("Could not download any chunks")
                                    break
                            except Exception as chunk_error:
                                if "File is too big" in str(chunk_error):
                                    logger.warning("Chunk download failed due to file size")
                                    if not chunks:  # No chunks downloaded yet
                                        return False, ["Видео слишком большое для обработки"]
                                    break
                                if retry < 2:
                                    logger.warning(f"Retry {retry + 1} for chunk download: {str(chunk_error)}")
                                    await asyncio.sleep(30 * (retry + 1))
                                    continue
                                raise

                        if not chunk_data:
                            break

                        # Save chunk
                        with open(chunk_path, 'wb') as f:
                            f.write(chunk_data)
                        chunks.append(chunk_path)

                        downloaded += len(chunk_data)
                        if total_size:
                            progress = min(40, 20 + int(downloaded * 20 / total_size))
                            if progress_callback:
                                await progress_callback(
                                    progress,
                                    f"Загружено {downloaded/(1024*1024):.1f}MB"
                                    + (f" из {total_size/(1024*1024):.1f}MB" if total_size else "")
                                )

                        if len(chunk_data) < chunk_size:
                            break

                        # Small delay between chunks
                        await asyncio.sleep(0.5)

                    except Exception as e:
                        logger.error(f"Error downloading chunk: {str(e)}")
                        raise

                if not chunks:
                    return False, ["Не удалось загрузить видео"]

                # Combine chunks
                if progress_callback:
                    await progress_callback(45, "Объединение частей видео")

                output_file = os.path.join(output_dir, "combined_video.mp4")
                with open(output_file, 'wb') as outfile:
                    for chunk in chunks:
                        with open(chunk, 'rb') as infile:
                            while True:
                                chunk_data = infile.read(8 * 1024 * 1024)  # Read 8MB at a time
                                if not chunk_data:
                                    break
                                outfile.write(chunk_data)

                # Clean up chunks
                for chunk in chunks:
                    try:
                        os.unlink(chunk)
                    except:
                        pass
                try:
                    os.rmdir(chunks_dir)
                except:
                    pass

                if progress_callback:
                    await progress_callback(50, "Определение сцен")

                # Process the combined video
                success, scenes = await VideoProcessor.detect_and_split_scenes(
                    output_file,
                    output_dir,
                    progress_callback
                )

                # Clean up the combined video
                try:
                    os.unlink(output_file)
                except:
                    pass

                return success, scenes

            except Exception as download_error:
                logger.error(f"Error downloading file: {str(download_error)}", exc_info=True)
                if "File is too big" in str(download_error):
                    return False, ["Видео слишком большое для обработки"]
                raise

        except Exception as e:
            logger.error(f"Error processing large file: {str(e)}", exc_info=True)
            return False, [f"Ошибка обработки большого файла: {str(e)}"]

    @staticmethod
    async def process_telegram_stream(
        file_id: str,
        output_dir: str,
        bot,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Tuple[bool, List[str]]:
        """Process video directly from Telegram stream."""
        try:
            logger.info(f"Starting stream processing for file_id: {file_id}")

            if progress_callback:
                await progress_callback(10, "Получение информации о видео")

            # Get file info from Telegram
            try:
                file = await bot.get_file(file_id)
                file_size = file.file_size if hasattr(file, 'file_size') else None
                logger.info(f"Got file size from Telegram: {file_size/(1024*1024):.1f}MB" if file_size else "File size unknown")
            except Exception as e:
                if "file is too big" in str(e).lower():
                    logger.info("Large file detected, switching to chunked download")
                else:
                    logger.error(f"Error getting file info: {e}")
                    return False, ["Не удалось получить информацию о видео"]

            if progress_callback:
                await progress_callback(20, "Загрузка видео")

            chunks_dir = os.path.join(output_dir, "chunks")
            os.makedirs(chunks_dir, exist_ok=True)
            chunks = []

            try:
                chunk_size = 20 * 1024 * 1024  # 20MB chunks
                downloaded = 0
                chunk_number = 0
                retry_count = 0
                max_retries = 3

                while True:
                    try:
                        logger.debug(f"Downloading chunk {chunk_number}, offset: {downloaded}")
                        chunk_path = os.path.join(chunks_dir, f"chunk_{chunk_number:03d}.mp4")

                        chunk_data = await file.download_chunk(
                            offset=downloaded,
                            chunk_size=chunk_size,
                            read_timeout=300,  # 5 minutes per chunk
                            write_timeout=300
                        )

                        if not chunk_data:
                            if chunk_number == 0:
                                logger.error("No data received in first chunk")
                                return False, ["Ошибка загрузки видео. Попробуйте еще раз."]
                            break

                        # Save chunk
                        with open(chunk_path, 'wb') as f:
                            f.write(chunk_data)
                        chunks.append(chunk_path)
                        chunk_size = len(chunk_data)
                        logger.debug(f"Saved chunk {chunk_number}, size: {chunk_size/(1024*1024):.1f}MB")

                        downloaded += chunk_size
                        chunk_number += 1

                        if file_size:
                            progress = min(80, 20 + int(downloaded * 60 / file_size))
                            if progress_callback:
                                await progress_callback(
                                    progress,
                                    f"Загружено {downloaded/(1024*1024):.1f}MB из {file_size/(1024*1024):.1f}MB"
                                )

                        retry_count = 0  # Reset retry counter after successful chunk
                        await asyncio.sleep(0.5)  # Small delay between chunks

                    except Exception as e:
                        retry_count += 1
                        logger.error(f"Error downloading chunk {chunk_number} (attempt {retry_count}): {e}")

                        if retry_count >= max_retries:
                            raise Exception(f"Failed to download chunk after {max_retries} attempts")

                        await asyncio.sleep(retry_count * 2)  # Exponential backoff
                        continue

                if not chunks:
                    logger.error("No chunks downloaded")
                    return False, ["Не удалось загрузить видео"]

                logger.info(f"Successfully downloaded {len(chunks)} chunks, total size: {downloaded/(1024*1024):.1f}MB")

                # Combine chunks
                if progress_callback:
                    await progress_callback(90, "Объединение частей видео")

                output_file = os.path.join(output_dir, "video.mp4")
                with open(output_file, 'wb') as outfile:
                    for chunk in chunks:
                        try:
                            with open(chunk, 'rb') as infile:
                                while True:
                                    chunk_data = infile.read(8 * 1024 * 1024)  # 8MB at a time
                                    if not chunk_data:
                                        break
                                    outfile.write(chunk_data)
                        except Exception as e:
                            logger.error(f"Error combining chunk {chunk}: {e}")
                            raise

                # Verify the output file
                if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
                    logger.error("Output file is missing or empty")
                    return False, ["Ошибка при сохранении видео"]

                # Clean up chunks
                for chunk in chunks:
                    try:
                        if os.path.exists(chunk):
                            os.unlink(chunk)
                    except Exception as e:
                        logger.error(f"Error cleaning up chunk {chunk}: {e}")

                try:
                    if os.path.exists(chunks_dir):
                        os.rmdir(chunks_dir)
                except Exception as e:
                    logger.error(f"Error removing chunks directory: {e}")

                logger.info(f"Successfully created video file: {output_file}")

                if progress_callback:
                    await progress_callback(100, "Обработка завершена")

                return True, [output_file]

            except Exception as e:
                # Clean up on error
                for chunk in chunks:
                    try:
                        if os.path.exists(chunk):
                            os.unlink(chunk)
                    except:
                        pass
                try:
                    if os.path.exists(chunks_dir):
                        os.rmdir(chunks_dir)
                except:
                    pass
                raise

        except Exception as e:
            logger.error(f"Error in stream processing: {e}")
            error_msg = str(e)
            if "too big" in error_msg.lower():
                return False, ["Видео слишком большое для обработки"]
            return False, [f"Ошибка при обработке видео: {error_msg}"]