import os
import sys
import logging
import subprocess
import requests
import time
import urllib.request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_local_server():
    """Check if local server is running and responsive"""
    try:
        response = requests.get("http://localhost:8081/")
        logger.info(f"Server check response: {response.status_code}")
        logger.info(f"Server response content: {response.text[:200]}")  # Log first 200 chars of response
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Error checking server: {e}")
        return False

def main():
    # Create necessary directories
    os.makedirs("tdlib-db", exist_ok=True)
    os.makedirs("tdlib-db/temp", exist_ok=True)
    logger.info("Created TDLib directories")

    # Check if telegram-bot-api binary exists
    if not os.path.exists("./telegram-bot-api"):
        logger.info("Downloading telegram-bot-api...")
        try:
            # Try different URLs for the binary
            urls = [
                "https://github.com/tdlib/telegram-bot-api/releases/download/v7.0/telegram-bot-api-linux-amd64",
                "https://github.com/tdlib/telegram-bot-api/releases/latest/download/telegram-bot-api-linux-amd64"
            ]

            success = False
            for url in urls:
                try:
                    logger.info(f"Trying to download from: {url}")
                    urllib.request.urlretrieve(url, "telegram-bot-api")
                    os.chmod("telegram-bot-api", 0o755)
                    logger.info("Successfully downloaded and set permissions for telegram-bot-api")
                    success = True
                    break
                except Exception as e:
                    logger.warning(f"Failed to download from {url}: {e}")
                    continue

            if not success:
                raise Exception("Failed to download telegram-bot-api from all available sources")

        except Exception as e:
            logger.error(f"Failed to download telegram-bot-api: {e}")
            sys.exit(1)

    # Configure the server with optimized settings
    logger.info("Starting local Telegram Bot API server...")
    try:
        command = [
            "./telegram-bot-api",
            "--local",
            "--dir=tdlib-db",
            "--temp-dir=tdlib-db/temp",
            "--filter-timeout=60",
            "--max-webhook-connections=100",
            "--max-connections=100",
            "--verbosity=3",  # Increased verbosity for debugging
            "--max-upload-file-size=2000000000"  # 2GB file size limit
        ]

        logger.info(f"Starting server with command: {' '.join(command)}")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        # Wait for server to start
        for attempt in range(30):  # Wait up to 30 seconds
            if check_local_server():
                logger.info("Local server started successfully!")

                # Additional verification
                try:
                    test_url = "http://localhost:8081/test"
                    test_response = requests.get(test_url)
                    logger.info(f"Test endpoint response: {test_response.status_code}")
                except Exception as e:
                    logger.warning(f"Test endpoint check failed: {e}")

                # Check process status and logs
                stdout, stderr = process.communicate()
                logger.info(f"Server stdout: {stdout}")
                if stderr:
                    logger.warning(f"Server stderr: {stderr}")

                return

            # Check process status
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                logger.error("Server process terminated!")
                logger.error(f"STDOUT: {stdout}")
                logger.error(f"STDERR: {stderr}")
                sys.exit(1)

            logger.info(f"Waiting for server to start (attempt {attempt + 1}/30)...")
            time.sleep(1)

        logger.error("Server failed to start within timeout")
        process.kill()
        sys.exit(1)

    except Exception as e:
        logger.error(f"Failed to start local server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()