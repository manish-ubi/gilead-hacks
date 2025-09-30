import logging
import os

# ANSI color codes
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
BLUE = "\033[34m"
YELLOW = "\033[33m"
CYAN = "\033[36m"


class ColorFormatter(logging.Formatter):
	LEVEL_TO_COLOR = {
		logging.DEBUG: CYAN,
		logging.INFO: GREEN,
		logging.WARNING: YELLOW,
		logging.ERROR: RED,
		logging.CRITICAL: RED,
	}

	def format(self, record: logging.LogRecord) -> str:
		color = self.LEVEL_TO_COLOR.get(record.levelno, RESET)
		prefix = f"{color}{record.levelname}{RESET}"
		msg = super().format(record)
		return f"{prefix} {msg}"


def get_logger(name: str = "app", level: str | int = None) -> logging.Logger:
	logger = logging.getLogger(name)
	if logger.handlers:
		return logger
	log_level = level if level is not None else os.getenv("LOG_LEVEL", "INFO").upper()
	logger.setLevel(log_level)
	h = logging.StreamHandler()
	h.setLevel(log_level)
	fmt = ColorFormatter("%(asctime)s %(name)s - %(message)s", "%Y-%m-%d %H:%M:%S")
	h.setFormatter(fmt)
	logger.addHandler(h)
	logger.propagate = False
	return logger


# Convenience functions
log = get_logger("agentic_qa")


def info(msg: str):
	log.info(msg)


def debug(msg: str):
	log.debug(msg)


def warn(msg: str):
	log.warning(msg)


def error(msg: str):
	log.error(msg)
