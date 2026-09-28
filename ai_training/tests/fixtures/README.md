# TEST_ONLY — NOT_REAL_DATA — NOT_PROJECT_TRAINING_DATA

`test_only_contract.json` is NOT_PROJECT_CONTRACT and NOT_APPROVED_BY_B.
`toy.py` supplies two artificial dimensionless values per timestep, a scalar toy
target, a tiny NumPy model, injected stochastic optimizer, identity normalizer and
toy validation metric/best policy. None is a project scientific choice or default.

Only explicit software self-tests import these fixtures. They are not installed
as part of `src/ai_training`. Toy loss/metric values have **no project scientific
meaning** and do not measure real-world disaster warning performance.

`test_provenance.py` also constructs a tiny TEST_ONLY simulator-shaped lineage
envelope in pytest's temporary directory. It is not a simulator scenario dataset,
real experiment artifact or approved training dataset.
