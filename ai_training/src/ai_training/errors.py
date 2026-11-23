"""Explicit failures with cause and remediation; never fall back to guessed rules."""


class FrameworkError(ValueError):
    pass


class ContractNotReadyError(FrameworkError):
    pass


class FormalTrainingNotAllowedError(ContractNotReadyError):
    """A test artifact must never be promoted by changing a caller's mode."""


class LeakageError(FrameworkError):
    pass


class IntegrityError(FrameworkError):
    pass
