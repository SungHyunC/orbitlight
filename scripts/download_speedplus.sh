#!/usr/bin/env bash
# SPEED+ (Stanford Digital Repository 판, lightbox/sunlamp 라벨 포함 버전) 다운로드.
# 16.93GB. 끊겨도 다시 실행하면 이어 받는다 (curl -C -).
#
#   bash scripts/download_speedplus.sh            # 다운로드 + SHA-1 확인 + 압축 해제 + zip 삭제
#   KEEP_ZIP=1 bash scripts/download_speedplus.sh # 압축 해제 후 zip을 지우지 않음
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/data/speedplus"
ZIP="$ROOT/data/speedplusv2.zip"
URL="https://stacks.stanford.edu/file/druid:wv398fc4383/speedplusv2.zip"
SIZE=16928863098
SHA1="2b3173d9cd0da405d359b7303de3913bdd9934ad"   # purl.stanford.edu/wv398fc4383.json 기준

mkdir -p "$ROOT/data"

if [[ ! -f "$ZIP" || "$(stat -c %s "$ZIP")" -lt "$SIZE" ]]; then
    echo "[download] $URL -> $ZIP"
    curl -fL -C - --retry 5 --retry-delay 10 -sS -o "$ZIP" "$URL"
fi

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
