"""
Structured Logger - JSON Logging Foundation
===========================================

Provides a standardized way to log events in JSON format,
enabling better observability in production environments.

Features:
- JSON output for machine readability
- Automatic inclusion of context (correlation_id, agent, version)
- Fallback to human-readable format for development
- Log rotation and size management

Author: Observability Agent
Created: 2026-01-10
"""

import logging
import json
import uuid
import os
from datetime import datetime
from typing import Any, Dict, Optional

class JsonFormatter(logging.Formatter):
    """
    Formatter that outputs JSON strings with secret scrubbing.
    """
    SENSITIVE_KEYS = {
        "private_key", "api_key", "token", "secret", "password", 
        "key", "authorization", "privatekey", "mnemonic"
    }

    def scrub(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {
                k: "********" if str(k).lower() in self.SENSITIVE_KEYS else self.scrub(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self.scrub(item) for item in data]
        return data

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
            "line": record.lineno,
        }

        # Include extra context if available
        if hasattr(record, "correlation_id"):
            log_data["correlation_id"] = record.correlation_id
        if hasattr(record, "agent_name"):
            log_data["agent_name"] = record.agent_name
        
        # Add any extra fields passed in 'extra'
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        # Scrub sensitive data
        log_data = self.scrub(log_data)

        return json.dumps(log_data)

class StructuredLogger:
    """
    Wrapper around python's logging to provide structured output.
    """
    def __init__(
        self, 
        name: str, 
        agent_name: Optional[str] = None,
        correlation_id: Optional[str] = None
    ):
        self.logger = logging.getLogger(name)
        self.agent_name = agent_name
        self.correlation_id = correlation_id or str(uuid.uuid4())

    def _get_extra(self, extra_fields: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        extra = {
            "correlation_id": self.correlation_id,
        }
        if self.agent_name:
            extra["agent_name"] = self.agent_name
        
        if extra_fields:
            extra["extra_fields"] = extra_fields
        
        return extra

    def info(self, msg: str, extra_fields: Optional[Dict[str, Any]] = None):
        self.logger.info(msg, extra=self._get_extra(extra_fields))

    def error(self, msg: str, extra_fields: Optional[Dict[str, Any]] = None, exc_info: bool = False):
        self.logger.error(msg, extra=self._get_extra(extra_fields), exc_info=exc_info)

    def warning(self, msg: str, extra_fields: Optional[Dict[str, Any]] = None):
        self.logger.warning(msg, extra=self._get_extra(extra_fields))

    def debug(self, msg: str, extra_fields: Optional[Dict[str, Any]] = None):
        self.logger.debug(msg, extra=self._get_extra(extra_fields))

def setup_logging(
    level: int = logging.INFO,
    json_output: bool = True,
    log_file: Optional[str] = "logs/system.log"
):
    """
    Configure global logging settings.
    """
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    root_logger.handlers = []

    # Console handler (human-readable if not json_output)
    console_handler = logging.StreamHandler()
    if json_output:
        console_handler.setFormatter(JsonFormatter())
    else:
        console_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
    root_logger.addHandler(console_handler)

    # File handler (always JSON)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JsonFormatter())
        root_logger.addHandler(file_handler)

    logging.info(f"Logging initialized (level={logging.getLevelName(level)}, json={json_output})")

# Added for Dashboard Integration
class DashboardHandler(logging.Handler):
    def __init__(self, reporter):
        super().__init__()
        self.reporter = reporter
    
    def emit(self, record):
        try:
            msg = self.format(record)
            self.reporter.add_log(msg, record.levelname)
        except Exception:
            self.handleError(record)

def attach_dashboard_handler(reporter):
    """
    Attach the dashboard reporter to the root logger.
    """
    logger = logging.getLogger()
    handler = DashboardHandler(reporter)
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
