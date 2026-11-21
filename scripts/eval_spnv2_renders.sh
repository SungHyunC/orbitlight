#!/usr/bin/env bash
# 우리가 렌더링한 이미지(outputs/renders/<run>/sunsweep)를 SPNv2 공개 가중치로 평가한다.
#
#   RUN=speedplus_sunsweep_v01 bash scripts/eval_spnv2_renders.sh            # 기본 offline 가중치
#   RUN=speedplus_sunsweep_v01 WEIGHTS="offline odr_B4_N1024" bash scripts/eval_spnv2_renders.sh
#
# 결과: outputs/spnv2_eval_renders/<run>/<weights>/efficientdet_d3/full_config/sunsweep/per_sample_performance.mat
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/_weights.sh"
PY="${PY:-$HOME/anaconda3/envs/orbitlight/bin/python}"
SPN="$ROOT/third_party/spnv2"
CFG="$SPN/experiments/offline_train_full_config_phi3_BN.yaml"
RUN="${RUN:?RUN=<outputs/renders 아래 폴더 이름>}"
# SPNv2는 DATASET.DATANAME에 'speedplus'가 들어 있어야 SPEED+ 형식으로 읽는다 (preprocess.py, SPEEDPLUSDataset.py)
[[ "$RUN" == *speedplus* ]] || { echo "RUN 이름에 'speedplus'가 들어가야 함 (예: speedplus_sunsweep_v01)"; exit 1; }
WEIGHTS="${WEIGHTS:-offline}"
KEYPTS="$SPN/core/utils/models/tangoPoints.mat"
OUT="$ROOT/outputs/spnv2_eval_renders/$RUN"
common=(DATASET.ROOT "$ROOT/outputs/renders" DATASET.DATANAME "$RUN" DATASET.KEYPOINTS "$KEYPTS" DIST.MULTIPROCESSING_DISTRIBUTED False)

# 렌더 폴더가 바뀌었으면 전처리(768×512 축소, CSV 라벨) 다시
DS="$ROOT/outputs/renders/$RUN/sunsweep"
if [[ ! -f "$DS/labels/test.csv" || "$DS/test.json" -nt "$DS/labels/test.csv" ]]; then
    rm -rf "$DS/images_768x512_RGB" "$DS/masks_192x128" "$DS/labels"
    # 기준 평가(eval_spnv2_baseline.sh)와 같게 마스크 없이 전처리 (마스크는 sunsweep/masks/*.png에 따로 있음)
    "$PY" -W ignore "$SPN/tools/preprocess.py" --cfg "$CFG" --jsonfile sunsweep/test.json --no_masks "${common[@]}"
fi

mkdir -p "$OUT"
for w in $WEIGHTS; do
    echo "[test] run=$RUN weights=$w"
    "$PY" -W ignore "$SPN/tools/test.py" --cfg "$CFG" "${common[@]}" \
        VERBOSE False OUTPUT_DIR "$OUT/${w/:/_}" LOG_DIR "$OUT/logs/${w/:/_}" \
        TEST.MODEL_FILE "$(weights_path "$w")" \
        TEST.TEST_CSV sunsweep/labels/test.csv > "$OUT/${w/:/_}.log" 2>&1
    tail -n 12 "$OUT/${w/:/_}.log"
done
