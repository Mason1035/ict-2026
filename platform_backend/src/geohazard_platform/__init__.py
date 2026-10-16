"""Local-first platform; no claim of hardware, cloud or model qualification."""

from pathlib import Path
import sys

# The platform is deployed from this repository and consumes its existing
# independent Edge Intake rather than copying or redefining that boundary.
_repository = str(Path(__file__).resolve().parents[3])
if _repository not in sys.path:
    sys.path.insert(0, _repository)

__version__ = "0.2.0"
