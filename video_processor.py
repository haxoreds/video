import os
import logging
import asyncio
import psutil
from typing import List, Tuple, Callable
import cv2
from scenedetect import detect, ContentDetector, split_video_ffmpeg
from config import MIN_SCENE_LENGTH, THRESHOLD, TELEGRAM_MAX_FILE_SIZE, SUPPORTED_VIDEO_FORMATS

# Configure logging
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

            process = psutil.Process()
            initial_memory = process.memory_info().rss / 1024 / 1024
            logger.info(f"Initial memory usage: {initial_memory:.1f}MB")

            if progress_callback:
                await progress_callback(5, "Reading video metadata")
                logger.info("Progress: 5% - Starting video processing")

            video_path = os.path.abspath(video_path)
            output_dir = os.path.abspath(output_dir)
            os.makedirs(output_dir, exist_ok=True)

            # Get video information with memory cleanup
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise ValueError("Could not open video file")

            # Get basic video info
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = frame_count/fps if fps > 0 else 0
            cap.release()  # Release immediately after getting info

            logger.info(f"Video info: FPS={fps}, Frames={frame_count}, Resolution={width}x{height}, Duration={duration:.2f}s")
            logger.info(f"Scene detection parameters: threshold={THRESHOLD}, min_scene_length={MIN_SCENE_LENGTH}s")

            if progress_callback:
                await progress_callback(10, "Initializing scene detection")
                logger.info("Progress: 10% - Video info collected")

            # Run detection with progress updates
            logger.info("Starting scene detection...")

            # Monitor memory before detection
            pre_detect_memory = process.memory_info().rss / 1024 / 1024
            logger.info(f"Memory usage before detection: {pre_detect_memory:.1f}MB")

            if progress_callback:
                await progress_callback(15, "Starting scene detection")
                logger.info("Progress: 15% - Beginning scene detection")

            # Use memory-efficient detector settings
            detector = ContentDetector(
                threshold=THRESHOLD,
                min_scene_len=int(MIN_SCENE_LENGTH * fps),
                luma_only=True  # Use only luminance for detection, reduces memory usage
            )

            # Run detection
            scenes = detect(video_path, detector)

            # Monitor memory after detection
            post_detect_memory = process.memory_info().rss / 1024 / 1024
            logger.info(f"Memory usage after detection: {post_detect_memory:.1f}MB")
            logger.info(f"Memory increase during detection: {post_detect_memory - pre_detect_memory:.1f}MB")

            if not scenes:
                logger.warning("No scenes detected")
                return False, ["No significant scene changes detected. Try adjusting the threshold or use a video with more distinct scene transitions."]

            logger.info(f"Found {len(scenes)} scenes")
            total_scenes = len(scenes)

            # Process detected scenes with progress updates
            for i, scene in enumerate(scenes, 1):
                start_time = scene[0].get_seconds()
                end_time = scene[1].get_seconds()
                logger.info(f"Scene {i}/{total_scenes}: Start={start_time:.2f}s, End={end_time:.2f}s")

                # Calculate progress between 15% and 40% based on scene analysis
                if progress_callback:
                    scene_progress = 15 + int((i / total_scenes) * 25)  # Progress from 15% to 40%
                    await progress_callback(scene_progress, f"Analyzing scene {i}/{total_scenes}")
                    logger.info(f"Progress: {scene_progress}% - Analyzing scene {i}/{total_scenes}")

            if progress_callback:
                await progress_callback(40, "Scene detection completed")
                logger.info("Progress: 40% - Scene detection completed")

            # Video splitting with detailed progress tracking
            logger.info("Starting video splitting with detailed progress...")
            try:
                async with asyncio.timeout(600):  # 10 minutes timeout
                    logger.info("Running FFmpeg for video splitting...")

                    # Pre-splitting memory check
                    pre_split_memory = process.memory_info().rss / 1024 / 1024
                    logger.info(f"Memory usage before splitting: {pre_split_memory:.1f}MB")

                    split_video_ffmpeg(
                        video_path, 
                        scenes, 
                        output_dir,
                        suppress_output=False,  # Enable output for debugging
                        arg_override="-c:v copy -c:a copy -v info"  # Copy streams without re-encoding, maintain quality
                    )

                    # Post-splitting memory check
                    post_split_memory = process.memory_info().rss / 1024 / 1024
                    logger.info(f"Memory usage after splitting: {post_split_memory:.1f}MB")
                    logger.info(f"Memory change during splitting: {post_split_memory - pre_split_memory:.1f}MB")

                    logger.info("FFmpeg video splitting completed")

                    # Update progress during video splitting
                    total_scenes = len(scenes)
                    for i, scene in enumerate(scenes, 1):
                        if progress_callback:
                            split_progress = 40 + int((i / total_scenes) * 40)  # Progress from 40% to 80%
                            await progress_callback(split_progress, f"Splitting scene {i}/{total_scenes}")
                            logger.info(f"Progress: {split_progress}% - Splitting scene {i}/{total_scenes}")

                            # Verify scene file immediately after splitting
                            scene_file = os.path.join(output_dir, f"scene-{i:03d}.mp4")
                            if os.path.exists(scene_file):
                                scene_size = os.path.getsize(scene_file) / (1024 * 1024)  # Size in MB
                                logger.info(f"Created scene file: {scene_file} (Size: {scene_size:.1f}MB)")
                            else:
                                logger.warning(f"Scene file not found: {scene_file}")

            except asyncio.TimeoutError:
                logger.error("Video splitting timed out")
                return False, ["Video splitting timed out. Try a shorter video or wait longer."]

            if progress_callback:
                await progress_callback(80, "Processing split scenes")
                logger.info("Progress: 80% - Video splitting completed")

            # Rename and verify scenes
            scene_files = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
            logger.info(f"Found {len(scene_files)} output files before renaming")

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
                return False, ["Failed to create scene files - check video format and codec compatibility"]

            # Log final memory usage
            final_memory = process.memory_info().rss / 1024 / 1024
            logger.info(f"Final memory usage: {final_memory:.1f}MB")
            logger.info(f"Total memory change: {final_memory - initial_memory:.1f}MB")

            if progress_callback:
                await progress_callback(100, "Processing completed")
                logger.info("Progress: 100% - All processing completed")

            logger.info(f"Successfully created {len(renamed_files)} scene files")
            return True, sorted(renamed_files)

        except Exception as e:
            logger.exception(f"Error processing scenes: {str(e)}")
            return False, [f"Error processing video: {str(e)}"]

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