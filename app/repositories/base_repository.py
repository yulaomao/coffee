"""
Base Repository class providing common CRUD operations.
Implements the Repository pattern for data access abstraction.
"""
from typing import TypeVar, Generic, Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_
from ..extensions import db

T = TypeVar('T')


class BaseRepository(Generic[T]):
    """Base repository providing common data operations."""
    
    def __init__(self, model_class: type[T], session: Optional[Session] = None):
        self.model_class = model_class
        self.session = session or db.session
    
    def create(self, **kwargs) -> T:
        """Create a new entity."""
        entity = self.model_class(**kwargs)
        self.session.add(entity)
        return entity
    
    def get_by_id(self, entity_id: int) -> Optional[T]:
        """Get entity by ID."""
        return self.session.query(self.model_class).get(entity_id)
    
    def get_by_ids(self, entity_ids: List[int]) -> List[T]:
        """Get entities by list of IDs."""
        return self.session.query(self.model_class).filter(
            self.model_class.id.in_(entity_ids)
        ).all()
    
    def get_all(self, limit: Optional[int] = None, offset: int = 0) -> List[T]:
        """Get all entities with optional pagination."""
        query = self.session.query(self.model_class)
        if offset:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)
        return query.all()
    
    def find_by(self, **kwargs) -> List[T]:
        """Find entities by arbitrary criteria."""
        query = self.session.query(self.model_class)
        for key, value in kwargs.items():
            if hasattr(self.model_class, key):
                if value is None:
                    query = query.filter(getattr(self.model_class, key).is_(None))
                else:
                    query = query.filter(getattr(self.model_class, key) == value)
        return query.all()
    
    def find_one_by(self, **kwargs) -> Optional[T]:
        """Find single entity by criteria."""
        results = self.find_by(**kwargs)
        return results[0] if results else None
    
    def update(self, entity: T, **kwargs) -> T:
        """Update entity with new values."""
        for key, value in kwargs.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        return entity
    
    def delete(self, entity: T) -> None:
        """Delete entity."""
        self.session.delete(entity)
    
    def delete_by_id(self, entity_id: int) -> bool:
        """Delete entity by ID. Returns True if deleted, False if not found."""
        entity = self.get_by_id(entity_id)
        if entity:
            self.delete(entity)
            return True
        return False
    
    def count(self, **kwargs) -> int:
        """Count entities matching criteria."""
        query = self.session.query(self.model_class)
        for key, value in kwargs.items():
            if hasattr(self.model_class, key):
                if value is None:
                    query = query.filter(getattr(self.model_class, key).is_(None))
                else:
                    query = query.filter(getattr(self.model_class, key) == value)
        return query.count()
    
    def exists(self, **kwargs) -> bool:
        """Check if entity exists with given criteria."""
        return self.count(**kwargs) > 0
    
    def commit(self) -> None:
        """Commit current session."""
        self.session.commit()
    
    def rollback(self) -> None:
        """Rollback current session."""
        self.session.rollback()
    
    def flush(self) -> None:
        """Flush current session."""
        self.session.flush()