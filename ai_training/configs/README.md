# Training configuration boundary

`public_multimodal_v1.json` is an explicit **PUBLIC_DATA_RESEARCH** configuration
for the independent soil/motion next-observation regressors described in
[MULTIMODAL.md](../MULTIMODAL.md). It does not approve a formal B contract,
define project class labels, or change hardware sampling/thresholds.
The statements below concern the original formal Trainer configuration boundary.

No project training configuration has been approved. This directory intentionally
contains no formal default feature list, epochs, optimizer, loss, split ratios or metric.

`TrainingConfig` holds explicit execution settings; B's separate external contract
controls scientific data semantics. Configuration is recorded as canonical JSON
in each TEST_ONLY run (`training_config.json`; JSON avoids a YAML dependency).

Software fixtures live only in `tests/fixtures/`. Their values are TEST_ONLY,
NOT_PROJECT_CONTRACT and NOT_APPROVED_BY_B. Copying them here does not authorize
formal training. REAL_ONLY and REAL_PLUS_SYNTHETIC remain WAITING_FOR_A/B.
