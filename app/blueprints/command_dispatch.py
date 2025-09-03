"""
Management-side command dispatch endpoints according to specification.
Implements Section 5.7 - Backend Command Dispatch
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Dict, List
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..extensions import db
from ..models import Device, RemoteCommand, User, OperationLog
from ..utils.security import merchant_scope_filter
from ..tasks.queue import submit_task, Task

bp = Blueprint("commands", __name__)


def _current_claims():
    """Get current user claims from JWT or session"""
    try:
        return get_jwt_identity()
    except Exception:
        return None


@bp.route("/api/commands/dispatch", methods=["POST"])
@jwt_required()
def dispatch_commands():
    """
    Backend Command Dispatch (Section 5.7)
    POST /api/commands/dispatch
    
    Request body:
    {
        "device_ids": ["D001", "D002"],
        "command_type": "upgrade",
        "payload": {
            "package_url": "http://host/packages/pk-1.zip",
            "md5": "abcd1234"
        },
        "note": "publish recipe package v1.0.0"
    }
    
    Response:
    {
        "ok": true,
        "batch_id": "batch-20250901-001", 
        "issued_count": 2
    }
    """
    try:
        claims = _current_claims()
        if not claims:
            return jsonify({"error": "Unauthorized"}), 401
            
        data = request.get_json() or {}
        device_ids = data.get("device_ids", [])
        command_type = data.get("command_type")
        payload = data.get("payload", {})
        note = data.get("note", "")
        
        if not device_ids or not command_type:
            return jsonify({"error": "device_ids and command_type required"}), 400
        
        # Generate batch ID
        batch_id = f"batch-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
        
        # Find devices (with merchant scope filtering if applicable)
        device_query = Device.query.filter(Device.device_no.in_(device_ids))
        device_query = merchant_scope_filter(device_query, claims)
        devices = device_query.all()
        
        if not devices:
            return jsonify({"error": "No devices found"}), 404
        
        issued_count = 0
        
        # Create commands for each device
        for device in devices:
            command_id = f"cmd-{uuid.uuid4().hex}"
            
            remote_cmd = RemoteCommand(
                command_id=command_id,
                device_id=device.id,
                command_type=command_type,
                payload=payload,
                issued_by=claims.get("id", 0),
                status="pending",
                batch_info=batch_id
            )
            
            db.session.add(remote_cmd)
            issued_count += 1
            
            # Submit to task queue for dispatch
            task = Task(
                id=f"dispatch-{uuid.uuid4().hex[:8]}",
                type="dispatch_command",
                payload={
                    "command_id": command_id,
                    "device_id": device.id,
                    "device_no": device.device_no,
                    "command_type": command_type,
                    "payload": payload
                }
            )
            submit_task(task)
        
        db.session.commit()
        
        # Log operation
        operation_log = OperationLog(
            user_id=claims.get("id", 0),
            action="command_dispatch",
            target_type="batch",
            target_id=None,
            ip=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            raw_payload={
                "batch_id": batch_id,
                "device_ids": device_ids,
                "command_type": command_type,
                "issued_count": issued_count,
                "note": note
            }
        )
        db.session.add(operation_log)
        db.session.commit()
        
        return jsonify({
            "ok": True,
            "batch_id": batch_id,
            "issued_count": issued_count
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Command dispatch failed: {str(e)}"}), 500


@bp.route("/api/commands/batches", methods=["GET"])
@jwt_required()
def list_command_batches():
    """
    List command batches with status
    GET /api/commands/batches
    """
    try:
        claims = _current_claims()
        if not claims:
            return jsonify({"error": "Unauthorized"}), 401
        
        # Get unique batch IDs and their status summary
        batch_query = db.session.query(
            RemoteCommand.batch_info,
            db.func.count(RemoteCommand.id).label('total'),
            db.func.sum(db.case((RemoteCommand.status == 'pending', 1), else_=0)).label('pending'),
            db.func.sum(db.case((RemoteCommand.status == 'sent', 1), else_=0)).label('sent'),
            db.func.sum(db.case((RemoteCommand.status == 'success', 1), else_=0)).label('success'),
            db.func.sum(db.case((RemoteCommand.status == 'fail', 1), else_=0)).label('failed'),
            db.func.min(RemoteCommand.created_at).label('created_at'),
            db.func.max(RemoteCommand.result_at).label('completed_at')
        ).filter(
            RemoteCommand.batch_info.isnot(None)
        ).group_by(RemoteCommand.batch_info).order_by(
            db.func.min(RemoteCommand.created_at).desc()
        )
        
        # Apply merchant filtering if needed
        if claims.get("role") != "superadmin":
            batch_query = batch_query.join(Device).filter(
                Device.merchant_id == claims.get("merchant_id")
            )
        
        page = int(request.args.get("page", 1))
        per_page = min(int(request.args.get("per_page", 20)), 100)
        
        batches = batch_query.limit(per_page).offset((page - 1) * per_page).all()
        
        result = []
        for batch in batches:
            result.append({
                "batch_id": batch.batch_info,
                "total": batch.total,
                "pending": batch.pending,
                "sent": batch.sent,
                "success": batch.success,
                "failed": batch.failed,
                "created_at": batch.created_at.isoformat() if batch.created_at else None,
                "completed_at": batch.completed_at.isoformat() if batch.completed_at else None
            })
        
        return jsonify({
            "ok": True,
            "batches": result,
            "page": page,
            "per_page": per_page
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to list batches: {str(e)}"}), 500


@bp.route("/api/commands/batches/<batch_id>", methods=["GET"])
@jwt_required()
def get_command_batch_details(batch_id: str):
    """
    Get detailed information about a specific command batch
    GET /api/commands/batches/{batch_id}
    """
    try:
        claims = _current_claims()
        if not claims:
            return jsonify({"error": "Unauthorized"}), 401
            
        # Get all commands in the batch
        query = RemoteCommand.query.filter_by(batch_info=batch_id)
        
        # Apply merchant filtering if needed
        if claims.get("role") != "superadmin":
            query = query.join(Device).filter(
                Device.merchant_id == claims.get("merchant_id")
            )
        
        commands = query.order_by(RemoteCommand.created_at.desc()).all()
        
        if not commands:
            return jsonify({"error": "Batch not found"}), 404
        
        # Build detailed response
        command_details = []
        for cmd in commands:
            device = Device.query.get(cmd.device_id)
            command_details.append({
                "command_id": cmd.command_id,
                "device_no": device.device_no if device else None,
                "device_id": cmd.device_id,
                "command_type": cmd.command_type,
                "status": cmd.status,
                "payload": cmd.payload,
                "result_payload": cmd.result_payload,
                "created_at": cmd.created_at.isoformat(),
                "result_at": cmd.result_at.isoformat() if cmd.result_at else None
            })
        
        return jsonify({
            "ok": True,
            "batch_id": batch_id,
            "commands": command_details,
            "total": len(commands)
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to get batch details: {str(e)}"}), 500


@bp.route("/api/commands/batches/<batch_id>/retry", methods=["POST"])
@jwt_required()
def retry_command_batch(batch_id: str):
    """
    Retry failed commands in a batch
    POST /api/commands/batches/{batch_id}/retry
    """
    try:
        claims = _current_claims()
        if not claims:
            return jsonify({"error": "Unauthorized"}), 401
            
        data = request.get_json() or {}
        retry_all = data.get("retry_all", False)  # Retry all failed, or specific command IDs
        command_ids = data.get("command_ids", [])
        
        # Get commands to retry
        query = RemoteCommand.query.filter_by(batch_info=batch_id)
        
        if not retry_all and command_ids:
            query = query.filter(RemoteCommand.command_id.in_(command_ids))
        elif not retry_all:
            query = query.filter(RemoteCommand.status == 'fail')
        else:
            query = query.filter(RemoteCommand.status.in_(['fail', 'timeout']))
        
        # Apply merchant filtering
        if claims.get("role") != "superadmin":
            query = query.join(Device).filter(
                Device.merchant_id == claims.get("merchant_id")
            )
        
        commands = query.all()
        
        if not commands:
            return jsonify({"error": "No commands to retry"}), 404
        
        retried_count = 0
        for cmd in commands:
            # Reset command status
            cmd.status = "pending"
            cmd.result_payload = None
            cmd.result_at = None
            
            # Re-submit to task queue
            device = Device.query.get(cmd.device_id)
            task = Task(
                id=f"retry-{uuid.uuid4().hex[:8]}",
                type="dispatch_command",
                payload={
                    "command_id": cmd.command_id,
                    "device_id": cmd.device_id,
                    "device_no": device.device_no if device else None,
                    "command_type": cmd.command_type,
                    "payload": cmd.payload
                }
            )
            submit_task(task)
            
            retried_count += 1
        
        db.session.commit()
        
        # Log retry operation
        operation_log = OperationLog(
            user_id=claims.get("id", 0),
            action="command_batch_retry",
            target_type="batch",
            target_id=None,
            ip=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            raw_payload={
                "batch_id": batch_id,
                "retried_count": retried_count
            }
        )
        db.session.add(operation_log)
        db.session.commit()
        
        return jsonify({
            "ok": True,
            "retried_count": retried_count
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to retry batch: {str(e)}"}), 500