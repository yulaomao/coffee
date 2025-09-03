"""
Material Management Module
Handles all material-related functionality including catalog management, inventory tracking, and supply chain.
"""

from .controllers import material_controller
from .models import InventoryModel, MaterialModel
from .services import MaterialManagementService

__all__ = ["material_controller", "MaterialManagementService", "MaterialModel", "InventoryModel"]
