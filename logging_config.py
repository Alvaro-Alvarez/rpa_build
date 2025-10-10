import logging
from pathlib import Path

LOG_FILE_NAME = "rpa_build.log"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging() -> logging.Logger:
    """
    Configure the root logger to write all records into the project log file.

    The configuration is applied only once. Subsequent calls simply return
    the already configured root logger.
    """
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return root_logger

    log_path = Path(__file__).resolve().parent / LOG_FILE_NAME
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    logging.captureWarnings(True)

    return root_logger
