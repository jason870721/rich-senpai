from dotenv import load_dotenv

load_dotenv()

# Configure logging before any project module imports — child loggers
# (`rich_senpai.*`) created during import will then inherit the level
# and FileHandler set up here.
from core.logging_setup import setup_logging

LOG_PATH = setup_logging()

from session_tui.tui import main


if __name__ == "__main__":
    main()
