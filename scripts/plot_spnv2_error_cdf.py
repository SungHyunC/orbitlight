"""SPNv2 기준 평가의 이미지별 회전 오차 분포(누적 분포, CDF)를 그리고 요약 통계를 낸다.

    python scripts/plot_spnv2_error_cdf.py                 # outputs/figures/spnv2_rotation_error_cdf.png
    python scripts/plot_spnv2_error_cdf.py --weights odr_B4_N1024

회전 오차는 heatmap 헤드(키포인트 + PnP) 기준. 자세 계산을 포기한(reject) 이미지는 SPNv2가 제외한다.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.io import loadmat  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "outputs" / "spnv2_eval"
DOMAINS = ["synthetic", "lightbox", "sunlamp"]
LABELS = {"synthetic": "Synthetic (validation)", "lightbox": "Lightbox (HIL)", "sunlamp": "Sunlamp (HIL)"}
# 기본 범주형 팔레트 1~3번 슬롯 (dataviz skill references/palette.md, light mode)
COLORS = {"synthetic": "#2a78d6", "lightbox": "#eb6834", "sunlamp": "#1baf7a"}
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
THRESHOLDS = (5.0, 10.0, 20.0)  # [deg]


def load(weights: str, domain: str) -> dict[str, np.ndarray]:
    f = EVAL / weights / "efficientdet_d3" / "full_config" / domain / "per_sample_performance.mat"
    m = loadmat(f)
    return {k: np.ravel(v) for k, v in m.items() if not k.startswith("__")}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--weights", default="offline")
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    out = args.out or ROOT / "outputs" / "figures" / f"spnv2_rotation_error_cdf_{args.weights}.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 4.8), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    print(f"weights={args.weights}")
    print("| 도메인 | 이미지 수 | 거부 | 회전 오차 중앙값 [°] | 90% 지점 [°] | " +
          " | ".join(f"> {t:g}° 비율" for t in THRESHOLDS) + " |")
    print("|---|---|---|---|---|" + "---|" * len(THRESHOLDS))
    for d in DOMAINS:
        m = load(args.weights, d)
        e = np.sort(m["heat_eR"][np.isfinite(m["heat_eR"])])
        n_total = len(m["h_reject"])
        y = np.arange(1, len(e) + 1) / n_total  # 거부된 이미지는 '실패'로 남겨 둠 (곡선이 1에 못 미침)
        ax.step(e, y, where="post", color=COLORS[d], lw=2, label=LABELS[d])
        med = np.median(e)
        fracs = [(np.sum(e > t) + int(m["h_reject"].sum())) / n_total for t in THRESHOLDS]
        print(f"| {d} | {n_total:,} | {int(m['h_reject'].sum())} | {med:.2f} | {np.quantile(e, 0.9):.2f} | " +
              " | ".join(f"{f * 100:.1f}%" for f in fracs) + " |")

    for t in (10.0,):
        ax.axvline(t, color=INK2, lw=1, ls=(0, (3, 3)))
        ax.text(t, 0.03, f" {t:g}°", color=INK2, fontsize=8)
    ax.set_xscale("log")
    ax.set_xlim(0.1, 180)
    ax.set_ylim(0, 1.0)
    ax.set_xlabel("Rotation error per image [deg] (log scale)", color=INK2)
    ax.set_ylabel("Fraction of images ≤ error", color=INK2)
    ax.set_title(f"SPNv2 (φ=3, {args.weights} weights): synthetic → hardware-in-the-loop gap",
                 color=INK, fontsize=11, loc="left")
    ax.grid(True, which="major", color=GRID, lw=0.8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    leg = ax.legend(loc="lower right", frameon=False, fontsize=9)
    for t in leg.get_texts():
        t.set_color(INK)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
