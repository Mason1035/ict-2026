"""Future export requirements only; status cannot become SUCCESS in this skeleton."""

from dataclasses import dataclass, asdict

from ai_training.errors import ContractNotReadyError


@dataclass(frozen=True)
class ONNXExportManifest:
    model_version: str | None = None
    checkpoint_hash: str | None = None
    feature_version: str | None = None
    ordered_features: tuple[str, ...] | None = None
    input_name: str | None = None
    output_name: str | None = None
    input_dtype: str | None = None
    input_shape: tuple | None = None
    dynamic_axes_policy: dict | None = None
    mask_semantics: dict | None = None
    normalization_artifact: dict | None = None
    opset: int | None = None
    export_framework_version: str | None = None
    onnx_hash: str | None = None
    status: str = "NOT_RUN"

    def __post_init__(self):
        # Providing dimensions is not evidence that an exporter/parity test ran.
        if self.status != "NOT_RUN" or self.onnx_hash is not None:
            raise ContractNotReadyError("ONNX export NOT_RUN: no exporter/approved model contract; cannot claim success")

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ONNXParityResult:
    status: str = "NOT_RUN"
    input_artifact_hash: str | None = None
    framework_output_hash: str | None = None
    onnx_output_hash: str | None = None
    tolerance_contract: dict | None = None
    max_error: float | None = None

    def __post_init__(self):
        if self.status != "NOT_RUN" or self.max_error is not None:
            raise ContractNotReadyError("ONNX parity NOT_RUN: no runtime comparison; provide approved test inputs and tolerances in a future implementation")
