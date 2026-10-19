"""Export the VWC ridge baseline as a standalone, allocation-free C99 header."""

import numpy as np

from .forecast import RidgeForecaster


def render_soil_header(model: RidgeForecaster) -> str:
    """Fold train-only normalization into float32 coefficients for MCU inference.

    This exports arithmetic, not a calibrated ADC adapter or an alarm classifier.
    The caller owns sensor identity, sequence boundaries and observation timing.
    """
    if (model.modality != "soil" or model.channels != 1
            or model.channel_names != ("vwc",) or model.units != ("1",)
            or model.time_unit != "source_relative_time"
            or not 2 <= model.history_length <= 64):
        raise ValueError("C export requires a single VWC-fraction soil model with native source time and history 2..64")
    weights = model.coefficients[:, 0] / model.scale
    bias = model.delta_mean[0] - model.mean @ weights
    parameters = np.concatenate((weights, [bias]))
    if not np.isfinite(parameters).all() or np.any(np.abs(parameters) > np.finfo(np.float32).max):
        raise ValueError("folded parameters are not representable as finite float32")
    parameters = parameters.astype(np.float32)

    def literal(value):
        return f"{float(value):.9e}f"

    constants = ", ".join(literal(value) for value in parameters[:-1])
    return _HEADER.replace("@HISTORY@", str(model.history_length)).replace(
        "@WEIGHTS@", constants).replace("@BIAS@", literal(parameters[-1]))


_HEADER = """/* Generated from the trained soil_model.json; do not hand-edit weights.
 * LISA data: Longoni et al., Politecnico di Milano and collaborators.
 * https://doi.org/10.7910/DVN/0H4AVF (CC BY 4.0).
 * Normalization folded into coefficients; float64 -> float32 export.
 * Research baseline: next recorded VWC observation, no fixed time horizon.
 * Local sensor calibration / board validation / alarm thresholds: NOT DONE.
 */
#ifndef ZHIFANG_SOIL_BASELINE_H
#define ZHIFANG_SOIL_BASELINE_H

#include <float.h>
#include <math.h>
#include <stddef.h>

#if FLT_RADIX != 2 || FLT_MANT_DIG != 24
#error "soil_baseline requires IEEE-style binary32 float"
#endif
#if defined(__FAST_MATH__)
#error "soil_baseline non-finite checks require fast-math to be disabled"
#endif
typedef char soil_model_float_size_check[(sizeof(float) == 4) ? 1 : -1];

#define SOIL_MODEL_HISTORY @HISTORY@u
#define SOIL_MODEL_PARAMETER_COUNT (SOIL_MODEL_HISTORY + 1u)
#define SOIL_MODEL_LOCAL_HARDWARE_VALIDATED 0

typedef enum {
    SOIL_MODEL_OK = 0,
    SOIL_MODEL_WARMUP = 1,
    SOIL_MODEL_INVALID_INPUT = -1,
    SOIL_MODEL_OUT_OF_RANGE = -2,
    SOIL_MODEL_NUMERIC_ERROR = -3
} soil_model_status;

/* Constant parameters stay in read-only storage; no heap or ML runtime. */
static const float soil_model_weights[SOIL_MODEL_HISTORY] = {@WEIGHTS@};
static const float soil_model_bias = @BIAS@;

/* history: oldest -> newest, one calibrated sensor, fraction 0..1 (0.32=32%).
 * Caller must ensure increasing timestamps and suitable observation intervals.
 * next_vwc is written ONLY on OK. Check the return code before using it.
 * Out-of-range predictions are rejected, never silently clipped.
 * Do not compile with -ffast-math; non-finite input checks are required.
 */
static inline soil_model_status soil_model_predict_vwc(
    const float *history, size_t count, float *next_vwc) {
    size_t i;
    float prediction;
    if (history == NULL || next_vwc == NULL || count != SOIL_MODEL_HISTORY)
        return SOIL_MODEL_INVALID_INPUT;
    for (i = 0; i < count; ++i) {
        if (!isfinite(history[i])) return SOIL_MODEL_INVALID_INPUT;
        if (history[i] < 0.0f || history[i] > 1.0f)
            return SOIL_MODEL_OUT_OF_RANGE;
    }
    prediction = history[count - 1u] + soil_model_bias;
    for (i = 0; i < count; ++i) {
        const float feature = i == 0u ? history[count - 1u] : history[i] - history[i - 1u];
        prediction += feature * soil_model_weights[i];
    }
    if (!isfinite(prediction)) return SOIL_MODEL_NUMERIC_ERROR;
    if (prediction < 0.0f || prediction > 1.0f) return SOIL_MODEL_OUT_OF_RANGE;
    *next_vwc = prediction;
    return SOIL_MODEL_OK;
}

/* Keep a SEPARATE state for each sensor. Reset at a new run, missed/invalid
 * observation, time rollback, sensor replacement or calibration change.
 * This buffer does not establish a sampling rate or validate timestamps.
 */
typedef struct {
    float history[SOIL_MODEL_HISTORY];
    unsigned count;
} soil_model_state;

static inline void soil_model_reset(soil_model_state *state) {
    size_t i;
    if (state == NULL) return;
    for (i = 0; i < SOIL_MODEL_HISTORY; ++i) state->history[i] = 0.0f;
    state->count = 0u;
}

static inline soil_model_status soil_model_push_vwc(
    soil_model_state *state, float vwc, int valid, float *next_vwc) {
    size_t i;
    if (state == NULL || next_vwc == NULL) return SOIL_MODEL_INVALID_INPUT;
    if (state->count > SOIL_MODEL_HISTORY || !valid || !isfinite(vwc)) {
        soil_model_reset(state);
        return SOIL_MODEL_INVALID_INPUT;
    }
    if (vwc < 0.0f || vwc > 1.0f) {
        soil_model_reset(state);
        return SOIL_MODEL_OUT_OF_RANGE;
    }
    if (state->count == SOIL_MODEL_HISTORY) {
        for (i = 1; i < SOIL_MODEL_HISTORY; ++i)
            state->history[i - 1u] = state->history[i];
        --state->count;
    }
    state->history[state->count++] = vwc;
    if (state->count < SOIL_MODEL_HISTORY) return SOIL_MODEL_WARMUP;
    return soil_model_predict_vwc(state->history, SOIL_MODEL_HISTORY, next_vwc);
}

#endif /* ZHIFANG_SOIL_BASELINE_H */
"""
