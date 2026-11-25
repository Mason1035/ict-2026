#include "tinyquake_runner.h"
#include <algorithm>
#include <cmath>
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "sdkconfig.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

namespace {
constexpr char kTag[] = "tinyquake";
tflite::MicroInterpreter* interpreter = nullptr;
}

bool tinyquake_init() {
    if (interpreter) return true;
    const auto* model = tflite::GetModel(kTinyQuakeModel);
    if (model->version() != TFLITE_SCHEMA_VERSION) return false;
    static tflite::MicroMutableOpResolver<5> resolver;
    if (resolver.AddConv2D() != kTfLiteOk || resolver.AddMaxPool2D() != kTfLiteOk ||
        resolver.AddReshape() != kTfLiteOk || resolver.AddFullyConnected() != kTfLiteOk ||
        resolver.AddSoftmax() != kTfLiteOk) return false;
    auto* arena = static_cast<uint8_t*>(heap_caps_aligned_alloc(16, CONFIG_TINYQUAKE_ARENA_BYTES, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    if (!arena) { ESP_LOGE(kTag,"Cannot reserve internal arena; inference disabled"); return false; }
    static tflite::MicroInterpreter instance(model, resolver, arena, CONFIG_TINYQUAKE_ARENA_BYTES);
    if (instance.AllocateTensors() != kTfLiteOk) return false;
    const auto* input = instance.input(0); const auto* output = instance.output(0);
    if (input->type != kTfLiteFloat32 || input->dims->size != 4 ||
        input->dims->data[0] != 1 || input->dims->data[1] != 80 ||
        input->dims->data[2] != 3 || input->dims->data[3] != 1 || input->bytes != 960 ||
        output->type != kTfLiteFloat32 || output->dims->size != 2 ||
        output->dims->data[0] != 1 || output->dims->data[1] != 3 || output->bytes != 12) return false;
    interpreter = &instance;
    ESP_LOGI(kTag,"model=%s bytes=%u arena_capacity=%u arena_used=%u",kTinyQuakeModelSha256,
             static_cast<unsigned>(kTinyQuakeModelSize),CONFIG_TINYQUAKE_ARENA_BYTES,static_cast<unsigned>(instance.arena_used_bytes()));
    return true;
}

bool tinyquake_infer_preprocessed(const float input[240], float scores[3], int64_t* invoke_us) {
    if (!interpreter || !input || !scores || !invoke_us) return false;
    for (int i=0;i<240;++i) { if (!std::isfinite(input[i])) return false; interpreter->input(0)->data.f[i]=input[i]; }
    const int64_t started = esp_timer_get_time();
    if (interpreter->Invoke() != kTfLiteOk) return false;
    *invoke_us = esp_timer_get_time()-started;
    float sum=0;
    for (int i=0;i<3;++i) { scores[i]=interpreter->output(0)->data.f[i]; if (!std::isfinite(scores[i]) || scores[i]<0 || scores[i]>1) return false; sum+=scores[i]; }
    return std::abs(sum-1.0f)<.001f;
}

size_t tinyquake_arena_used() { return interpreter ? interpreter->arena_used_bytes() : 0; }

bool tinyquake_normalize_40hz(const float acceleration[240], float output[240]) {
    if (!acceleration || !output) return false;
    float peak=0, positive_peak=-INFINITY;
    for (int i=0;i<240;++i) { if (!std::isfinite(acceleration[i])) return false; peak=std::max(peak,std::abs(acceleration[i])); positive_peak=std::max(positive_peak,acceleration[i]); }
    if (peak<=1e-8f || peak>=2.0f*9.81f || positive_peak<=0) return false;
    float normalized_peak=0;
    for (int i=0;i<240;++i) { output[i]=acceleration[i]/positive_peak; normalized_peak=std::max(normalized_peak,std::abs(output[i])); }
    const float factor=32767.0f/normalized_peak;
    float final_peak=0;
    for (int i=0;i<240;++i) {
        const float scaled=std::clamp(output[i]*factor,-32767.0f,32767.0f);
        output[i]=static_cast<float>(static_cast<int16_t>(scaled));
        final_peak=std::max(final_peak,output[i]);
    }
    if (final_peak<=0) return false;
    for (int i=0;i<240;++i) output[i]/=final_peak;
    return true;
}
