#!/usr/bin/env bash
# SPNv2 공개 가중치(offline, φ=3 BN)에서 시작해 미세조정(fine-tuning)한다.
#
#   DATA=speedplus_ft_v01 EXP=ft_v01 bash scripts/finetune_spnv2.sh
#   DATA=speedplus_ftsmoke EXP=smoke EPOCHS=1 bash scripts/finetune_spnv2.sh     # 동작 확인용
#
# 학습 데이터: outputs/renders/$DATA/mix (scripts/build_finetune_set.py)
# 결과: outputs/finetune/$EXP/ (체크포인트 model_best.pth.tar / model_final.pth.tar, 로그)
#
# 원래 SPNv2 학습 설정과 다른 점 (이유):
# - 스타일 증강(AUGMENT.APPLY_TEXTURE_RANDOMIZATION) 끔: 미리 만든 스타일 이미지 폴더가 공개돼 있지 않음
# - GPU 1장, 분산 학습 끔
# - 학습률 1e-4 (원래 1e-3의 1/10), 에폭 수 적게: 처음부터가 아니라 공개 가중치에서 이어서 학습하므로
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PY:-$HOME/anaconda3/envs/orbitlight/bin/python}"
SPN="$ROOT/third_party/spnv2"
CFG="$SPN/experiments/offline_train_full_config_phi3_BN.yaml"
DATA="${DATA:?DATA=<outputs/renders 아래 학습 폴더>}"
EXP="${EXP:?EXP=<실험 이름>}"
EPOCHS="${EPOCHS:-6}"
LR="${LR:-1.0e-4}"
LR_STEP="${LR_STEP:-[4]}"
BATCH="${BATCH:-8}"
WORKERS="${WORKERS:-8}"
INIT="${INIT:-$ROOT/outputs/pretrained/spnv2_efficientnetb3_fullconfig_offline.pth.tar}"
OUT="$ROOT/outputs/finetune/$EXP"
mkdir -p "$OUT"

"$PY" -W ignore "$SPN/tools/train.py" --cfg "$CFG" \
    DATASET.ROOT "$ROOT/outputs/renders" DATASET.DATANAME "$DATA" \
    DATASET.KEYPOINTS "$SPN/core/utils/models/tangoPoints.mat" \
    DIST.MULTIPROCESSING_DISTRIBUTED False \
    OUTPUT_DIR "$OUT/out" LOG_DIR "$OUT/logs" \
    MODEL.PRETRAIN_FILE "$INIT" \
    AUGMENT.APPLY_TEXTURE_RANDOMIZATION False \
    TRAIN.TRAIN_CSV mix/labels/train.csv TRAIN.VAL_CSV mix/labels/val.csv \
    TRAIN.BEGIN_EPOCH 0 TRAIN.END_EPOCH "$EPOCHS" TRAIN.LR "$LR" TRAIN.LR_STEP "$LR_STEP" \
    TRAIN.IMAGES_PER_GPU "$BATCH" TRAIN.WORKERS "$WORKERS" TRAIN.VALID_FRACTION 1.0 \
    2>&1 | tee "$OUT/train.log"
