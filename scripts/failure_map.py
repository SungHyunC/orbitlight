"""태양 각도 실험(sunsweep)의 SPNv2 오차로 "실패 지도"를 그린다.

    python scripts/failure_map.py --run speedplus_sunsweep_v01 [--weights offline]

입력
- outputs/renders/<run>/sunsweep/meta.csv         이미지별 위상각·방위각·자세 번호 (test.json과 같은 순서)
- outputs/spnv2_eval_renders/<run>/<w>/.../per_sample_performance.mat   SPNv2 이미지별 오차 (같은 순서)
- outputs/spnv2_eval/<w>/.../synthetic/per_sample_performance.mat       같은 자세의 SPEED+ 원본 이미지 오차 (렌더러 검증용)

실패 정의: heatmap 헤드 회전 오차 > 10° 또는 자세 계산 거부(reject). Phase 1 base-003과 같은 기준.
출력: outputs/figures/failure_map_<run>_<w>.png, outputs/failure_map/<run>_<w>_{by_phase,by_cell}.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from scipy.io import loadmat  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FAIL_DEG = 10.0
# dataviz 기본 팔레트: 순차(sequential) 파랑 100→700, 범주형 1~3번
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
CAT = {"ours": "#2a78d6", "lightbox": "#eb6834", "sunlamp": "#1baf7a"}
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
# Phase 1 실측 (LOG base-003, offline 가중치, 거부 포함 10° 초과 비율)
HIL_FAIL = {"offline": {"lightbox": 0.081, "sunlamp": 0.130}}


def per_sample(path: Path) -> dict[str, np.ndarray]:
    m = loadmat(path)
    return {k: np.ravel(v) for k, v in m.items() if not k.startswith("__")}


def failed(ps: dict[str, np.ndarray]) -> np.ndarray:
    e = ps["heat_eR"]
    return (~np.isfinite(e)) | (e > FAIL_DEG) | (ps["h_reject"] > 0)


def bootstrap_ci(fail: np.ndarray, pose: np.ndarray, n: int = 2000, seed: int = 0) -> tuple[float, float]:
    """자세 단위로 다시 뽑는 부트스트랩 95% 구간 (같은 자세의 이미지끼리는 독립이 아니므로)."""
    rng = np.random.default_rng(seed)
    ids = np.unique(pose)
    per_pose = np.array([fail[pose == i].mean() for i in ids])
    bs = rng.choice(per_pose, (n, len(per_pose)), replace=True).mean(1)
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def style(ax):
    ax.set_facecolor(SURFACE)
    ax.tick_params(colors=INK2, labelsize=9)
    for s in ax.spines.values():
        s.set_color(GRID)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="speedplus_sunsweep_v01")
    p.add_argument("--weights", default="offline")
    a = p.parse_args()

    rows = list(csv.DictReader(open(ROOT / "outputs" / "renders" / a.run / "sunsweep" / "meta.csv")))
    ps = per_sample(ROOT / "outputs" / "spnv2_eval_renders" / a.run / a.weights / "efficientdet_d3" / "full_config"
                    / "sunsweep" / "per_sample_performance.mat")
    assert len(rows) == len(ps["heat_eR"]), (len(rows), len(ps["heat_eR"]))
    phase = np.array([float(r["phase_deg"]) for r in rows])
    az = np.array([float(r["azimuth_deg"]) for r in rows])
    pose = np.array([int(r["pose_id"]) for r in rows])
    fail = failed(ps)
    eR = ps["heat_eR"]

    # 렌더러 검증: 같은 자세의 SPEED+ 원본 이미지에서 SPNv2 오차
    syn_csv = ROOT / "data" / "speedplus" / "speedplusv2" / "synthetic" / "labels" / "validation.csv"
    syn_names = [line.split(",")[0].strip() for line in open(syn_csv)]
    syn = per_sample(ROOT / "outputs" / "spnv2_eval" / a.weights / "efficientdet_d3" / "full_config" / "synthetic"
                     / "per_sample_performance.mat")
    src_of_pose = {int(r["pose_id"]): r["source_image"] for r in rows}
    idx = [syn_names.index(src_of_pose[k]) for k in sorted(src_of_pose)]
    syn_fail = failed({k: syn[k][idx] for k in ("heat_eR", "h_reject")})
    syn_eR = syn["heat_eR"][idx]

    out_csv = ROOT / "outputs" / "failure_map"
    out_csv.mkdir(parents=True, exist_ok=True)
    phases = sorted(set(phase))
    azs = sorted(set(az[phase > 0]))
    by_phase = []
    for ph in phases:
        m = phase == ph
        lo, hi = bootstrap_ci(fail[m], pose[m])
        by_phase.append(dict(phase_deg=ph, n=int(m.sum()), fail_rate=float(fail[m].mean()), ci_lo=lo, ci_hi=hi,
                             median_eR=float(np.nanmedian(eR[m]))))
    with open(out_csv / f"{a.run}_{a.weights}_by_phase.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(by_phase[0]))
        w.writeheader()
        w.writerows(by_phase)
    cells = []
    for ph in phases:
        for z in ([0.0] if ph == 0 else azs):
            m = (phase == ph) & (az == z)
            cells.append(dict(phase_deg=ph, azimuth_deg=z, n=int(m.sum()), fail_rate=float(fail[m].mean()),
                              median_eR=float(np.nanmedian(eR[m]))))
    with open(out_csv / f"{a.run}_{a.weights}_by_cell.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cells[0]))
        w.writeheader()
        w.writerows(cells)

    # ---------------- 그림 ----------------
    fig = plt.figure(figsize=(12, 5.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    cmap = LinearSegmentedColormap.from_list("seq", SEQ)
    vmax = max(0.5, float(np.ceil(max(c["fail_rate"] for c in cells) * 10) / 10))

    # (a) 극좌표 실패 지도: 각도 = 방위각(이미지 기준 태양 방향), 반지름 = 위상각
    axp = fig.add_subplot(1, 2, 1, projection="polar")
    style(axp)
    step = 20.0
    dz = np.radians(azs[1] - azs[0]) if len(azs) > 1 else 2 * np.pi
    for c in cells:
        r0 = max(c["phase_deg"] - step / 2, 0)
        r1 = c["phase_deg"] + step / 2
        if c["phase_deg"] == 0:
            th, width = 0.0, 2 * np.pi
        else:
            th, width = np.radians(c["azimuth_deg"]) - dz / 2, dz
        axp.bar(th, r1 - r0, width=width, bottom=r0, align="edge", color=cmap(c["fail_rate"] / vmax),
                edgecolor=SURFACE, linewidth=1.0)
    axp.set_ylim(0, phases[-1] + step / 2)
    axp.set_yticks([0, 40, 80, 120, 160])
    axp.set_yticklabels(["0°", "40°", "80°", "120°", "160°"], color=INK2, fontsize=8)
    axp.set_rlabel_position(22.5)
    axp.set_xticks(np.radians([0, 90, 180, 270]))
    axp.set_xticklabels(["sun from\nimage right", "from top", "from left", "from bottom"], color=INK2, fontsize=8)
    axp.grid(color=GRID, lw=0.6)
    axp.set_title("(a) Failure rate by sun direction\ncenter = front-lit (phase 0°), edge = back-lit (phase 160°)",
                  color=INK, fontsize=10, loc="left", pad=14)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0, vmax))
    cb = fig.colorbar(sm, ax=axp, shrink=0.75, pad=0.1)
    cb.set_label(f"failure rate (rotation error > {FAIL_DEG:g}° or rejected)", color=INK2, fontsize=8)
    cb.ax.tick_params(colors=INK2, labelsize=8)
    cb.ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    cb.outline.set_edgecolor(GRID)

    # (b) 위상각별 실패율 + 95% 구간, Phase 1 실물 조명 실패율을 기준선으로
    ax = fig.add_subplot(1, 2, 2)
    style(ax)
    x = np.array([b["phase_deg"] for b in by_phase])
    y = np.array([b["fail_rate"] for b in by_phase])
    lo = np.array([b["ci_lo"] for b in by_phase])
    hi = np.array([b["ci_hi"] for b in by_phase])
    ax.fill_between(x, lo, hi, color=CAT["ours"], alpha=0.15, lw=0)
    ax.plot(x, y, color=CAT["ours"], lw=2, marker="o", ms=5, label="OrbitLight renders (100 poses × 8 azimuths)")
    ax.axhline(syn_fail.mean(), color=INK2, lw=1, ls=(0, (1, 2)),
               label=f"SPEED+ synthetic, same 100 poses ({syn_fail.mean():.0%})")
    for d, v in HIL_FAIL.get(a.weights, {}).items():
        ax.axhline(v, color=CAT[d], lw=1.2, ls=(0, (4, 3)), label=f"SPEED+ {d} (HIL), Phase 1 ({v:.1%})")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{v:g}°" for v in x])
    ax.set_xlabel("Sun phase angle (0° = sun behind camera, 180° = sun behind target)", color=INK2)
    ax.set_ylabel("Failure rate", color=INK2)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.set_ylim(0, max(1.0, hi.max() * 1.05) if hi.max() > 0.6 else max(0.6, hi.max() * 1.1))
    ax.grid(True, axis="y", color=GRID, lw=0.8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_title(f"(b) SPNv2 ({a.weights} weights) failure rate vs sun phase angle (shaded: 95% CI over poses)",
                 color=INK, fontsize=10, loc="left")
    leg = ax.legend(loc="upper left", frameon=False, fontsize=8)
    for t in leg.get_texts():
        t.set_color(INK)
    fig.tight_layout()
    fig_path = ROOT / "outputs" / "figures" / f"failure_map_{a.run}_{a.weights}.png"
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, facecolor=SURFACE)

    # ---------------- 요약 출력 ----------------
    print(f"run={a.run} weights={a.weights} images={len(rows)} poses={len(np.unique(pose))}")
    print(f"렌더러 검증: SPEED+ 원본(같은 자세) 실패율 {syn_fail.mean():.1%}, 회전 오차 중앙값 {np.nanmedian(syn_eR):.2f}°")
    print("| 위상각 | 이미지 | 실패율 | 95% 구간 | 회전 오차 중앙값 |")
    print("|---|---|---|---|---|")
    for b in by_phase:
        print(f"| {b['phase_deg']:g}° | {b['n']} | {b['fail_rate']:.1%} | {b['ci_lo']:.1%}–{b['ci_hi']:.1%} | "
              f"{b['median_eR']:.2f}° |")
    print("방위각별 실패율 (위상각 > 0 전체):")
    for z in azs:
        m = (az == z) & (phase > 0)
        print(f"  az {z:g}°: {fail[m].mean():.1%}")
    print(f"saved {fig_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
