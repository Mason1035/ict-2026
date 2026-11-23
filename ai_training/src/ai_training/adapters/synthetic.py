"""Read-only lineage inspection for physics_sim v0.1.1; no feature conversion."""

import csv
from pathlib import Path
import re
import hashlib
import json

from ai_training.datasets.provenance import Provenance
from ai_training.errors import ContractNotReadyError, IntegrityError
from ai_training.training.reproducibility import read_json, file_hash


class SyntheticAdapter:
    def inspect(self, directory):
        directory = Path(directory)
        meta = read_json(directory / "metadata.json")
        expected = {"artifact_kind": "simulator_observation_csv",
                    "observation_schema_version": "physics_sim.observation.v0.1.1",
                    "contract_status": "PRE_B_TRAINING_CONTRACT", "generator_version": "0.1.1"}
        if any(meta.get(k) != v for k, v in expected.items()):
            raise IntegrityError("unknown synthetic schema/status; use the documented v0.1.1 artifact inspector")
        digest = file_hash(directory / "simulation.csv")
        if meta.get("csv_sha256") != digest:
            raise IntegrityError("CSV hash mismatch; restore the original artifact and sidecar")
        h = meta.get("parameter_hash")
        if (meta.get("is_synthetic") is not True or type(meta.get("seed")) is not int
                or meta["seed"] < 0 or meta.get("parent_run") is not None
                or not isinstance(meta.get("config"), dict) or meta["config"].get("seed") != meta["seed"]
                or not isinstance(h, str) or not re.fullmatch("[0-9a-f]{64}", h)
                or meta.get("run_id") != f"sim_{h}"
                # Simulator v0.1.1 uses ASCII-escaped canonical JSON for its
                # normalized config. Honor that artifact convention independently.
                or hashlib.sha256(json.dumps(meta.get("config"), sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode()).hexdigest() != h):
            raise IntegrityError("invalid synthetic identity/config hash; provide consistent original metadata")
        result = []
        with (directory / "simulation.csv").open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            required = {"run_id", "row_index", "is_synthetic", "generator_version", "seed", "parameter_hash", "parent_run"}
            if not reader.fieldnames or not required <= set(reader.fieldnames) or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise IntegrityError("missing/duplicate lineage columns; restore simulator observation schema")
            for index, row in enumerate(reader):
                if (row["row_index"] != str(index) or str(row["is_synthetic"]).lower() != "true"
                        or row["run_id"] != meta["run_id"] or row["parent_run"] != ""
                        or row["seed"] != str(meta["seed"]) or row["parameter_hash"] != h
                        or row["generator_version"] != meta["generator_version"]):
                    raise IntegrityError(f"row {index}: inconsistent lineage; preserve original row identity")
                result.append(Provenance("SYNTHETIC", meta["run_id"], (index,),
                                         generator_version=meta["generator_version"], seed=meta["seed"],
                                         parameter_hash=h, source_artifact_hash=digest))
        if not result or type(meta.get("row_count")) is not int or len(result) != meta["row_count"]:
            raise IntegrityError("row count mismatch; provide a complete simulator artifact")
        return tuple(result)

    def to_dataset(self, artifact, contract):
        raise ContractNotReadyError("WAITING_FOR_B: observation proxies have no approved Feature/Label/Window mapping; submit an independent adapter contract")
