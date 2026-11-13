"""Read-only NODE01 conversion CLI; does not enable RealAdapter."""
from pathlib import Path
import sys

# Permit direct execution from a checkout without installing ai_training.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_training.real_intake.node01_contract_csv import main

if __name__ == "__main__":
    raise SystemExit(main())
