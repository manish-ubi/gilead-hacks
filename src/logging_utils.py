import logging
import os
import json
import time
from typing import Any, Dict, Optional
from datetime import datetime

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


class PipelineLogger:
	"""Enhanced logger for pipeline operations with structured logging."""
	
	def __init__(self, component: str = "pipeline"):
		self.component = component
		self.logger = get_logger(f"{component}_logger")
		self.start_time = None
		self.operation_id = None
	
	def start_operation(self, operation: str, operation_id: Optional[str] = None) -> str:
		"""Start logging an operation."""
		self.operation_id = operation_id or f"{operation}_{int(time.time())}"
		self.start_time = time.time()
		self.logger.info(f"Starting {operation} [ID: {self.operation_id}]")
		return self.operation_id
	
	def log_step(self, step: str, details: Optional[Dict[str, Any]] = None):
		"""Log a step in the operation."""
		elapsed = time.time() - self.start_time if self.start_time else 0
		message = f"Step: {step} [Elapsed: {elapsed:.2f}s]"
		if details:
			message += f" | Details: {json.dumps(details)}"
		self.logger.info(message)
	
	def log_indexing(self, file_count: int, total_size: int, file_types: Dict[str, int]):
		"""Log indexing operation details."""
		details = {
			"file_count": file_count,
			"total_size_mb": round(total_size / (1024 * 1024), 2),
			"file_types": file_types
		}
		self.log_step("Indexing completed", details)
	
	def log_query(self, query: str, response_length: int, cached: bool, response_time: float):
		"""Log query operation details."""
		details = {
			"query_length": len(query),
			"response_length": response_length,
			"cached": cached,
			"response_time_ms": round(response_time * 1000, 2)
		}
		self.log_step("Query processed", details)
	
	def log_sql_generation(self, question: str, sql_query: str, validation_result: bool):
		"""Log SQL generation details."""
		details = {
			"question_length": len(question),
			"sql_length": len(sql_query),
			"validation_passed": validation_result
		}
		self.log_step("SQL generated", details)
	
	def log_feedback(self, feedback_type: str, query_hash: str, user_id: Optional[str] = None):
		"""Log user feedback."""
		details = {
			"feedback_type": feedback_type,
			"query_hash": query_hash[:8] + "...",
			"user_id": user_id or "anonymous"
		}
		self.log_step("Feedback recorded", details)
	
	def end_operation(self, success: bool = True, error_msg: Optional[str] = None):
		"""End the operation logging."""
		total_time = time.time() - self.start_time if self.start_time else 0
		status = "SUCCESS" if success else "FAILED"
		message = f"Completed {self.component} operation [ID: {self.operation_id}] - {status} [Total: {total_time:.2f}s]"
		
		if error_msg:
			message += f" | Error: {error_msg}"
		
		if success:
			self.logger.info(message)
		else:
			self.logger.error(message)
	
	def log_cache_operation(self, operation: str, entries_affected: int):
		"""Log cache operations."""
		details = {
			"operation": operation,
			"entries_affected": entries_affected
		}
		self.log_step("Cache operation", details)
	
	def log_csv_loading(self, files_loaded: int, tables_created: int, errors: int):
		"""Log CSV loading operation."""
		details = {
			"files_loaded": files_loaded,
			"tables_created": tables_created,
			"errors": errors
		}
		self.log_step("CSV loading completed", details)


# Global pipeline logger instance
pipeline_logger = PipelineLogger("main")
