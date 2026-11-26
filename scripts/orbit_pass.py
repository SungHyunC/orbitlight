"""궤도 한 바퀴 동안 언제 자세 추정이 위험한가: 실패 지도를 실제 근접 운용 장면에 적용한다 (v0.2).

    # 1) 계획: 베타각 × 정지 위치별로 위험 시간을 실패 지도로 예측 (GPU 없이, 몇 초)
    python scripts/orbit_pass.py plan --betas 0,30,60 --holds vbar-,vbar+,rbar-,hbar+,hbar-

    # 2) 렌더 작업 만들기 → 렌더 → SPEED+ 형식 변환 → SPNv2 평가 (sunsweep.py, eval 스크립트를 그대로 씀)
    python scripts/orbit_pass.py jobs --run speedplus_orbit_b30_vbarm --beta 30 --hold vbar- --step 15
    python scripts/sunsweep.py render --run speedplus_orbit_b30_vbarm     # 또는 cloud/modal_app.py::run_render
    python scripts/sunsweep.py post --run speedplus_orbit_b30_vbarm
    RUN=speedplus_orbit_b30_vbarm bash scripts/eval_spnv2_renders.sh

    # 3) 실제 오차와 예측(실패 지도)·자가 경고를 시간축에 맞춰 비교
    python scripts/orbit_pass.py analyze --run speedplus_orbit_b30_vbarm

장면 정의와 좌표는 src/orbitlight/orbit/scenario.py. 목표 위성의 LVLH 고정 자세는 SPEED+ 검증셋 자세 하나에서 정한다:
기준 정지 위치(vbar-)에서 그 자세로 보이도록 하고, 다른 정지 위치는 같은 목표 자세를 다른 방향에서 본다.
지구 반사광(albedo)과 카메라 시야 안의 태양(눈부심)은 렌더러에 없다 (v0.1과 같은 한계).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from orbitlight.orbit.scenario import (HOLD_KO, HOLDS, Orbit, p_fail_from_map, phase_azimuth_deg,  # noqa: E402
                                       relative_pose, sun_in_camera, target_attitude_lvlh)
from orbitlight.render.geometry import C_CV2BL, blender_object_matrix, phase_angle_deg  # noqa: E402

SPEED = ROOT / "data" / "speedplus" / "speedplusv2"
MODEL = ROOT / "data" / "models" / "spin_tango" / "tango_fix.obj"
OUT = ROOT / "outputs" / "orbit"
HIGH, LOW = 0.30, 0.05     # 위험 구간: 실패 지도 실패율 30% 이상 / 안전 구간: 5% 미만


def floats(s: str) -> list[float]:
    return [float(x) for x in s.split(",") if x.strip()]


def strs(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def load_map(path: str | None) -> dict[float, float] | None:
    """failure_map.py가 만든 by_phase CSV가 있으면 그 값을 쓴다 (없으면 README v0.1 표)."""
    if not path or not Path(path).exists():
        return None
    rows = list(csv.DictReader(open(path)))
    key = "fail_rate" if "fail_rate" in rows[0] else [k for k in rows[0] if "fail" in k][0]
    return {float(r["phase_deg"]): float(r[key]) for r in rows}


def reference_pose(pose_source: str, pose_from: str | None, seed: int, n_poses: int) -> dict:
    """목표 자세의 기준이 될 SPEED+ 라벨. 지정이 없으면 태양 실험(sunsweep.py)과 같은 방식으로 뽑은 첫 자세."""
    if not (SPEED / pose_source).exists():
        # 계획(plan)은 위상각만 쓰므로 목표 자세와 무관하다: 데이터가 없으면 기본 자세로 계산
        return dict(filename="(기본 자세)", q_vbs2tango_true=[1.0, 0.0, 0.0, 0.0], r_Vo2To_vbs_true=[0.0, 0.0, 7.0])
    labels = json.loads((SPEED / pose_source).read_text())
    if pose_from:
        return next(l for l in labels if l["filename"] == pose_from)
    rng = np.random.default_rng(seed)
    return labels[sorted(rng.choice(len(labels), n_poses, replace=False).tolist())[0]]


def timeline(orbit: Orbit, hold: str, body_from_lvlh: np.ndarray, dist: float, step_s: float,
             table: dict | None) -> list[dict]:
    n = int(np.ceil(orbit.period_s / step_s))
    t = np.arange(n) * step_s
    u = 360.0 * t / orbit.period_s
    st = orbit.state(u)
    q, r = relative_pose(body_from_lvlh, hold, dist)
    s_cam = sun_in_camera(st["s_lvlh"], hold)
    phase, az = phase_azimuth_deg(r, s_cam)
    p = p_fail_from_map(phase, table)
    rows = []
    for k in range(n):
        rows.append(dict(k=k, t_s=float(t[k]), t_min=float(t[k] / 60), u_deg=float(st["u_deg"][k]),
                         eclipse=bool(st["eclipse"][k]), phase_deg=float(phase[k]), azimuth_deg=float(az[k]),
                         p_fail_map=None if st["eclipse"][k] else float(p[k]),
                         sun_cam=s_cam[k].tolist(), q=q.tolist(), r=r.tolist()))
    return rows


def summarize(rows: list[dict], step_s: float) -> dict:
    lit = [x for x in rows if not x["eclipse"]]
    p = np.array([x["p_fail_map"] for x in lit])
    m = step_s / 60.0
    return dict(period_min=len(rows) * m, eclipse_min=(len(rows) - len(lit)) * m, lit_min=len(lit) * m,
                high_min=float((p >= HIGH).sum() * m), safe_min=float((p < LOW).sum() * m),
                mean_p_lit=float(p.mean()) if len(p) else float("nan"),
                phase_min=float(min(x["phase_deg"] for x in lit)) if lit else None,
                phase_max=float(max(x["phase_deg"] for x in lit)) if lit else None)


def cmd_plan(a) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    table = load_map(a.map)
    ref = reference_pose(a.pose_source, a.pose_from, a.seed, a.n_poses)
    body = target_attitude_lvlh(ref["q_vbs2tango_true"])
    dist = a.dist or float(np.linalg.norm(ref["r_Vo2To_vbs_true"]))
    out_rows, summ = [], []
    for beta in a.betas:
        orbit = Orbit(altitude_km=a.altitude, beta_deg=beta)
        for hold in a.holds:
            rows = timeline(orbit, hold, body, dist, a.step, table)
            s = summarize(rows, a.step)
            summ.append(dict(beta_deg=beta, hold=hold, hold_ko=HOLD_KO[hold], **s))
            for x in rows:
                out_rows.append(dict(beta_deg=beta, hold=hold, **{k: v for k, v in x.items() if k not in ("sun_cam", "q", "r")}))
    with open(OUT / "plan_timeline.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    meta = dict(created=time.strftime("%Y-%m-%d %H:%M:%S"), altitude_km=a.altitude, step_s=a.step, dist_m=dist,
                ref_image=ref["filename"], failure_map="table" if table else "README v0.1", high=HIGH, low=LOW, rows=summ)
    (OUT / "plan_summary.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    print(f"고도 {a.altitude:.0f} km (한 바퀴 {summ[0]['period_min']:.1f}분), 거리 {dist:.1f} m, 기준 자세 {ref['filename']}")
    print(f"| β | 정지 위치 | 식 [분] | 위험(≥{HIGH:.0%}) [분] | 안전(<{LOW:.0%}) [분] | 빛 받는 동안 평균 실패율 | 위상각 범위 |")
    print("|---|---|---|---|---|---|---|")
    for s in summ:
        rng = f"{s['phase_min']:.0f}~{s['phase_max']:.0f}°" if s["phase_min"] is not None else "-"
        print(f"| {s['beta_deg']:.0f}° | {s['hold_ko']} | {s['eclipse_min']:.1f} | {s['high_min']:.1f} | {s['safe_min']:.1f} | "
              f"{s['mean_p_lit']:.1%} | {rng} |")
    if not a.no_figure:
        plot_plan(OUT / "plan_timeline.csv", meta, ROOT / "outputs" / "figures" / "orbit_plan.png")


def cmd_jobs(a) -> None:
    run = ROOT / "outputs" / "renders" / a.run
    run.mkdir(parents=True, exist_ok=True)
    assert "speedplus" in a.run, "SPNv2가 읽으려면 run 이름에 speedplus가 있어야 한다"
    camera = json.loads((SPEED / "camera.json").read_text())
    table = load_map(a.map)
    ref = reference_pose(a.pose_source, a.pose_from, a.seed, a.n_poses)
    body = target_attitude_lvlh(ref["q_vbs2tango_true"])
    dist = a.dist or float(np.linalg.norm(ref["r_Vo2To_vbs_true"]))
    orbit = Orbit(altitude_km=a.altitude, beta_deg=a.beta)
    rows = timeline(orbit, a.hold, body, dist, a.step, table)
    jobs = []
    for x in rows:
        if x["eclipse"]:
            continue      # 지구 그림자: 지구 반사광이 없는 렌더러에서는 아무것도 안 보인다
        s_cam = np.array(x["sun_cam"])
        assert abs(phase_angle_deg(x["r"], s_cam) - x["phase_deg"]) < 1e-6
        jobs.append(dict(name=f"t{x['k']:04d}", pose_id=0, source_image=ref["filename"], q=x["q"], r=x["r"],
                         phase_deg=x["phase_deg"], azimuth_deg=x["azimuth_deg"], sun_strength=a.sun_strength,
                         sun_dir_cam=s_cam.tolist(), sun_dir_world=(C_CV2BL @ s_cam).tolist(),
                         object_matrix=blender_object_matrix(x["q"], x["r"]).tolist(),
                         t_s=x["t_s"], u_deg=x["u_deg"]))
    cfg = dict(
        created=time.strftime("%Y-%m-%d %H:%M:%S"), camera=camera, model=str(MODEL.relative_to(ROOT)),
        pose_source=a.pose_source, seed=a.seed, randomize_materials=False,
        render=dict(sun_strength=a.sun_strength, samples=64, denoise=True, max_bounces=6, seed=0, exposure=0.0, color_depth="16"),
        post=dict(noise_std=3.0, noise_offset=2.0, jpg_quality=95), conditions=[],
        orbit=dict(altitude_km=a.altitude, beta_deg=a.beta, hold=a.hold, hold_ko=HOLD_KO[a.hold], step_s=a.step,
                   period_s=orbit.period_s, dist_m=dist, ref_image=ref["filename"], **summarize(rows, a.step)),
        jobs=jobs,
    )
    (run / "jobs.json").write_text(json.dumps(cfg, indent=1))
    with open(run / "timeline.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["k", "t_s", "t_min", "u_deg", "eclipse", "phase_deg", "azimuth_deg", "p_fail_map"])
        w.writeheader()
        w.writerows([{k: x[k] for k in w.fieldnames} for x in rows])
    print(f"{run / 'jobs.json'}: β={a.beta:.0f}°, {HOLD_KO[a.hold]}, 한 바퀴 {len(rows)}스텝 중 빛 받는 {len(jobs)}장 렌더")


def cmd_analyze(a) -> None:
    from orbitlight.eval.spnv2_results import load_per_sample

    run = ROOT / "outputs" / "renders" / a.run
    cfg = json.loads((run / "jobs.json").read_text())
    wd = a.weights.replace(":", "_")
    ev = ROOT / "outputs" / "spnv2_eval_renders" / a.run / wd / "efficientdet_d3" / "full_config" / "sunsweep"
    ps = load_per_sample(ev / "per_sample_performance.mat")
    labels = json.loads((run / "sunsweep" / "test.json").read_text())
    by_name = {j["name"]: j for j in cfg["jobs"]}
    eR, rej = ps["heat_eR"], ps["h_reject"]
    fail = rej | ~np.isfinite(eR) | (np.nan_to_num(eR, nan=np.inf) > 10.0)
    # 자가 경고 점수 (scripts/self_check.py가 렌더로 정한 모델과 기준)
    warn = np.full(len(labels), np.nan)
    sc_path = ROOT / "outputs" / "self_check" / wd / "summary.json"
    if sc_path.exists() and (ev / "predictions_pose.mat").exists():
        import self_check as SC

        sc = json.loads(sc_path.read_text())
        mdl = sc["models"][sc.get("primary", "전체 신호")]
        d, _ = SC.load_domain(ev, run / "sunsweep" / "images_768x512_RGB", labels, sc["effi_R_transposed"])
        m = SC.usable(d, mdl["features"])
        X = np.c_[[d[f][m] for f in mdl["features"]]].T
        s = np.full(len(labels), np.nan)
        s[m] = SC.score(dict(mu=np.array(mdl["mu"]), sd=np.array(mdl["sd"]), w=np.array(mdl["w"])), X)
        warn = (d["reject"] | (np.nan_to_num(s, nan=np.inf) >= mdl["threshold"])).astype(float)
    rows = []
    for i, lab in enumerate(labels):
        j = by_name[Path(lab["filename"]).stem]
        rows.append(dict(name=j["name"], t_min=j["t_s"] / 60, u_deg=j["u_deg"], phase_deg=j["phase_deg"],
                         azimuth_deg=j["azimuth_deg"], p_fail_map=float(p_fail_from_map([j["phase_deg"]])[0]),
                         heat_eR=float(eR[i]) if np.isfinite(eR[i]) else "", reject=int(rej[i]), fail=int(fail[i]),
                         warn="" if not np.isfinite(warn[i]) else int(warn[i])))
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{a.run}_{wd}.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    o = cfg["orbit"]
    pf = np.array([r["p_fail_map"] for r in rows])
    fl = np.array([r["fail"] for r in rows], bool)
    step_min = o["step_s"] / 60
    res = dict(run=a.run, weights=a.weights, beta_deg=o["beta_deg"], hold=o["hold"], hold_ko=o["hold_ko"],
               lit_frames=len(rows), actual_fail_rate=float(fl.mean()), predicted_fail_rate=float(pf.mean()),
               actual_fail_min=float(fl.sum() * step_min), predicted_high_min=float((pf >= HIGH).sum() * step_min),
               eclipse_min=o["eclipse_min"])
    if np.isfinite(warn).any():
        wv = np.nan_to_num(warn, nan=0).astype(bool)
        res.update(warn_rate=float(wv.mean()), fail_warned=float((wv & fl).sum() / max(fl.sum(), 1)),
                   kept_fail_rate=float(fl[~wv].mean()) if (~wv).any() else None)
    (OUT / f"{a.run}_{wd}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False))
    plot_pass(rows, cfg, res, ROOT / "outputs" / "figures" / f"orbit_{a.run.replace('speedplus_orbit_', '')}_{wd}.png")


def _style(ax, SURFACE, GRID, INK2):
    ax.set_facecolor(SURFACE)
    ax.grid(color=GRID, lw=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=INK2)


def plot_plan(timeline_csv: Path, meta: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    SURFACE, INK2, GRID = "#fcfcfb", "#52514e", "#e4e3df"
    COL = {"vbar-": "#d9622b", "vbar+": "#e0a03a", "rbar-": "#2b7bd9", "hbar+": "#3a9e6b", "hbar-": "#8a5bd0"}
    EN = {"vbar-": "V-bar behind", "vbar+": "V-bar ahead", "rbar-": "R-bar below", "hbar+": "H-bar sun side",
          "hbar-": "H-bar far side"}
    rows = list(csv.DictReader(open(timeline_csv)))
    betas = sorted({float(r["beta_deg"]) for r in rows})
    fig, axes = plt.subplots(1, len(betas), figsize=(5.2 * len(betas), 4.2), facecolor=SURFACE, sharey=True, squeeze=False)
    for ax, beta in zip(axes[0], betas):
        sub = [r for r in rows if float(r["beta_deg"]) == beta]
        for hold in dict.fromkeys(r["hold"] for r in sub):
            hs = [r for r in sub if r["hold"] == hold]
            t = np.array([float(r["t_min"]) for r in hs])
            p = np.array([np.nan if r["p_fail_map"] in ("", "None") else float(r["p_fail_map"]) for r in hs])
            ax.plot(t, p * 100, color=COL.get(hold, "#555"), lw=1.8, label=EN.get(hold, hold))
            ecl = np.array([r["eclipse"] == "True" for r in hs])
        if ecl.any():
            ax.fill_between(t, 0, 100, where=ecl, color="#0b0b0b", alpha=0.08, lw=0, label="eclipse")
        ax.axhline(HIGH * 100, color=INK2, lw=0.8, ls=":")
        ax.set_title(f"beta = {beta:.0f} deg", loc="left", fontsize=10)
        ax.set_xlabel("time in orbit [min]")
        ax.set_ylim(0, 80)
        _style(ax, SURFACE, GRID, INK2)
    axes[0][0].set_ylabel("predicted failure rate from the map [%]")
    axes[0][-1].legend(frameon=False, fontsize=8, loc="upper right")
    fig.suptitle(f"Where the camera waits decides when pose estimation is at risk "
                 f"({meta['altitude_km']:.0f} km circular orbit, {meta['dist_m']:.1f} m)", x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    print(f"-> {path}")


def plot_pass(rows: list[dict], cfg: dict, res: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
    o = cfg["orbit"]
    t = np.array([r["t_min"] for r in rows])
    e = np.array([np.nan if r["heat_eR"] == "" else r["heat_eR"] for r in rows], float)
    fl = np.array([r["fail"] for r in rows], bool)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6), facecolor=SURFACE, sharex=True,
                                   gridspec_kw=dict(height_ratios=[1, 1.3]))
    # 식(그림자) 구간은 프레임이 없으므로 선을 끊는다
    gap = np.r_[False, np.diff(t) > 1.5 * o["step_s"] / 60]
    tt, ph, pm = [], [], []
    for i, r in enumerate(rows):
        if gap[i]:
            tt.append(np.nan); ph.append(np.nan); pm.append(np.nan)
        tt.append(t[i]); ph.append(r["phase_deg"]); pm.append(r["p_fail_map"] * 100)
    ax1.plot(tt, ph, color=INK, lw=1.5)
    ax1.set_ylabel("sun phase angle [deg]")
    ax1.set_ylim(0, 180)
    ax1b = ax1.twinx()
    ax1b.plot(tt, pm, color="#d9622b", lw=1.2, ls="--")
    ax1b.set_ylabel("map: failure rate [%]", color="#d9622b")
    ax1b.set_ylim(0, 100)
    ax2.scatter(t[~fl], np.clip(e[~fl], 0.1, 180), s=8, color="#3a9e6b", label="ok (< 10 deg)")
    ax2.scatter(t[fl], np.clip(np.nan_to_num(e[fl], nan=180), 0.1, 180), s=10, color="#c8372d", label="fail (> 10 deg or rejected)")
    ws = [r for r in rows if r["warn"] == 1]
    if ws:
        ax2.scatter([r["t_min"] for r in ws], [150] * len(ws), marker="|", s=40, color="#2b7bd9", label="self-check warning")
    ax2.set_yscale("log")
    ax2.set_ylabel("rotation error [deg]")
    ax2.set_xlabel("time in orbit [min]")
    ax2.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3)
    T = o["period_s"] / 60
    for ax in (ax1, ax2):
        ax.set_xlim(0, T)
        _style(ax, SURFACE, GRID, INK2)
    lit = set(np.round(t, 4))
    step = o["step_s"] / 60
    allt = np.arange(0, T, step)
    for x in allt:
        if np.round(x, 4) not in lit:
            for ax in (ax1, ax2):
                ax.axvspan(x, x + step, color=INK, alpha=0.07, lw=0)
    ax1.set_title(f"One orbit, beta {o['beta_deg']:.0f} deg, camera {o['hold']} at {o['dist_m']:.1f} m — "
                  f"actual failures {res['actual_fail_rate']:.0%} of lit frames (map predicted {res['predicted_fail_rate']:.0%}); "
                  f"shaded = eclipse", loc="left", fontsize=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    print(f"-> {path}")


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "jobs"):
        s = sub.add_parser(name)
        s.add_argument("--altitude", type=float, default=500.0)
        s.add_argument("--step", type=float, default=15.0, help="시간 간격 [s]")
        s.add_argument("--dist", type=float, default=0.0, help="카메라-목표 거리 [m]. 0이면 기준 자세의 거리")
        s.add_argument("--pose-source", default="synthetic/validation.json")
        s.add_argument("--pose-from", default=None, help="기준 자세로 쓸 SPEED+ 파일 이름")
        s.add_argument("--seed", type=int, default=0)
        s.add_argument("--n-poses", type=int, default=100)
        s.add_argument("--map", default=str(ROOT / "outputs" / "failure_map" / "speedplus_sunsweep_v01_offline_by_phase.csv"))
    sp = sub.choices["plan"]
    sp.add_argument("--betas", type=floats, default=floats("0,30,60"))
    sp.add_argument("--holds", type=strs, default=list(HOLDS))
    sp.add_argument("--no-figure", action="store_true")
    sj = sub.choices["jobs"]
    sj.add_argument("--run", required=True)
    sj.add_argument("--beta", type=float, default=30.0)
    sj.add_argument("--hold", default="vbar-", choices=list(HOLDS))
    sj.add_argument("--sun-strength", type=float, default=4.0)
    sa = sub.add_parser("analyze")
    sa.add_argument("--run", required=True)
    sa.add_argument("--weights", default="offline")
    a = p.parse_args()
    {"plan": cmd_plan, "jobs": cmd_jobs, "analyze": cmd_analyze}[a.cmd](a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
