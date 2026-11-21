# 가중치 이름 → 파일 경로. eval 스크립트에서 source 해서 쓴다.
#   offline, odr_B4_N1024            → outputs/pretrained/spnv2_efficientnetb3_fullconfig_<이름>.pth.tar (저자 공개)
#   그 밖의 이름(예: ft_v01)          → outputs/finetune/<이름>/out/efficientdet_d3/full_config/model_best.pth.tar
#                                       (미세조정 결과. 검증셋 점수로 고른 모델. 끝 에폭을 쓰려면 이름 뒤에 :final)
weights_path() {
    local w="${1%%:*}" which="best"
    [[ "$1" == *:final ]] && which="final"
    local pre="$ROOT/outputs/pretrained/spnv2_efficientnetb3_fullconfig_${w}.pth.tar"
    local ft="$ROOT/outputs/finetune/${w}/out/efficientdet_d3/full_config/model_${which}.pth.tar"
    if [[ -f "$pre" ]]; then echo "$pre"
    elif [[ -f "$ft" ]]; then echo "$ft"
    else echo "가중치를 찾지 못함: $1 ($pre 또는 $ft)" >&2; return 1
    fi
}
