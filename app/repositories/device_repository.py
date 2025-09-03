"""
Device Repository implementation with device-specific operations.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import and_, or_, desc, func
from .base_repository import BaseRepository
from ..models import Device, DeviceStatusLog, DeviceMaterial, MaterialCatalog


class DeviceRepository(BaseRepository[Device]):
    """Repository for Device-specific operations."""
    
    def __init__(self):
        from ..models import Device
        super().__init__(Device)
    
    def find_by_device_no(self, device_no: str) -> Optional[Device]:
        """Find device by device number."""
        return self.find_one_by(device_no=device_no)
    
    def find_by_merchant(self, merchant_id: int) -> List[Device]:
        """Find all devices for a merchant."""
        return self.find_by(merchant_id=merchant_id)
    
    def find_online_devices(self) -> List[Device]:
        """Find all online devices."""
        return self.find_by(status='online')
    
    def find_offline_devices(self) -> List[Device]:
        """Find all offline devices."""
        return self.find_by(status='offline')
    
    def get_device_with_materials(self, device_id: int) -> Optional[Device]:
        """Get device with its material information."""
        device = self.get_by_id(device_id)
        if device:
            # Eager load materials
            materials = (
                self.session.query(DeviceMaterial, MaterialCatalog)
                .outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceMaterial.material_id)
                .filter(DeviceMaterial.device_id == device_id)
                .all()
            )
            device._materials = materials
        return device
    
    def get_devices_with_low_materials(self, threshold_multiplier: float = 1.0) -> List[Dict[str, Any]]:
        """Get devices with materials below threshold."""
        return (
            self.session.query(
                Device.id.label('device_id'),
                Device.device_no,
                DeviceMaterial.material_id,
                MaterialCatalog.name.label('material_name'),
                MaterialCatalog.unit,
                DeviceMaterial.remain,
                DeviceMaterial.threshold,
                DeviceMaterial.capacity
            )
            .join(DeviceMaterial, Device.id == DeviceMaterial.device_id)
            .outerjoin(MaterialCatalog, MaterialCatalog.id == DeviceMaterial.material_id)
            .filter(DeviceMaterial.remain <= DeviceMaterial.threshold * threshold_multiplier)
            .order_by(DeviceMaterial.remain.asc())
            .all()
        )
    
    def get_device_status_history(self, device_id: int, days: int = 7) -> List[DeviceStatusLog]:
        """Get device status history for the last N days."""
        since = datetime.utcnow() - timedelta(days=days)
        return (
            self.session.query(DeviceStatusLog)
            .filter(
                and_(
                    DeviceStatusLog.device_id == device_id,
                    DeviceStatusLog.created_at >= since
                )
            )
            .order_by(desc(DeviceStatusLog.created_at))
            .all()
        )
    
    def get_device_statistics(self, merchant_id: Optional[int] = None) -> Dict[str, Any]:
        """Get device statistics with optional merchant filtering."""
        query = self.session.query(Device)
        if merchant_id:
            query = query.filter(Device.merchant_id == merchant_id)
        
        total = query.count()
        online = query.filter(Device.status == 'online').count()
        offline = query.filter(Device.status == 'offline').count()
        fault = query.filter(Device.status == 'fault').count()
        
        return {
            'total': total,
            'online': online,
            'offline': offline,
            'fault': fault,
            'online_rate': round(online / total * 100, 2) if total > 0 else 0
        }
    
    def update_device_status(self, device_id: int, status: str, **kwargs) -> Device:
        """Update device status and log the change."""
        device = self.get_by_id(device_id)
        if device:
            old_status = device.status
            device = self.update(device, status=status, **kwargs)
            
            # Log status change if different
            if old_status != status:
                status_log = DeviceStatusLog(
                    device_id=device_id,
                    status=status,
                    previous_status=old_status
                )
                self.session.add(status_log)
        
        return device