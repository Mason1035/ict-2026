#!/usr/bin/env bash
# Board notes (verified 2026-10-20): run as root (OPP vendor files are not
# readable by HwHiAiUser); one ATC at a time (3.4G RAM); ~10 min per model.
set -euo pipefail
# Ascend's environment script may read unset variables.
set +u
source /usr/local/Ascend/ascend-toolkit/set_env.sh
set -u
# ATC/TBE needs the vendor conda Python (has numpy/decorator/sympy); the
# Ubuntu system python3 lacks them (EC0010 import failures).
export PATH="/usr/local/miniconda3/bin:$PATH"
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
atc --help >/dev/null 2>&1 && echo "atc binary OK (this build has no --version flag)"
for branch in soil motion; do
    shape='history:1,4,1'
    if [[ "$branch" == motion ]]; then shape='history:1,8,6'; fi
    atc --model="${branch}_forecaster.onnx" --framework=5 \
        --soc_version=Ascend310B4 --input_shape="$shape" --input_format=ND \
        --output="${branch}_forecaster" --precision_mode=force_fp32
 done
