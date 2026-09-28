"""WAITING_FOR_A real CSV/metadata and WAITING_FOR_B transformation rules."""

from ai_training.errors import ContractNotReadyError


class RealAdapter:
    def to_dataset(self, artifact, contract):
        raise ContractNotReadyError("WAITING_FOR_A / WAITING_FOR_B: real handoff and mapping absent; provide CSV, Calibration Metadata, validity and B contract")
