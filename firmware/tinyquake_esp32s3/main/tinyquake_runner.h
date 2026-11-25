#pragma once
#include <stddef.h>
#include <stdint.h>

// This runner has one interpreter and must be owned by one inference task.
// Inputs are 80 time samples of interleaved E,N,Z float32 values, already
// filtered/resampled/normalized. It neither reads the ICM nor invents calibration.
bool tinyquake_init();
bool tinyquake_infer_preprocessed(const float input[240], float scores[3], int64_t* invoke_us);
size_t tinyquake_arena_used();
// Only upstream's final normalization/int16 step. The caller must first provide
// calibrated, aligned, filtered 40 Hz acceleration in m/s²; this is NOT a full
// raw ICM adaptation pipeline. Invalid/silent/nonpositive-maximum windows reject.
bool tinyquake_normalize_40hz(const float acceleration_enz[240], float output[240]);

extern const unsigned char kTinyQuakeModel[];
extern const size_t kTinyQuakeModelSize;
extern const float kReferenceInputs[3][240];
extern const float kReferenceOutputs[3][3];
extern const int kReferenceIndexes[3];
inline constexpr char kTinyQuakeModelSha256[] = "0e1eb00a920ae3daaec7cf142ef8a54373fe1b93b472350e7048b8ae0c1ff1f1";
