/* On-board TEST_ONLY arithmetic self-test, with no sensor or alarm drivers. */
#include <math.h>
#include <stdio.h>
#include "soil_baseline.h"

void app_main(void) {
    const float test_only_vwc[SOIL_MODEL_HISTORY] = {0.20f, 0.21f, 0.23f, 0.25f};
    /* NumPy float64 model reference for the same binary32 inputs. */
    const float expected = 0.25494769f;
    float predicted = 0.0f;
    soil_model_status status = soil_model_predict_vwc(test_only_vwc, SOIL_MODEL_HISTORY, &predicted);
    if (status != SOIL_MODEL_OK || fabsf(predicted - expected) > 0.0000005f) {
        printf("SOIL_BASELINE_SELF_TEST FAIL status=%d predicted=%.8f\n", (int)status, (double)predicted);
        return;
    }
    printf("SOIL_BASELINE_SELF_TEST PASS next_vwc=%.8f\n", (double)predicted);
    printf("TEST_ONLY arithmetic replay; sensor calibration and hardware sampling are not tested.\n");
}
