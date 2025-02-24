import os
import shutil
import uuid
import logging
from typing import List, Tuple
from config import TEMP_DIR

logger = logging.getLogger(__name__)

def get_directory_size(directory: str) -> int:
    """Calculate total size of a directory in bytes."""
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(directory):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total_size += os.path.getsize(fp)
    return total_size

def check_disk_space(directory: str) -> Tuple[bool, str]:
    """Check available disk space and current directory size."""
    try:
        # Ensure directory exists before checking
        os.makedirs(directory, exist_ok=True)

        total, used, free = shutil.disk_usage(directory)
        dir_size = get_directory_size(directory) if os.path.exists(directory) else 0

        # Convert to MB for logging
        total_mb = total / (1024 * 1024)
        used_mb = used / (1024 * 1024)
        free_mb = free / (1024 * 1024)
        dir_size_mb = dir_size / (1024 * 1024)

        logger.info(
            f"Disk space status for {directory}:\n"
            f"Total: {total_mb:.1f}MB\n"
            f"Used: {used_mb:.1f}MB ({used/total*100:.1f}%)\n"
            f"Free: {free_mb:.1f}MB ({free/total*100:.1f}%)\n"
            f"Directory size: {dir_size_mb:.1f}MB"
        )

        return True, ""
    except Exception as e:
        logger.error(f"Error checking disk space: {e}")
        return False, str(e)

def create_temp_dir() -> str:
    """Create a unique temporary directory for processing files."""
    unique_dir = os.path.join(TEMP_DIR, str(uuid.uuid4()))
    os.makedirs(unique_dir, exist_ok=True)
    logger.info(f"Created temporary directory: {unique_dir}")
    return unique_dir

def cleanup_temp_files(directory: str) -> None:
    """Remove temporary files and directories recursively."""
    try:
        logger.info(f"Starting cleanup of directory: {directory}")

        # Log space before cleanup
        check_disk_space(directory)

        if os.path.exists(directory):
            # Remove all files and subdirectories
            for root, dirs, files in os.walk(directory, topdown=False):
                for name in files:
                    try:
                        file_path = os.path.join(root, name)
                        if os.path.exists(file_path):
                            file_size = os.path.getsize(file_path)
                            os.unlink(file_path)
                            logger.info(f"Removed file: {file_path} (size: {file_size/1024/1024:.1f}MB)")
                    except Exception as e:
                        logger.error(f"Error removing file {name}: {e}")

                for name in dirs:
                    try:
                        dir_path = os.path.join(root, name)
                        if os.path.exists(dir_path):
                            dir_size = get_directory_size(dir_path)
                            shutil.rmtree(dir_path)
                            logger.info(f"Removed directory: {dir_path} (size: {dir_size/1024/1024:.1f}MB)")
                    except Exception as e:
                        logger.error(f"Error removing directory {name}: {e}")

            # Recreate the base directory
            if os.path.exists(directory):
                shutil.rmtree(directory)
            os.makedirs(directory, exist_ok=True)
            logger.info(f"Directory {directory} cleaned and recreated")

            # Log space after cleanup
            check_disk_space(directory)
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

def get_video_info(file_path: str) -> dict:
    """Get video metadata."""
    import ffmpeg
    try:
        probe = ffmpeg.probe(file_path)
        video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        return {
            'duration': float(probe['format']['duration']),
            'width': int(video_info['width']),
            'height': int(video_info['height']),
            'format': probe['format']['format_name']
        }
    except Exception as e:
        raise ValueError(f"Failed to get video info: {e}")

def split_list(lst: List, n: int) -> List[List]:
    """Split a list into n-sized chunks while maintaining order."""
    return [lst[i:i + n] for i in range(0, len(lst), n)]