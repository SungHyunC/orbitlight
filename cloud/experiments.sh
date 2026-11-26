#!/usr/bin/env bash
# v0.2 실험을 Modal에서 순서대로 재현하는 명령 모음. 단계별로 골라 실행한다:
#
#   bash cloud/experiments.sh setup        # 데이터 받기·전처리 (CPU), 가중치 업로드
#   bash cloud/experiments.sh baseline     # Phase 1: SPNv2 공개 가중치 평가 (L4)
#   bash cloud/experiments.sh sweep        # Phase 2·3: 태양 실험 6,500장 렌더 → 평가 → 실패 지도
#   bash cloud/experiments.sh selfcheck    # v0.2 ①: 실패 자가 경고
#   bash cloud/experiments.sh trainrender  # 학습용 무작위 재질 렌더 8,000장
#   bash cloud/experiments.sh finetune A   # 미세조정 한 조건 (A, B, C × 시드). 조건마다 다른 터미널에서 동시에
#   bash cloud/experiments.sh orbit        # v0.2 ②: 궤도 한 바퀴 렌더 → 평가 → 분석
#
# 이 맥처럼 modal이 PATH에 없으면 MODAL="uvx --python 3.12 modal" (기본값).
set -euo pipefail
cd "$(dirname "$0")/.."
MODAL="${MODAL:-uvx --python 3.12 modal}"
APP=cloud/modal_app.py
cpu() { $MODAL run "$APP::run_sh" --cmd "$1"; }
gpu() { $MODAL run "$APP::run_sh" --gpu "${GPU:-L4}" --cmd "$1"; }
render() { $MODAL run "$APP::run_render" --run "$1" --chunks "${2:-16}"; }

case "${1:-}" in
setup)
    $MODAL run "$APP::fetch_data"
    for w in offline odr_B4_N1024; do
        $MODAL volume put orbitlight-data ~/Downloads/spnv2_efficientnetb3_fullconfig_$w.pth.tar \
            /outputs/pretrained/spnv2_efficientnetb3_fullconfig_$w.pth.tar || true
    done ;;
baseline)
    gpu "WEIGHTS=offline bash scripts/eval_spnv2_baseline.sh && python scripts/summarize_spnv2_eval.py" ;;
sweep)
    cpu "python scripts/sunsweep.py jobs --run speedplus_sunsweep_v01 --n-poses 100 --sun-strength 4.0"
    render speedplus_sunsweep_v01 16
    cpu "python scripts/sunsweep.py post --run speedplus_sunsweep_v01"
    gpu "RUN=speedplus_sunsweep_v01 bash scripts/eval_spnv2_renders.sh"
    cpu "python scripts/failure_map.py --run speedplus_sunsweep_v01" ;;
selfcheck)
    cpu "python scripts/self_check.py --weights ${W:-offline}" ;;
trainrender)
    cpu "python scripts/sunsweep.py jobs --run speedplus_trainrender_dr_v01 --pose-source synthetic/train.json \
         --n-poses 4000 --random-per-pose 2 --phase-max 170 --strength-range 3,5 --color-depth 8 --seed 1 --randomize-materials"
    render speedplus_trainrender_dr_v01 24
    cpu "python scripts/sunsweep.py post --run speedplus_trainrender_dr_v01" ;;
finetune)
    # A: 비교군 SPEED+ 16,000장 / B: SPEED+ 8,000장 + 무작위 재질 렌더 (Phase 3c)
    # C: SPEED+ 16,000장 + 무작위 재질 렌더. 학습 스텝 수를 A와 맞춤 (23,500장 × 4에폭 ≈ 16,000장 × 6에폭)
    cond="${2:?A|B|C}"; seed="${SEED:-0}"; sfx="v01"; [[ "$seed" != 0 ]] && sfx="v01s$seed"
    case "$cond" in
        A) set_args="--speed-n 16000"; exp="ftctrl_$sfx"; ep=6; step="[4]" ;;
        B) set_args="--speed-n 8000 --renders speedplus_trainrender_dr_v01"; exp="ftdr_$sfx"; ep=6; step="[4]" ;;
        C) set_args="--speed-n 16000 --renders speedplus_trainrender_dr_v01"; exp="ftdrfull_$sfx"; ep=4; step="[3]" ;;
    esac
    data="speedplus_${exp}"
    cpu "python scripts/build_finetune_set.py --name $data $set_args --val-n 500 --seed $seed"
    gpu "DATA=$data EXP=$exp BATCH=4 EPOCHS=$ep LR_STEP='$step' bash scripts/finetune_spnv2.sh > /dev/null \
         && tail -n 3 outputs/finetune/$exp/train.log \
         && WEIGHTS=$exp:final bash scripts/eval_spnv2_baseline.sh \
         && RUN=speedplus_sunsweep_v01 WEIGHTS=$exp:final bash scripts/eval_spnv2_renders.sh" ;;
orbit)
    for hold in vbar- hbar+ hbar- rbar-; do
        run="speedplus_orbit_b30_${hold/-/m}"; run="${run/+/p}"
        cpu "python scripts/orbit_pass.py jobs --run $run --beta 30 --hold $hold --step 15"
        render "$run" 8
        cpu "python scripts/sunsweep.py post --run $run"
        gpu "RUN=$run bash scripts/eval_spnv2_renders.sh"
        cpu "python scripts/orbit_pass.py analyze --run $run"
    done ;;
*)
    sed -n '2,13p' "$0"; exit 1 ;;
esac
