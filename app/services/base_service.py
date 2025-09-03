"""
Base Service class providing common business operations.
"""

from typing import Optional

from sqlalchemy.orm import Session

from ..extensions import db


class BaseService:
    """Base service providing common business operations."""

    def __init__(self, session: Optional[Session] = None):
        self.session = session or db.session

    def commit(self) -> None:
        """Commit current session."""
        self.session.commit()

    def rollback(self) -> None:
        """Rollback current session."""
        self.session.rollback()

    def flush(self) -> None:
        """Flush current session."""
        self.session.flush()

    def close(self) -> None:
        """Close current session."""
        self.session.close()
