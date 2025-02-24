import os
import logging
import asyncio
from typing import List, Tuple, Callable
import cv2
from scenedetect import detect, ContentDetector, split_video_ffmpeg
from config import MIN_SCENE_LENGTH, THRESHOLD, MAX_VIDEO_SIZE, SUPPORTED_VIDEO_FORMATS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VideoProcessor:
    @staticmethod
    def validate_video(file_path: str) -> Tuple[bool, str]:
        """Validate if the file is a valid video."""
        try:
            logger.info(f"Начинаем проверку видеофайла: {file_path}")

            if not os.path.isfile(file_path):
                return False, "Видеофайл не существует"

            if not os.access(file_path, os.R_OK):
                return False, "Нет доступа к видеофайлу"

            _, ext = os.path.splitext(file_path)
            if ext.lower() not in SUPPORTED_VIDEO_FORMATS:
                error_msg = f"Неподдерживаемый формат видео. Поддерживаемые форматы: {', '.join(SUPPORTED_VIDEO_FORMATS)}"
                logger.error(error_msg)
                return False, error_msg

            file_size = os.path.getsize(file_path)
            if file_size > MAX_VIDEO_SIZE:
                error_msg = f"Видеофайл слишком большой. Максимальный размер: {MAX_VIDEO_SIZE/(1024*1024)}МБ"
                logger.error(error_msg)
                return False, error_msg

            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                logger.error("Не удалось открыть видеофайл")
                return False, "Некорректный видеофайл"

            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count/fps if fps > 0 else 0

            logger.info(f"Параметры видео: FPS={fps}, Кадров={frame_count}, Длительность={duration:.2f}с")

            if fps <= 0 or frame_count <= 0:
                logger.error("Обнаружены некорректные параметры видео")
                return False, "Некорректный видеофайл: не удалось определить длительность"

            if duration < MIN_SCENE_LENGTH:
                logger.error(f"Видео слишком короткое: {duration:.2f}с < {MIN_SCENE_LENGTH}с")
                return False, f"Видео слишком короткое. Минимальная длительность: {MIN_SCENE_LENGTH} секунд"

            cap.release()
            logger.info("Проверка видео успешно завершена")
            return True, ""

        except Exception as e:
            logger.error(f"Ошибка при проверке видео: {str(e)}")
            return False, f"Ошибка при проверке видео: {str(e)}"

    @staticmethod
    def rename_scenes(output_dir: str) -> List[str]:
        """Rename scene files to have sequential numbers."""
        try:
            # Get all scene files
            scene_files = [
                f for f in os.listdir(output_dir)
                if f.endswith('.mp4')
            ]
            scene_files.sort()  # Sort to ensure correct order

            renamed_files = []
            for i, old_name in enumerate(scene_files, 1):
                old_path = os.path.join(output_dir, old_name)
                new_name = f'scene-{i:03d}.mp4'  # Use 3 digits padding for better sorting
                new_path = os.path.join(output_dir, new_name)

                os.rename(old_path, new_path)
                renamed_files.append(new_path)
                logger.info(f"Переименован файл {old_name} в {new_name}")

            return renamed_files

        except Exception as e:
            logger.error(f"Ошибка при переименовании сцен: {str(e)}")
            return []

    @staticmethod
    async def detect_and_split_scenes(
        video_path: str, 
        output_dir: str,
        progress_callback: Callable[[int], None] = None
    ) -> Tuple[bool, List[str]]:
        """Detect and split video into scenes using PySceneDetect."""
        try:
            logger.info(f"Начинаем определение сцен для видео: {video_path}")
            logger.info(f"Директория для сохранения: {output_dir}")

            video_path = os.path.abspath(video_path)
            output_dir = os.path.abspath(output_dir)

            if progress_callback:
                await progress_callback(5)  # Initial progress

            os.makedirs(output_dir, exist_ok=True)

            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise ValueError("Не удалось открыть видеофайл")

            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = frame_count / fps if fps > 0 else 0
            cap.release()

            logger.info(f"Параметры видео: FPS={fps}, Кадров={frame_count}, Разрешение={width}x{height}, Длительность={duration:.2f}с")
            logger.info(f"Параметры определения сцен: порог={THRESHOLD}, мин_длина_сцены={MIN_SCENE_LENGTH}с")

            if progress_callback:
                await progress_callback(20)  # Progress after initial setup

            # Устанавливаем таймаут для определения сцен
            try:
                async with asyncio.timeout(300):  # 5 минут на определение сцен
                    scenes = detect(video_path, ContentDetector(
                        threshold=THRESHOLD,
                        min_scene_len=int(MIN_SCENE_LENGTH * fps)
                    ))

                    if not scenes:
                        logger.warning("Сцены не обнаружены")
                        return False, ["Значительных изменений сцен не обнаружено. Попробуйте настроить порог определения или использовать видео с более явными переходами между сценами."]

                    logger.info(f"Найдено {len(scenes)} сцен")
                    for i, scene in enumerate(scenes, 1):
                        start_time = scene[0].get_seconds()
                        end_time = scene[1].get_seconds()
                        logger.info(f"Сцена {i}: Начало={start_time:.2f}с, Конец={end_time:.2f}с")

            except asyncio.TimeoutError:
                logger.error("Превышено время определения сцен")
                return False, ["Превышено время определения сцен. Попробуйте видео меньшей длительности."]

            if progress_callback:
                await progress_callback(50)  # Progress after scene detection

            # Разделение видео на сцены с высоким качеством и таймаутом
            logger.info("Разделение видео на сцены...")
            try:
                async with asyncio.timeout(300):  # 5 минут на разделение
                    split_video_ffmpeg(
                        video_path, 
                        scenes, 
                        output_dir,
                        suppress_output=True,
                        arg_override="-c:v copy -c:a copy"  # Сохраняем оригинальное качество
                    )
            except asyncio.TimeoutError:
                logger.error("Превышено время разделения видео на сцены")
                return False, ["Превышено время разделения видео на сцены. Попробуйте видео меньшей длительности."]

            if progress_callback:
                await progress_callback(80)  # Progress after splitting

            # Переименовываем сцены для правильного порядка
            scene_files = VideoProcessor.rename_scenes(output_dir)

            if not scene_files:
                logger.error("После разделения не создано ни одного файла сцены")
                raise ValueError("Не удалось создать файлы сцен - проверьте формат видео и совместимость кодеков")

            if progress_callback:
                await progress_callback(100)  # Final progress

            logger.info(f"Успешно создано {len(scene_files)} файлов сцен")
            return True, sorted(scene_files)

        except Exception as e:
            logger.exception(f"Ошибка при обработке сцен: {str(e)}")
            return False, [f"Ошибка при обработке видео: {str(e)}"]