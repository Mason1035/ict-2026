"""Adapters consume artifacts, never simulator private implementation modules."""

from typing import Protocol
from ai_training.datasets.base import CanonicalDataset


class BaseAdapter(Protocol):
    def to_dataset(self, artifact, contract) -> CanonicalDataset: ...
