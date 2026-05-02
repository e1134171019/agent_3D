"""
Phase-0 map-building strategy pack.

Active roles:
- PointCloudValidator: validates upstream SfM / pointcloud readiness
- MapValidator: validates 3DGS quality
- ProductionParamGate: proposes controlled SfM / 3DGS parameters
"""

from .pointcloud_validator import PointCloudValidator
from .map_validator import MapValidator
from .production_param_gate import ProductionParamGate

__all__ = [
    "PointCloudValidator",
    "MapValidator",
    "ProductionParamGate",
]
