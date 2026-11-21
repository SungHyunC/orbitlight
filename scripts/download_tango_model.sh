#!/usr/bin/env bash
# Tango 위성 3D 모형을 SPIN 시뮬레이터 저장소(vpulab/SPIN, GPL-3.0)에서 받아 data/models/spin_tango/에 둔다 (git 제외).
# 모형 파일은 GPL-3.0이라 이 저장소에 넣어 재배포하지 않는다. 고정 커밋에서 받는다.
#
#   bash scripts/download_tango_model.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SHA="${SPIN_COMMIT:-26bd56f7d7a1d1cfe680f4e26875054aa19c2e31}"
D="$ROOT/data/models/spin_tango"
mkdir -p "$D"
base="https://raw.githubusercontent.com/vpulab/SPIN/$SHA"
curl -fsSL -o "$D/tango_fix.obj" "$base/Assets/Models/tango_fix.obj"
curl -fsSL -o "$D/LICENSE" "$base/LICENSE"
echo "$SHA" > "$D/SOURCE_COMMIT"
# 받은 파일 확인 (2026-11-21 기준 2,785,376 B)
echo "162fc7a10283da0a0816c17add9747b272fa7d36d6c7cc2167b40290fc5e9881  $D/tango_fix.obj" | sha256sum -c -
echo "ok -> $D/tango_fix.obj"
