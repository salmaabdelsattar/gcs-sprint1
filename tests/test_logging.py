import logging
import logging.handlers

from gcs.logging_setup import setup_logging


def test_setup_creates_rotating_file_and_console(tmp_path):
    settings = {"log_level": "DEBUG", "log_file": str(tmp_path / "logs" / "t.log")}
    root = setup_logging(settings)
    kinds = {type(h) for h in root.handlers}
    assert logging.handlers.RotatingFileHandler in kinds
    assert logging.StreamHandler in kinds
    logging.getLogger("x").info("hello")
    assert (tmp_path / "logs" / "t.log").exists()