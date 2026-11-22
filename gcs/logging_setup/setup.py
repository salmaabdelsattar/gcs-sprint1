"""Logging setup: levels, rotating file, and console output."""
import logging
import logging.handlers
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def setup_logging(settings):
    """Configure the root logger from the settings dict."""
    level = getattr(logging, str(settings["log_level"]).upper(), logging.INFO)
    log_path = Path(settings["log_file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()  # avoid duplicate handlers if called twice
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return root
