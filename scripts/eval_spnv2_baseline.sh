#!/usr/bin/env bash
# Phase 1 기준 성능: SPNv2 공개 가중치(φ=3 BN)를 SPEED+ 합성 검증셋 / lightbox / sunlamp에서 평가한다.
#
#   bash scripts/eval_spnv2_baseline.sh                 # 전처리(없으면) + 평가 6회
#   DOMAINS="lightbox" WEIGHTS="offline" bash scripts/eval_spnv2_baseline.sh
#
# 전제: data/speedplus/{synthetic,lightbox,sunlamp}/ 와 각 도메인의 라벨 JSON,
#       outputs/pretrained/spnv2_efficientnetb3_fullconfig_{offline,odr_B4_N1024}.pth.tar
# 결과: outputs/spnv2_eval/logs/.../mean_performance.txt  (요약은 scripts/summarize_spnv2_eval.py)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/_weights.sh"
PY="${PY:-$HOME/anaconda3/envs/orbitlight/bin/python}"
SPN="$ROOT/third_party/spnv2"
CFG="$SPN/experiments/offline_train_full_config_phi3_BN.yaml"
DS="$ROOT/data/speedplus"             # DATASET.ROOT
DN="speedplusv2"                       # DATASET.DATANAME (zip 안의 폴더 이름)
KEYPTS="$SPN/core/utils/models/tangoPoints.mat"
OUT="$ROOT/outputs/spnv2_eval"

DOMAINS="${DOMAINS:-synthetic lightbox sunlamp}"
WEIGHTS="${WEIGHTS:-offline odr_B4_N1024}"

# 도메인별 라벨 JSON 경로 (data/speedplus/speedplusv2 기준). 압축 해제 후 실제 파일명을 확인해서 맞춘 값.
declare -A JSON=(
    [synthetic]="${JSON_SYNTHETIC:-synthetic/validation.json}"
    [lightbox]="${JSON_LIGHTBOX:-lightbox/test.json}"
    [sunlamp]="${JSON_SUNLAMP:-sunlamp/test.json}"
)

mkdir -p "$OUT"
common=(DATASET.ROOT "$DS" DATASET.DATANAME "$DN" DATASET.KEYPOINTS "$KEYPTS" DIST.MULTIPROCESSING_DISTRIBUTED False)

for d in $DOMAINS; do
    json="${JSON[$d]}"
    csv="$d/labels/$(basename "${json%.json}").csv"
    if [[ ! -f "$DS/$DN/$csv" || ! -d "$DS/$DN/$d/images_768x512_RGB" ]]; then
        echo "[preprocess] $d ($json) -> $csv"
        "$PY" -W ignore "$SPN/tools/preprocess.py" --cfg "$CFG" --jsonfile "$json" --no_masks "${common[@]}"
    fi
done

for w in $WEIGHTS; do
    model="$(weights_path "$w")"
    for d in $DOMAINS; do
        json="${JSON[$d]}"
        csv="$d/labels/$(basename "${json%.json}").csv"
        echo "[test] weights=$w domain=$d"
        "$PY" -W ignore "$SPN/tools/test.py" --cfg "$CFG" "${common[@]}" \
            VERBOSE False \
            OUTPUT_DIR "$OUT/${w/:/_}" LOG_DIR "$OUT/logs/${w/:/_}" \
            TEST.MODEL_FILE "$model" TEST.TEST_CSV "$csv" \
            > "$OUT/${w/:/_}.$d.log" 2>&1
        tail -n 20 "$OUT/${w/:/_}.$d.log"
    done
done
