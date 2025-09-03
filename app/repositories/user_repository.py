"""
User Repository implementation with user-specific operations.
"""
from typing import List, Optional, Dict, Any
from sqlalchemy import and_, desc, func
from .base_repository import BaseRepository
from ..models import User, Role, Merchant


class UserRepository(BaseRepository[User]):
    """Repository for User-specific operations."""
    
    def __init__(self):
        from ..models import User
        super().__init__(User)
    
    def find_by_username(self, username: str) -> Optional[User]:
        """Find user by username."""
        return self.find_one_by(username=username)
    
    def find_by_email(self, email: str) -> Optional[User]:
        """Find user by email."""
        return self.find_one_by(email=email)
    
    def find_by_role(self, role: str) -> List[User]:
        """Find users by role."""
        return self.find_by(role=role, is_active=True)
    
    def find_by_merchant(self, merchant_id: int) -> List[User]:
        """Find all users for a merchant."""
        return self.find_by(merchant_id=merchant_id, is_active=True)
    
    def find_active_users(self) -> List[User]:
        """Find all active users."""
        return self.find_by(is_active=True)
    
    def authenticate(self, username: str, password: str) -> Optional[User]:
        """Authenticate user by username and password."""
        user = self.find_by_username(username)
        if user and user.is_active and user.check_password(password):
            return user
        return None
    
    def create_user(
        self, 
        username: str, 
        email: str, 
        password: str,
        role: str = 'viewer',
        merchant_id: Optional[int] = None,
        **kwargs
    ) -> User:
        """Create a new user with hashed password."""
        user = self.create(
            username=username,
            email=email,
            role=role,
            merchant_id=merchant_id,
            **kwargs
        )
        user.set_password(password)
        return user
    
    def update_password(self, user: User, new_password: str) -> User:
        """Update user password."""
        user.set_password(new_password)
        return user
    
    def deactivate_user(self, user_id: int) -> bool:
        """Deactivate user instead of deleting."""
        user = self.get_by_id(user_id)
        if user:
            self.update(user, is_active=False)
            return True
        return False
    
    def get_user_statistics(self) -> Dict[str, Any]:
        """Get user statistics by role and status."""
        stats = (
            self.session.query(
                User.role,
                User.is_active,
                func.count(User.id).label('count')
            )
            .group_by(User.role, User.is_active)
            .all()
        )
        
        result = {
            'total': 0,
            'active': 0,
            'inactive': 0,
            'by_role': {}
        }
        
        for stat in stats:
            result['total'] += stat.count
            
            if stat.is_active:
                result['active'] += stat.count
            else:
                result['inactive'] += stat.count
            
            role_key = stat.role
            if role_key not in result['by_role']:
                result['by_role'][role_key] = {'active': 0, 'inactive': 0}
            
            if stat.is_active:
                result['by_role'][role_key]['active'] = stat.count
            else:
                result['by_role'][role_key]['inactive'] = stat.count
        
        return result