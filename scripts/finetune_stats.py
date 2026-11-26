"""미세조정 모델끼리 같은 이미지로 짝지어 비교(McNemar 검정)하고, 시드를 바꾼 반복 학습의 편차를 본다.

    python scripts/finetune_stats.py \
        --pair ftdrfull_v01:final ftctrl_v01:final --pair ftdrfull_v01s1:final ftctrl_v01s1:final \
        --seeds ftctrl_v01:final,ftctrl_v01s1:final --seeds ftdrfull_v01:final,ftdrfull_v01s1:final

McNemar: 두 모델 중 한쪽만 실패한 이미지 수(b, c)로 정확 이항 검정(양측). 실패 = 회전 오차 10° 초과 또는 거부.
도메인: lightbox, sunlamp(실물 조명), 합성 검증, 태양 실험 렌더.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from orbitlight.eval.spnv2_results import failed, load_per_sample  # noqa: E402

RUN = "speedplus_sunsweep_v01"


def fails(w: str, dom: str) -> np.ndarray | None:
    wd = w.replace(":", "_")
    if dom == "renders":
        f = ROOT / "outputs" / "spnv2_eval_renders" / RUN / wd / "efficientdet_d3" / "full_config" / "sunsweep" / "per_sample_performance.mat"
    else:
        f = ROOT / "outputs" / "spnv2_eval" / wd / "efficientdet_d3" / "full_config" / dom / "per_sample_performance.mat"
    return failed(load_per_sample(f)) if f.exists() else None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pair", nargs=2, action="append", default=[], metavar=("A", "B"))
    p.add_argument("--seeds", action="append", default=[], help="쉼표로 나눈 같은 조건의 가중치들")
    a = p.parse_args()
    doms = ["lightbox", "sunlamp", "synthetic", "renders"]
    out = dict(pairs=[], seeds=[])
    print("| 비교 (A vs B) | 도메인 | A 실패 | B 실패 | A만 실패 | B만 실패 | p (McNemar) |")
    print("|---|---|---|---|---|---|---|")
    for A, B in a.pair:
        for d in doms:
            fa, fb = fails(A, d), fails(B, d)
            if fa is None or fb is None:
                continue
            b, c = int((fa & ~fb).sum()), int((fb & ~fa).sum())
            pv = binomtest(min(b, c), b + c, 0.5).pvalue if b + c else 1.0
            out["pairs"].append(dict(a=A, b=B, domain=d, fail_a=float(fa.mean()), fail_b=float(fb.mean()), only_a=b, only_b=c, p=pv))
            print(f"| {A} vs {B} | {d} | {fa.mean():.1%} | {fb.mean():.1%} | {b} | {c} | {pv:.2g} |")
    print("\n| 조건(시드들) | 도메인 | 실패율 (시드별) | 평균 | 범위 |")
    print("|---|---|---|---|---|")
    for grp in a.seeds:
        ws = grp.split(",")
        for d in doms:
            vals = [fails(w, d) for w in ws]
            if any(v is None for v in vals):
                continue
            r = [float(v.mean()) for v in vals]
            out["seeds"].append(dict(weights=ws, domain=d, rates=r))
            print(f"| {' / '.join(ws)} | {d} | {' · '.join(f'{x:.1%}' for x in r)} | {np.mean(r):.1%} | {max(r) - min(r):.1%}p |")
    dst = ROOT / "outputs" / "failure_map" / "finetune_stats.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=1))
    print(f"\n-> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
