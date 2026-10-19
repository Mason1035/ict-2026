/* Synthetic TEST_ONLY arithmetic example, not a connected sensor reading. */
#include <stdio.h>
#include "soil_baseline.h"

int main(void) {
    const float test_only_vwc[SOIL_MODEL_HISTORY] = {0.20f, 0.21f, 0.23f, 0.25f};
    soil_model_state state;
    float predicted = 0.0f;
    size_t i;
    soil_model_reset(&state);
    for (i = 0; i < SOIL_MODEL_HISTORY; ++i) {
        soil_model_status status = soil_model_push_vwc(&state, test_only_vwc[i], 1, &predicted);
        if (status == SOIL_MODEL_WARMUP) continue;
        if (status != SOIL_MODEL_OK) return 1;
        printf("TEST_ONLY next recorded VWC = %.8f (fraction)\n", (double)predicted);
    }
    printf("parameters=%zu bytes, per-sensor state=%zu bytes\n",
           sizeof(soil_model_weights) + sizeof(soil_model_bias), sizeof(state));
    return 0;
}
