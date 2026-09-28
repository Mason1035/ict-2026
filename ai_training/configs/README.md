# Training configuration boundary

No project training configuration has been approved. This directory intentionally
contains no default feature list, epochs, optimizer, loss, split ratios or metric.

`TrainingConfig` holds explicit execution settings; B's separate external contract
controls scientific data semantics. Configuration is recorded as canonical JSON
in each TEST_ONLY run (`training_config.json`; JSON avoids a YAML dependency).

Software fixtures live only in `tests/fixtures/`. Their values are TEST_ONLY,
NOT_PROJECT_CONTRACT and NOT_APPROVED_BY_B. Copying them here does not authorize
formal training. REAL_ONLY and REAL_PLUS_SYNTHETIC remain WAITING_FOR_A/B.
