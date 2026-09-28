# C-side envelope proposal — WAITING_FOR_B

`ai_training.contract-envelope.v0.1` versions the framework envelope, **not** a
ratified project Feature/Training Contract. `TrainingContract` can represent B's
future version, ordered features, units, dtype, validity/mask and coordinate
semantics, sampling/alignment, causal window/warmup/gaps/padding, label, split,
normalization, metrics and synthetic constraints.

The unresolved example contains null scientific values. Loading it fails.
`load_training_contract(path)` also rejects TEST_ONLY fixtures and caller-supplied
approval claims. No formal B contract version interpreter is registered in V0.1.
The only executable interpreter is explicitly `test_only=True` with
`TEST_ONLY.v1`, declarations TEST_ONLY / NOT_PROJECT_CONTRACT /
NOT_APPROVED_BY_B and no approver. This opt-in is not an approval mechanism.

Future handoff: B supplies the versioned contract and split manifest; A supplies
the real artifact and calibration/validity evidence. Review that handoff against
00, implement its version-specific validator/adapter with negative tests, then
enable a formal execution path. Merely editing status strings must never enable it.

`feature_sources`, `feature_lookahead_s` and per-value `available_at` are proposed
audit evidence fields, not claims that B has approved their encoding. The toy
interpreter checks exact feature order, sources, zero lookahead, causal availability,
prealigned samples, and an explicit reject-nonfinite policy. It does not calculate
project features/windows/labels or infer hidden upstream computations.

SplitManifest assigns whole run IDs, source types, optional parent and optional
experiment group IDs. All ancestors must be declared, including source-only rows.
Duplicate runs, cyclic/unknown lineage and groups/ancestors crossing splits fail.
This is a conservative guard; B still owns group definitions and split generation.

## B handoff inspection in framework 0.1.1

`contracts/b_handoff.py` reads B_RULE_DISTILLATION_CONTRACT `1.0-test-only` and
B_FORMAL_TRAINING_CONTRACT `0.1-draft` via B's public validator CLI. This is a
readiness bridge, not a new formal TrainingContract interpreter. The formal draft
reports WAITING_FOR_A / WAITING_FOR_B / TODO_CALIBRATION and cannot execute.
Unknown versions and invented readiness fail closed.

`adapters/b_rule_fixture.py` consumes the TEST_ONLY artifact as precomputed tabular
rows. It preserves B feature order, demo labels/splits and provenance, without
coercing B data into the unrelated `TEST_ONLY.v1` toy regression/window contract.
The generic loader rejects both B contracts for training. See the module README
for the explicit read-only integration CLI and remaining formal dependencies.
