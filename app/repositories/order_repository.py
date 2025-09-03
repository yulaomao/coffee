"""
Order Repository implementation with order-specific operations.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import and_, desc, func, between
from .base_repository import BaseRepository
from ..models import Order, Device, Product


class OrderRepository(BaseRepository[Order]):
    """Repository for Order-specific operations."""
    
    def __init__(self):
        from ..models import Order
        super().__init__(Order)
    
    def find_by_device(self, device_id: int, limit: Optional[int] = None) -> List[Order]:
        """Find orders for a specific device."""
        query = self.session.query(Order).filter(Order.device_id == device_id).order_by(desc(Order.created_at))
        if limit:
            query = query.limit(limit)
        return query.all()
    
    def find_by_merchant(self, merchant_id: int, limit: Optional[int] = None) -> List[Order]:
        """Find orders for a merchant through their devices."""
        query = (
            self.session.query(Order)
            .join(Device, Order.device_id == Device.id)
            .filter(Device.merchant_id == merchant_id)
            .order_by(desc(Order.created_at))
        )
        if limit:
            query = query.limit(limit)
        return query.all()
    
    def find_by_date_range(
        self, 
        start_date: datetime, 
        end_date: datetime, 
        device_id: Optional[int] = None,
        merchant_id: Optional[int] = None
    ) -> List[Order]:
        """Find orders within a date range."""
        query = self.session.query(Order).filter(
            between(Order.created_at, start_date, end_date)
        )
        
        if device_id:
            query = query.filter(Order.device_id == device_id)
        elif merchant_id:
            query = query.join(Device, Order.device_id == Device.id).filter(
                Device.merchant_id == merchant_id
            )
        
        return query.order_by(desc(Order.created_at)).all()
    
    def find_paid_orders(
        self, 
        device_id: Optional[int] = None, 
        merchant_id: Optional[int] = None
    ) -> List[Order]:
        """Find all paid orders."""
        query = self.session.query(Order).filter(Order.pay_status == 'paid')
        
        if device_id:
            query = query.filter(Order.device_id == device_id)
        elif merchant_id:
            query = query.join(Device, Order.device_id == Device.id).filter(
                Device.merchant_id == merchant_id
            )
        
        return query.order_by(desc(Order.created_at)).all()
    
    def get_daily_sales(
        self, 
        start_date: datetime, 
        end_date: datetime, 
        merchant_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get daily sales statistics."""
        query = (
            self.session.query(
                func.date(Order.created_at).label('date'),
                func.count(Order.id).label('order_count'),
                func.sum(Order.total_amount).label('total_revenue'),
                func.avg(Order.total_amount).label('avg_order_value')
            )
            .filter(
                and_(
                    Order.pay_status == 'paid',
                    between(Order.created_at, start_date, end_date)
                )
            )
        )
        
        if merchant_id:
            query = query.join(Device, Order.device_id == Device.id).filter(
                Device.merchant_id == merchant_id
            )
        
        return query.group_by(func.date(Order.created_at)).order_by(
            func.date(Order.created_at)
        ).all()
    
    def get_product_sales_stats(
        self, 
        start_date: datetime, 
        end_date: datetime,
        device_id: Optional[int] = None,
        merchant_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get product sales statistics."""
        query = (
            self.session.query(
                Order.product_id,
                Product.name.label('product_name'),
                func.count(Order.id).label('order_count'),
                func.sum(Order.quantity).label('total_quantity'),
                func.sum(Order.total_amount).label('total_revenue')
            )
            .outerjoin(Product, Order.product_id == Product.id)
            .filter(
                and_(
                    Order.pay_status == 'paid',
                    between(Order.created_at, start_date, end_date)
                )
            )
        )
        
        if device_id:
            query = query.filter(Order.device_id == device_id)
        elif merchant_id:
            query = query.join(Device, Order.device_id == Device.id).filter(
                Device.merchant_id == merchant_id
            )
        
        return query.group_by(Order.product_id, Product.name).order_by(
            func.count(Order.id).desc()
        ).all()
    
    def get_order_statistics(
        self, 
        days: int = 30, 
        merchant_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get comprehensive order statistics."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        query = self.session.query(Order).filter(
            between(Order.created_at, start_date, end_date)
        )
        
        if merchant_id:
            query = query.join(Device, Order.device_id == Device.id).filter(
                Device.merchant_id == merchant_id
            )
        
        # Total orders
        total_orders = query.count()
        
        # Paid orders stats
        paid_query = query.filter(Order.pay_status == 'paid')
        paid_orders = paid_query.count()
        total_revenue = paid_query.with_entities(
            func.sum(Order.total_amount)
        ).scalar() or 0
        
        # Today's stats
        today = datetime.utcnow().date()
        today_query = query.filter(func.date(Order.created_at) == today)
        today_orders = today_query.filter(Order.pay_status == 'paid').count()
        today_revenue = today_query.filter(Order.pay_status == 'paid').with_entities(
            func.sum(Order.total_amount)
        ).scalar() or 0
        
        return {
            'total_orders': total_orders,
            'paid_orders': paid_orders,
            'total_revenue': float(total_revenue),
            'avg_order_value': float(total_revenue / paid_orders) if paid_orders > 0 else 0.0,
            'today_orders': today_orders,
            'today_revenue': float(today_revenue),
            'conversion_rate': round(paid_orders / total_orders * 100, 2) if total_orders > 0 else 0
        }