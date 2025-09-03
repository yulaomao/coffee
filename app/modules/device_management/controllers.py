"""
Device Management Controller - Presentation Layer
Handles HTTP requests and responses for device management operations.
"""

from typing import List, Optional

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pydantic import ValidationError

from ...schemas.device_schemas import (
    DeviceCreateSchema,
    DeviceMaterialSchema,
    DeviceResponseSchema,
    DeviceUpdateSchema,
    MaterialRefillSchema,
)
from ...utils.security import merchant_scope_filter
from .services import DeviceManagementService

bp = Blueprint("device_management", __name__, url_prefix="/api/v1/devices")


def _get_current_claims():
    """Get current user claims from JWT."""
    try:
        return get_jwt_identity()
    except Exception:
        return None


def _validate_merchant_access(device_id: int, claims: dict) -> bool:
    """Validate merchant access to device."""
    if claims.get("role") == "superadmin":
        return True

    # For other roles, check merchant ownership
    service = DeviceManagementService()
    device = service.device_repo.get_by_id(device_id)

    return device and device.merchant_id == claims.get("merchant_id")


@bp.route("/", methods=["POST"])
@jwt_required()
def register_device():
    """Register a new device."""
    claims = _get_current_claims()
    if not claims:
        return jsonify({"error": "Authentication required"}), 401

    try:
        # Parse request data
        data = request.get_json()
        device_data = DeviceCreateSchema(**data)

        # Validate merchant access
        if claims.get("role") != "superadmin":
            if device_data.merchant_id != claims.get("merchant_id"):
                return jsonify({"error": "Access denied to merchant"}), 403

        # Get initial materials if provided
        initial_materials = None
        if "initial_materials" in data:
            initial_materials = [
                DeviceMaterialSchema(**material) for material in data["initial_materials"]
            ]

        # Register device
        service = DeviceManagementService()
        result = service.register_new_device(device_data, initial_materials)

        return (
            jsonify(
                {
                    "success": True,
                    "message": "Device registered successfully",
                    "device": result.model_dump(),
                }
            ),
            201,
        )

    except ValidationError as e:
        return jsonify({"error": "Validation error", "details": e.errors()}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/<int:device_id>", methods=["PUT"])
@jwt_required()
def update_device(device_id: int):
    """Update device information."""
    claims = _get_current_claims()
    if not claims:
        return jsonify({"error": "Authentication required"}), 401

    # Validate access
    if not _validate_merchant_access(device_id, claims):
        return jsonify({"error": "Access denied"}), 403

    try:
        data = request.get_json()
        update_data = DeviceUpdateSchema(**data)

        service = DeviceManagementService()
        result = service.update_device_information(device_id, update_data)

        return jsonify(
            {
                "success": True,
                "message": "Device updated successfully",
                "device": result.model_dump(),
            }
        )

    except ValidationError as e:
        return jsonify({"error": "Validation error", "details": e.errors()}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/dashboard", methods=["GET"])
@jwt_required()
def device_dashboard():
    """Get device dashboard data."""
    claims = _get_current_claims()
    if not claims:
        return jsonify({"error": "Authentication required"}), 401

    try:
        merchant_id = None
        if claims.get("role") != "superadmin":
            merchant_id = claims.get("merchant_id")

        service = DeviceManagementService()
        dashboard_data = service.get_device_dashboard(merchant_id)

        return jsonify({"success": True, "data": dashboard_data})

    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/<int:device_id>/materials/refill", methods=["POST"])
@jwt_required()
def refill_material(device_id: int):
    """Refill device material."""
    claims = _get_current_claims()
    if not claims:
        return jsonify({"error": "Authentication required"}), 401

    # Validate access
    if not _validate_merchant_access(device_id, claims):
        return jsonify({"error": "Access denied"}), 403

    # Validate role permissions
    if claims.get("role") not in {"superadmin", "merchant_admin", "ops_engineer"}:
        return jsonify({"error": "Insufficient permissions"}), 403

    try:
        data = request.get_json()
        refill_data = MaterialRefillSchema(**data)

        service = DeviceManagementService()
        result = service.perform_material_refill(device_id, refill_data)

        return jsonify(
            {"success": True, "message": "Material refilled successfully", "refill_details": result}
        )

    except ValidationError as e:
        return jsonify({"error": "Validation error", "details": e.errors()}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/<int:device_id>/health", methods=["GET"])
@jwt_required()
def device_health_report(device_id: int):
    """Get comprehensive device health report."""
    claims = _get_current_claims()
    if not claims:
        return jsonify({"error": "Authentication required"}), 401

    # Validate access
    if not _validate_merchant_access(device_id, claims):
        return jsonify({"error": "Access denied"}), 403

    try:
        days = int(request.args.get("days", 7))
        if days < 1 or days > 30:
            return jsonify({"error": "Days must be between 1 and 30"}), 400

        service = DeviceManagementService()
        health_report = service.get_device_health_report(device_id, days)

        return jsonify({"success": True, "report": health_report})

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/<int:device_id>/materials", methods=["GET"])
@jwt_required()
def get_device_materials(device_id: int):
    """Get device material status."""
    claims = _get_current_claims()
    if not claims:
        return jsonify({"error": "Authentication required"}), 401

    # Validate access
    if not _validate_merchant_access(device_id, claims):
        return jsonify({"error": "Access denied"}), 403

    try:
        service = DeviceManagementService()
        device_materials = service.device_material_repo.find_by_device(device_id)

        # Format response
        materials_data = []
        for dm in device_materials:
            # Get material info
            material = service.material_repo.get_by_id(dm.material_id)

            # Calculate alert level
            if dm.remain <= dm.threshold:
                alert_level = "critical"
            elif dm.remain <= dm.threshold * 1.2:
                alert_level = "warning"
            else:
                alert_level = "normal"

            materials_data.append(
                {
                    "material_id": dm.material_id,
                    "material_name": material.name if material else f"Material {dm.material_id}",
                    "unit": material.unit if material else "units",
                    "remain": dm.remain,
                    "capacity": dm.capacity,
                    "threshold": dm.threshold,
                    "stock_percent": round((dm.remain / dm.capacity) * 100, 2),
                    "alert_level": alert_level,
                    "updated_at": dm.updated_at.isoformat(),
                }
            )

        return jsonify({"success": True, "device_id": device_id, "materials": materials_data})

    except Exception as e:
        return jsonify({"error": "Internal server error"}), 500


# Error handlers for the blueprint
@bp.errorhandler(ValidationError)
def handle_validation_error(e):
    return jsonify({"error": "Validation error", "details": e.errors()}), 400


@bp.errorhandler(ValueError)
def handle_value_error(e):
    return jsonify({"error": str(e)}), 400
