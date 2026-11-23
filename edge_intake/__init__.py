"""Independent Telemetry reception boundary; no training or transport dependency."""

from .intake import INTAKE_VERSION, EdgeIntakeError, receive_validated_telemetry

__version__ = INTAKE_VERSION
__all__ = ["EdgeIntakeError", "receive_validated_telemetry", "__version__"]
