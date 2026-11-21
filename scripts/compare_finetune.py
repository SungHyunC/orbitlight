"""미세조정 전후 비교: SPEED+ 세 도메인 점수 + 태양 각도 실험(sunsweep) 실패율.

    python scripts/compare_finetune.py --weights offline ft_v01:final ftctrl_v01:final \
        --labels "Public weights (offline)" "Fine-tuned: + OrbitLight renders" "Control: SPEED+ only"

전제: 각 가중치로 scripts/eval_spnv2_baseline.sh (WEIGHTS=...) 와 scripts/eval_spnv2_renders.sh 를 돌려 둔 상태.
출력: 마크다운 표(stdout), outputs/figures/finetune_compare_<run>.png, outputs/failure_map/finetune_compare_<run>.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from orbitlight.eval.spnv2_results import failed, load_per_sample  # noqa: E402
from summarize_spnv2_eval import parse  # noqa: E402

DOMAINS = ["synthetic", "lightbox", "sunlamp"]
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#a35bd6"]   # dataviz 기본 범주형 1~4번 (고정 순서)
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def full_config(base: Path) -> Path:
    return base / "efficientdet_d3" / "full_config"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--weights", nargs="+", required=True)
    p.add_argument("--labels", nargs="+")
    p.add_argument("--run", default="speedplus_sunsweep_v01")
    a = p.parse_args()
    labels = a.labels or a.weights
    assert len(labels) == len(a.weights)

    rows_meta = list(csv.DictReader(open(ROOT / "outputs" / "renders" / a.run / "sunsweep" / "meta.csv")))
    phase = np.array([float(r["phase_deg"]) for r in rows_meta])
    pose = np.array([int(r["pose_id"]) for r in rows_meta])
    phases = sorted(set(phase))

    table, curves = [], {}
    for w, lab in zip(a.weights, labels):
        wd = w.replace(":", "_")
        row = dict(weights=w, label=lab)
        for d in DOMAINS:
            base = full_config(ROOT / "outputs" / "spnv2_eval" / wd) / d
            if (base / "mean_performance.txt").exists():
                m = parse(base / "mean_performance.txt")
                row[f"{d}_eT"] = m["efficientpose.eT"]
                row[f"{d}_eR"] = m["heatmap.eR"]
                row[f"{d}_pose"] = m["final_pose"]
                row[f"{d}_fail"] = float(failed(load_per_sample(base / "per_sample_performance.mat")).mean())
        f = full_config(ROOT / "outputs" / "spnv2_eval_renders" / a.run / wd) / "sunsweep" / "per_sample_performance.mat"
        if f.exists():
            fl = failed(load_per_sample(f))
            curves[lab] = np.array([fl[phase == ph].mean() for ph in phases])
            row["sweep_fail_all"] = float(fl.mean())
            row["sweep_fail_0_40"] = float(fl[phase <= 40].mean())
            row["sweep_fail_60_100"] = float(fl[(phase >= 60) & (phase <= 100)].mean())
            row["sweep_fail_120_160"] = float(fl[phase >= 120].mean())
        table.append(row)

    # ---- 표
    print("| 모델 | 합성 E_pose | lightbox E_pose | sunlamp E_pose | 합성 실패 | lightbox 실패 | sunlamp 실패 |"
          " 태양실험 실패 0~40° | 60~100° | 120~160° |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    g = lambda r, k, pct=False: (f"{r[k]:.1%}" if pct else f"{r[k]:.3f}") if k in r else "–"  # noqa: E731
    for r in table:
        print(f"| {r['label']} | {g(r, 'synthetic_pose')} | {g(r, 'lightbox_pose')} | {g(r, 'sunlamp_pose')} | "
              f"{g(r, 'synthetic_fail', 1)} | {g(r, 'lightbox_fail', 1)} | {g(r, 'sunlamp_fail', 1)} | "
              f"{g(r, 'sweep_fail_0_40', 1)} | {g(r, 'sweep_fail_60_100', 1)} | {g(r, 'sweep_fail_120_160', 1)} |")
    print("\n| 모델 | 도메인 | E_T [m] | E_R [°] | E_pose |")
    print("|---|---|---|---|---|")
    for r in table:
        for d in DOMAINS:
            if f"{d}_pose" in r:
                print(f"| {r['label']} | {d} | {r[f'{d}_eT']:.3f} | {r[f'{d}_eR']:.2f} | {r[f'{d}_pose']:.3f} |")
    out_csv = ROOT / "outputs" / "failure_map" / f"finetune_compare_{a.run}.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for r in table for k in r}, key=lambda k: (k not in ("weights", "label"), k))
    with open(out_csv, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=keys)
        wr.writeheader()
        wr.writerows(table)

    # ---- 그림: (a) 위상각별 실패율, (b) SPEED+ 실물 조명 도메인 실패율
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(13, 5.2), dpi=150, gridspec_kw=dict(width_ratios=[1.5, 1]))
    fig.patch.set_facecolor(SURFACE)
    for axx in (ax, bx):
        axx.set_facecolor(SURFACE)
        axx.tick_params(colors=INK2, labelsize=9)
        for s in ("top", "right"):
            axx.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            axx.spines[s].set_color(GRID)
        axx.grid(True, axis="y", color=GRID, lw=0.8)
        axx.set_axisbelow(True)
        axx.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    for i, (lab, y) in enumerate(curves.items()):
        ax.plot(phases, y, color=COLORS[i], lw=2, marker="o", ms=5, label=lab)
    ax.set_xticks(phases)
    ax.set_xticklabels([f"{v:g}°" for v in phases])
    ax.set_xlabel("Sun phase angle (0° = front-lit, 180° = back-lit)", color=INK2)
    ax.set_ylabel("Failure rate (rot. error > 10° or rejected)", color=INK2)
    ax.set_ylim(0, 1)
    ax.set_title("(a) Held-out sun-angle test: 100 SPEED+ validation poses × 65 sun directions",
                 color=INK, fontsize=10, loc="left")
    leg = ax.legend(loc="upper left", frameon=False, fontsize=9)
    for t in leg.get_texts():
        t.set_color(INK)

    x = np.arange(len(DOMAINS))
    n = len(table)
    wbar = 0.8 / n
    ymax = 0.0
    for i, r in enumerate(table):
        vals = [r.get(f"{d}_fail", np.nan) for d in DOMAINS]
        ymax = max(ymax, np.nanmax(vals))
        bars = bx.bar(x + (i - (n - 1) / 2) * wbar, vals, width=wbar - 0.02, color=COLORS[i],
                      edgecolor=SURFACE, linewidth=2, label=r["label"])
        for b, v in zip(bars, vals):
            if np.isfinite(v):
                bx.text(b.get_x() + b.get_width() / 2, v + 0.004, f"{v:.1%}", ha="center", va="bottom",
                        fontsize=7.5, color=INK2)
    bx.set_xticks(x)
    bx.set_xticklabels(["Synthetic\n(validation)", "Lightbox\n(HIL)", "Sunlamp\n(HIL)"], color=INK2)
    bx.set_ylim(0, ymax * 1.25 if ymax > 0 else 1)
    bx.set_title("(b) SPEED+ test domains: failure rate", color=INK, fontsize=10, loc="left")
    fig.tight_layout()
    out = ROOT / "outputs" / "figures" / f"finetune_compare_{a.run}.png"
    fig.savefig(out, facecolor=SURFACE)
    print(f"\nsaved {out}\nsaved {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
