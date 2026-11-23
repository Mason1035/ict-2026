# Pinned A MOCK fixtures

`TEST_ONLY / MOCK_ONLY / NOT_REAL_DATA / NOT_PROJECT_TRAINING_DATA`.

These four cases and two runner helpers are exact byte copies from 李青原's
branch at `25c55ca0ab2e9d0f18e3640833a575102f7e48c6` in
`Mason1035/ict-2026`. `manifest.json` records source paths and SHA-256 hashes.
The verification tool checks every hash before executing the helpers.

`runner/mock_v2_validator.py` is A's **NOT_PRODUCTION_VALIDATOR**. Its fixture
checks are upstream routing evidence for this isolated software test; they do
not freeze a new production schema or implement the production validation layer.
The cases' older expected-status prose is retained verbatim as source history;
the generated evidence reports actual calls and outcomes from the current run.

M01, M02 and M07 must reach C's new Edge entry. M08's four invalid messages must
be rejected by A's mock validator before snapshot checks or any C call. B's Risk
consumer and A's existing `he_adapter.py` are not invoked by this tool, so passing
these checks does not mean three-person integration has passed.
