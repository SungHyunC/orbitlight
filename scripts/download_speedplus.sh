#!/usr/bin/env bash
# SPEED+ (Stanford Digital Repository 판, lightbox/sunlamp 라벨 포함 버전) 다운로드.
# 16.93GB. Stanford 서버는 연결 1개당 약 1MB/s로 느려서(한국↔미국 서부, 왕복 지연 약 0.2초)
# 파일을 여러 구간으로 나눠 동시에 받는다. 끊겨도 다시 실행하면 각 구간을 이어 받는다.
#
#   bash scripts/download_speedplus.sh               # 다운로드 + SHA-1 확인 + 압축 해제 + zip 삭제
#   PARALLEL=8 bash scripts/download_speedplus.sh    # 동시 연결 수 (기본 8)
#   KEEP_ZIP=1 bash scripts/download_speedplus.sh    # 압축 해제 후 zip을 지우지 않음
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/data/speedplus"
ZIP="$ROOT/data/speedplusv2.zip"
PARTS="$ROOT/data/speedplusv2.parts"
URL="https://stacks.stanford.edu/file/druid:wv398fc4383/speedplusv2.zip"
SIZE=16928863098
SHA1="2b3173d9cd0da405d359b7303de3913bdd9934ad"   # purl.stanford.edu/wv398fc4383.json 기준
N="${PARALLEL:-8}"

mkdir -p "$ROOT/data"
touch "$ZIP"

have() { stat -c %s "$1" 2>/dev/null || echo 0; }

# 이미 이어 붙인 앞부분(HEAD) 뒤의 나머지를 N개 구간으로 나눈다.
# 구간 경계는 처음 실행할 때 정해 parts/plan 에 저장해서, 다시 실행해도 같은 경계로 이어 받는다.
if [[ "$(have "$ZIP")" -lt "$SIZE" ]]; then
    mkdir -p "$PARTS"
    if [[ ! -f "$PARTS/plan" ]]; then
        head_size=$(have "$ZIP")
        python3 - "$head_size" "$SIZE" "$N" > "$PARTS/plan" <<'EOF'
import sys
start, size, n = map(int, sys.argv[1:])
step = -(-(size - start) // n)
for i in range(n):
    a = start + i * step
    b = min(size, a + step) - 1
    if a <= b:
        print(i, a, b)
EOF
        echo "[plan] 앞부분 $head_size B 유지, 나머지를 $(wc -l < "$PARTS/plan")개 구간으로 나눔"
    fi

    pids=()
    while read -r i a b; do
        part="$PARTS/part.$i"
        want=$((b - a + 1))
        got=$(have "$part")
        if [[ "$got" -lt "$want" ]]; then
            ( for try in 1 2 3 4 5 6 7 8 9 10; do
                  got=$(have "$part")
                  [[ "$got" -ge "$want" ]] && exit 0
                  curl -fsSL -r "$((a + got))-$b" "$URL" >> "$part" && exit 0
                  sleep 10
              done; exit 1 ) &
            pids+=($!)
        fi
    done < "$PARTS/plan"
    echo "[download] 동시 연결 ${#pids[@]}개로 받는 중..."
    fail=0
    for p in "${pids[@]}"; do wait "$p" || fail=1; done
    [[ "$fail" -eq 0 ]] || { echo "[error] 일부 구간 실패. 다시 실행하면 이어 받는다." >&2; exit 1; }

    # 구간 크기 확인 후 순서대로 이어 붙인다
    while read -r i a b; do
        [[ "$(have "$PARTS/part.$i")" -eq $((b - a + 1)) ]] || { echo "[error] part.$i 크기 불일치" >&2; exit 1; }
    done < "$PARTS/plan"
    while read -r i a b; do cat "$PARTS/part.$i" >> "$ZIP"; done < "$PARTS/plan"
    rm -rf "$PARTS"
fi

[[ "$(have "$ZIP")" -eq "$SIZE" ]] || { echo "[error] zip 크기 $(have "$ZIP") != $SIZE" >&2; exit 1; }

echo "[verify] SHA-1 확인 중..."
echo "$SHA1  $ZIP" | sha1sum -c -

echo "[extract] $DEST"
mkdir -p "$DEST"
unzip -q -o "$ZIP" -d "$DEST"

if [[ "${KEEP_ZIP:-0}" != "1" ]]; then
    rm -f "$ZIP"
    echo "[cleanup] zip 삭제 (KEEP_ZIP=1이면 유지)"
fi

du -sh "$DEST"
find "$DEST" -maxdepth 3 -name '*.json' | sort
