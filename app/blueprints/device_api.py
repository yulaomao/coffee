"""
Device-side API endpoints according to specification Section 5.
Implements the required HTTP REST endpoints for device communication:
- POST /api/devices/register (5.1)
- POST /api/devices/{id}/status (5.2)  
- POST /api/devices/{id}/materials/report (5.3)
- GET /api/devices/{id}/commands/pending (5.4)
- POST /api/devices/{id}/command_result (5.5)
- POST /api/devices/{id}/orders/create (5.6)
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Dict, List
from flask import Blueprint, jsonify, request, current_app
from ..extensions import db
from ..models import (
    Device, Merchant, DeviceBin, MaterialCatalog, Order, RemoteCommand, 
    CommandResult, DeviceStatusLog, OperationLog
)

bp = Blueprint("device_specification_api", __name__)


def _log_operation(action: str, target_type: str, target_id: int = None, payload: Dict = None):
    """记录操作日志"""
    try:
        log = OperationLog(
            user_id=0,  # System user for device operations
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            raw_payload=payload
        )
        db.session.add(log)
    except Exception:
        pass  # Don't fail the main operation due to logging issues


@bp.route("/api/devices/register", methods=["POST"])
def device_register():
    """
    Device Registration (Section 5.1)
    POST /api/devices/register
    
    Request body:
    {
        "device_id": "D001",
        "model": "CoffeePro-A", 
        "firmware_version": "1.2.0",
        "serial": "SN-20250901-0001",
        "mac": "AA:BB:CC:DD:EE",
        "location": {"lat": 1.234, "lng": 103.123},
        "address": "Mall 1F"
    }
    
    Response:
    {
        "ok": true,
        "device_id": "D001", 
        "message": "registered",
        "provisioning": {
            "merchant_id": null,
            "needs_binding": true
        }
    }
    """
    try:
        data = request.get_json() or {}
        
        device_id = data.get("device_id")
        if not device_id:
            return jsonify({"ok": False, "error": "device_id required"}), 400
            
        # Check if device already exists
        existing_device = Device.query.filter_by(device_no=device_id).first()
        
        if existing_device:
            # Update existing device information
            existing_device.model = data.get("model", existing_device.model)
            existing_device.firmware_version = data.get("firmware_version", existing_device.firmware_version)
            if data.get("location"):
                loc = data["location"]
                existing_device.location_lat = loc.get("lat")
                existing_device.location_lng = loc.get("lng")
            existing_device.address = data.get("address", existing_device.address)
            existing_device.last_seen = datetime.utcnow()
            existing_device.status = "registered"
            
        else:
            # Create new device - assign to first merchant for now
            default_merchant = Merchant.query.first()
            if not default_merchant:
                return jsonify({"ok": False, "error": "No merchant configured"}), 500
                
            existing_device = Device(
                device_no=device_id,
                merchant_id=default_merchant.id,
                model=data.get("model"),
                firmware_version=data.get("firmware_version"),
                software_version=data.get("software_version"),
                status="registered",
                last_seen=datetime.utcnow()
            )
            
            if data.get("location"):
                loc = data["location"]
                existing_device.location_lat = loc.get("lat")
                existing_device.location_lng = loc.get("lng")
            existing_device.address = data.get("address")
            
            db.session.add(existing_device)
        
        db.session.commit()
        
        _log_operation("device_register", "device", existing_device.id, data)
        
        # Determine if device needs merchant binding
        needs_binding = existing_device.merchant_id is None
        
        return jsonify({
            "ok": True,
            "device_id": device_id,
            "message": "registered",
            "provisioning": {
                "merchant_id": existing_device.merchant_id,
                "needs_binding": needs_binding
            }
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Device registration error: {e}")
        return jsonify({"ok": False, "error": "Registration failed"}), 500


@bp.route("/api/devices/<device_id>/status", methods=["POST"])
def device_status_report(device_id: str):
    """
    Device Status Report (Section 5.2)  
    POST /api/devices/{device_id}/status
    
    Request body:
    {
        "device_id": "D001",
        "timestamp": "2025-09-01T10:30:00Z",
        "status": "online",
        "temperature": 92.5,
        "wifi_ssid": "Mall-WiFi", 
        "firmware_version": "1.2.0",
        "uptime_seconds": 3600
    }
    
    Response: {"ok": true}
    """
    try:
        device = Device.query.filter_by(device_no=device_id).first()
        if not device:
            return jsonify({"ok": False, "error": "Device not found"}), 404
            
        data = request.get_json() or {}
        
        # Update device status
        device.status = data.get("status", "online")
        device.last_seen = datetime.utcnow()
        if data.get("firmware_version"):
            device.firmware_version = data["firmware_version"]
        
        # Log detailed status  
        status_log = DeviceStatusLog(
            device_id=device.id,
            status=data.get("status", "online"),
            payload={
                "timestamp": data.get("timestamp"),
                "temperature": data.get("temperature"),
                "wifi_ssid": data.get("wifi_ssid"),
                "uptime_seconds": data.get("uptime_seconds"),
                "raw_data": data
            }
        )
        db.session.add(status_log)
        db.session.commit()
        
        _log_operation("device_status_report", "device", device.id, data)
        
        return jsonify({"ok": True})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Status report error: {e}")
        return jsonify({"ok": False, "error": "Status report failed"}), 500


@bp.route("/api/devices/<device_id>/materials/report", methods=["POST"])
def device_materials_report(device_id: str):
    """
    Material Report (Section 5.3)
    POST /api/devices/{device_id}/materials/report
    
    Request body:
    {
        "device_id": "D001",
        "timestamp": "2025-09-01T10:31:00Z",
        "bins": [
            {
                "bin_index": 1,
                "material_code": "BEAN_A", 
                "remaining": 800,
                "capacity": 1000,
                "unit": "g"
            },
            {
                "bin_index": 2,
                "material_code": "MILK_POWDER",
                "remaining": 120, 
                "capacity": 500,
                "unit": "g"
            }
        ]
    }
    
    Response: {"ok": true}
    """
    try:
        device = Device.query.filter_by(device_no=device_id).first()
        if not device:
            return jsonify({"ok": False, "error": "Device not found"}), 404
            
        data = request.get_json() or {}
        bins = data.get("bins", [])
        
        for bin_data in bins:
            bin_index = bin_data.get("bin_index")
            material_code = bin_data.get("material_code")
            remaining = bin_data.get("remaining", 0)
            capacity = bin_data.get("capacity", 1000)
            unit = bin_data.get("unit", "g")
            
            if not bin_index:
                continue
                
            # Find or create material catalog entry
            material = None
            if material_code:
                material = MaterialCatalog.query.filter_by(code=material_code).first()
                if not material:
                    # Auto-create material if not exists
                    material = MaterialCatalog(
                        code=material_code,
                        name=material_code,
                        unit=unit,
                        is_active=True
                    )
                    db.session.add(material)
                    db.session.flush()  # Get ID
            
            # Update or create device bin
            device_bin = DeviceBin.query.filter_by(
                device_id=device.id, 
                bin_index=bin_index
            ).first()
            
            if not device_bin:
                device_bin = DeviceBin(
                    device_id=device.id,
                    bin_index=bin_index
                )
                db.session.add(device_bin)
            
            device_bin.material_id = material.id if material else None
            device_bin.remaining = remaining
            device_bin.capacity = capacity
            device_bin.unit = unit
            device_bin.last_sync_at = datetime.utcnow()
        
        db.session.commit()
        
        _log_operation("device_materials_report", "device", device.id, data)
        
        return jsonify({"ok": True})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Materials report error: {e}")
        return jsonify({"ok": False, "error": "Materials report failed"}), 500


@bp.route("/api/devices/<device_id>/commands/pending", methods=["GET"])
def device_commands_pending(device_id: str):
    """
    Device Command Polling (Section 5.4)
    GET /api/devices/{device_id}/commands/pending
    
    Response:
    [
        {
            "command_id": "cmd-uuid-0001",
            "type": "make_product",
            "payload": {
                "product_id": 101,
                "recipe_id": 201, 
                "order_id": "ORD-..."
            },
            "issued_at": "2025-09-01T10:30:05Z"
        },
        {
            "command_id": "cmd-uuid-0002",
            "type": "open_door",
            "payload": {},
            "issued_at": "..."
        }
    ]
    """
    try:
        device = Device.query.filter_by(device_no=device_id).first()
        if not device:
            return jsonify([]), 404  # Return empty array for not found
            
        # Get pending commands for this device
        pending_commands = RemoteCommand.query.filter_by(
            device_id=device.id,
            status="pending"
        ).order_by(RemoteCommand.created_at.asc()).all()
        
        # Update device last seen
        device.last_seen = datetime.utcnow()
        db.session.commit()
        
        commands = []
        for cmd in pending_commands:
            commands.append({
                "command_id": cmd.command_id,
                "type": cmd.command_type,
                "payload": cmd.payload or {},
                "issued_at": cmd.created_at.isoformat() + "Z"
            })
            
            # Mark command as sent
            cmd.status = "sent"
            
        db.session.commit()
        
        return jsonify(commands)
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Command polling error: {e}")
        return jsonify([])


@bp.route("/api/devices/<device_id>/command_result", methods=["POST"])
def device_command_result(device_id: str):
    """
    Device Command Result (Section 5.5)
    POST /api/devices/{device_id}/command_result
    
    Request body:
    {
        "command_id": "cmd-uuid-0001",
        "device_id": "D001", 
        "status": "success",
        "result_payload": {
            "msg": "brew ok",
            "consumed": [{"bin": 1, "amt": 7}]
        },
        "result_at": "2025-09-01T10:31:12Z"
    }
    
    Response: {"ok": true}
    """
    try:
        device = Device.query.filter_by(device_no=device_id).first()
        if not device:
            return jsonify({"ok": False, "error": "Device not found"}), 404
            
        data = request.get_json() or {}
        command_id = data.get("command_id")
        status = data.get("status", "success")
        result_payload = data.get("result_payload")
        
        if not command_id:
            return jsonify({"ok": False, "error": "command_id required"}), 400
            
        # Find the remote command
        remote_cmd = RemoteCommand.query.filter_by(
            command_id=command_id,
            device_id=device.id
        ).first()
        
        if remote_cmd:
            # Update command status
            remote_cmd.status = status
            remote_cmd.result_payload = result_payload
            remote_cmd.result_at = datetime.utcnow()
        
        # Create command result record
        cmd_result = CommandResult(
            command_id=command_id,
            device_id=device.id,
            success=(status == "success"),
            message=result_payload.get("msg") if result_payload else None,
            raw_payload=data
        )
        db.session.add(cmd_result)
        
        # Update device last seen
        device.last_seen = datetime.utcnow()
        
        db.session.commit()
        
        _log_operation("device_command_result", "command", remote_cmd.id if remote_cmd else None, data)
        
        return jsonify({"ok": True})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Command result error: {e}")
        return jsonify({"ok": False, "error": "Command result failed"}), 500


@bp.route("/api/devices/<device_id>/orders/create", methods=["POST"])
def device_order_create(device_id: str):
    """
    Device Order Creation (Section 5.6)
    POST /api/devices/{device_id}/orders/create
    
    Request body:
    {
        "order_id": "ORD-20250901-0001",
        "device_id": "D001",
        "timestamp": "2025-09-01T10:35:00Z",
        "address": "Mall 1F",
        "items": [
            {
                "product_id": 101,
                "name": "Latte", 
                "qty": 1,
                "unit_price": 3.00
            }
        ],
        "total_price": 3.00,
        "payment_method": "wechat",
        "payment_status": "paid"
    }
    
    Response: {"ok": true}
    """
    try:
        device = Device.query.filter_by(device_no=device_id).first()
        if not device:
            return jsonify({"ok": False, "error": "Device not found"}), 404
            
        data = request.get_json() or {}
        order_id = data.get("order_id")
        items = data.get("items", [])
        total_price = data.get("total_price", 0)
        payment_method = data.get("payment_method", "cash")
        payment_status = data.get("payment_status", "paid")
        
        # Check if order already exists (idempotency)
        existing_order = Order.query.filter_by(order_no=order_id).first()
        if existing_order:
            return jsonify({"ok": True, "message": "Order already exists"})
        
        # Create order record
        order = Order(
            order_no=order_id,
            device_id=device.id,
            merchant_id=device.merchant_id,
            product_name=items[0]["name"] if items else "Unknown",
            qty=sum(item.get("qty", 1) for item in items),
            unit_price=items[0].get("unit_price", 0) if items else 0,
            total_amount=total_price,
            pay_method=payment_method,
            pay_status=payment_status,
            status=payment_status,
            is_exception=False,
            raw_payload=data
        )
        
        db.session.add(order)
        
        # Update device last seen
        device.last_seen = datetime.utcnow()
        
        db.session.commit()
        
        _log_operation("device_order_create", "order", order.id, data)
        
        return jsonify({"ok": True})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Order creation error: {e}")
        return jsonify({"ok": False, "error": "Order creation failed"}), 500