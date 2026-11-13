"""Console and daily, per-process files (safe with Windows spawn)."""
import logging
import os
import re
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


class RedactStreams(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        message = re.sub(r"rtsps?://[^\s\"'<>]+", "rtsp://[redacted]", message, flags=re.I)
        message = re.sub(r"(https?://)[^/\s@]+@", r"\1[redacted]@", message, flags=re.I)
        record.msg, record.args = message, ()
        return True


def setup_logger(name="camera_ai", log_level=None, service_name=None, log_dir=None):
    logger = logging.getLogger(name)
    logger.setLevel((log_level or os.getenv("LOG_LEVEL", "INFO")).upper())
    logger.propagate = False
    if not logger.handlers:
        directory = Path(log_dir or os.getenv("LOG_DIR", "logs"))
        directory.mkdir(parents=True, exist_ok=True)
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s pid=%(process)d thread=%(threadName)s %(name)s %(message)s")
        console = logging.StreamHandler(sys.stdout)
        file_handler = TimedRotatingFileHandler(
            directory / f"{service_name or 'ai'}_{os.getpid()}.log",
            when="midnight", backupCount=30, encoding="utf-8")
        for handler in (console, file_handler):
            handler.setFormatter(formatter)
            handler.addFilter(RedactStreams())
            logger.addHandler(handler)
    return logger


def get_logger(name="camera_ai"):
    logger = logging.getLogger(name)
    return logger if logger.handlers else setup_logger(name)
