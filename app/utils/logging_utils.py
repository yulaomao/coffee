"""
Structured logging configuration for the Coffee Machine Management System.
Provides comprehensive logging for monitoring, debugging, and auditing.
"""
import logging
import logging.config
import os
import sys
from datetime import datetime
from typing import Dict, Any

# Logging configuration
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        },
        "detailed": {
            "format": "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s"
        },
        "json": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        }
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": sys.stdout
        },
        "file": {
            "level": "DEBUG",
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "detailed",
            "filename": "logs/application.log",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5
        },
        "error_file": {
            "level": "ERROR",
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "detailed",
            "filename": "logs/error.log",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5
        },
        "audit_file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "filename": "logs/audit.log",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 10
        }
    },
    "loggers": {
        "app": {
            "level": "DEBUG",
            "handlers": ["console", "file", "error_file"],
            "propagate": False
        },
        "app.audit": {
            "level": "INFO",
            "handlers": ["audit_file"],
            "propagate": False
        },
        "app.security": {
            "level": "INFO",
            "handlers": ["console", "file", "error_file", "audit_file"],
            "propagate": False
        },
        "sqlalchemy.engine": {
            "level": "WARNING",
            "handlers": ["file"],
            "propagate": False
        },
        "werkzeug": {
            "level": "INFO",
            "handlers": ["file"],
            "propagate": False
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"]
    }
}


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""
    
    def format(self, record):
        import json
        
        # Create structured log entry
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Add exception information if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields if present
        if hasattr(record, 'user_id'):
            log_entry["user_id"] = record.user_id
        if hasattr(record, 'request_id'):
            log_entry["request_id"] = record.request_id
        if hasattr(record, 'ip_address'):
            log_entry["ip_address"] = record.ip_address
        if hasattr(record, 'action'):
            log_entry["action"] = record.action
        if hasattr(record, 'resource'):
            log_entry["resource"] = record.resource
        if hasattr(record, 'result'):
            log_entry["result"] = record.result
        
        return json.dumps(log_entry)


def setup_logging():
    """Initialize logging configuration."""
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Configure logging
    logging.config.dictConfig(LOGGING_CONFIG)
    
    # Get logger for application
    logger = logging.getLogger("app")
    logger.info("Logging system initialized")
    
    return logger


class AuditLogger:
    """Specialized logger for audit events."""
    
    def __init__(self):
        self.logger = logging.getLogger("app.audit")
    
    def log_user_action(
        self,
        user_id: int,
        action: str,
        resource: str,
        result: str,
        details: Dict[str, Any] = None,
        ip_address: str = None,
        request_id: str = None
    ):
        """Log user actions for audit purposes."""
        extra = {
            "user_id": user_id,
            "action": action,
            "resource": resource,
            "result": result,
            "details": details or {}
        }
        
        if ip_address:
            extra["ip_address"] = ip_address
        if request_id:
            extra["request_id"] = request_id
            
        self.logger.info(
            f"User {user_id} performed {action} on {resource}: {result}",
            extra=extra
        )
    
    def log_system_event(
        self,
        event_type: str,
        description: str,
        details: Dict[str, Any] = None,
        severity: str = "info"
    ):
        """Log system events."""
        extra = {
            "event_type": event_type,
            "details": details or {},
            "severity": severity
        }
        
        log_method = getattr(self.logger, severity.lower(), self.logger.info)
        log_method(f"System event - {event_type}: {description}", extra=extra)
    
    def log_security_event(
        self,
        event_type: str,
        user_id: int = None,
        ip_address: str = None,
        description: str = "",
        details: Dict[str, Any] = None
    ):
        """Log security-related events."""
        security_logger = logging.getLogger("app.security")
        
        extra = {
            "event_type": event_type,
            "details": details or {}
        }
        
        if user_id:
            extra["user_id"] = user_id
        if ip_address:
            extra["ip_address"] = ip_address
            
        security_logger.warning(
            f"Security event - {event_type}: {description}",
            extra=extra
        )


class PerformanceLogger:
    """Logger for performance monitoring."""
    
    def __init__(self):
        self.logger = logging.getLogger("app.performance")
    
    def log_request_timing(
        self,
        endpoint: str,
        method: str,
        duration_ms: float,
        status_code: int,
        user_id: int = None,
        request_id: str = None
    ):
        """Log API request performance."""
        extra = {
            "endpoint": endpoint,
            "method": method,
            "duration_ms": duration_ms,
            "status_code": status_code
        }
        
        if user_id:
            extra["user_id"] = user_id
        if request_id:
            extra["request_id"] = request_id
        
        # Determine log level based on performance
        if duration_ms > 5000:  # > 5 seconds
            log_level = "warning"
        elif duration_ms > 2000:  # > 2 seconds
            log_level = "info"
        else:
            log_level = "debug"
            
        log_method = getattr(self.logger, log_level)
        log_method(
            f"{method} {endpoint} completed in {duration_ms:.2f}ms (status: {status_code})",
            extra=extra
        )
    
    def log_database_query_timing(
        self,
        query_type: str,
        table_name: str,
        duration_ms: float,
        query_hash: str = None
    ):
        """Log database query performance."""
        extra = {
            "query_type": query_type,
            "table_name": table_name,
            "duration_ms": duration_ms
        }
        
        if query_hash:
            extra["query_hash"] = query_hash
        
        if duration_ms > 1000:  # > 1 second
            log_level = "warning"
        elif duration_ms > 500:  # > 500ms
            log_level = "info"
        else:
            log_level = "debug"
            
        log_method = getattr(self.logger, log_level)
        log_method(
            f"Database query - {query_type} on {table_name} took {duration_ms:.2f}ms",
            extra=extra
        )


# Global instances
audit_logger = AuditLogger()
performance_logger = PerformanceLogger()


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the specified name."""
    return logging.getLogger(f"app.{name}")


# Initialize logging when module is imported
if not logging.getLogger("app").handlers:
    setup_logging()