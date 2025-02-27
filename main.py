import logging
from bot import SceneDetectionBot

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

def main():
    """Initialize and run the bot"""
    logger.info("Starting bot...")
    bot = SceneDetectionBot()
    bot.run()

if __name__ == "__main__":
    main()