"""웹 데모(site/)가 읽는 데이터 만들기: 축소 이미지, 예측·정답 키포인트 투영, 자가 경고, 궤도 타임라인.

    python scripts/build_site.py                      # → outputs/site/{data/*.json, img/...}
    python scripts/build_site.py --sections sweep,hil

결과 폴더를 저장소의 site/ 아래로 복사하면 site/index.html이 그대로 읽는다 (서버 없이 정적 파일).
이미지는 SPEED+(CC BY-NC-SA 4.0)와 SPIN Tango 모형(GPL-3.0)으로 만든 것이라 출처를 페이지에 적는다.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from scipy.io import loadmat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from orbitlight.eval.spnv2_results import load_per_sample  # noqa: E402
from orbitlight.render.geometry import quat2dcm  # noqa: E402

SPEED = ROOT / "data" / "speedplus" / "speedplusv2"
KEYPTS = ROOT / "third_party" / "spnv2" / "core" / "utils" / "models" / "tangoPoints.mat"
OUT = ROOT / "outputs" / "site"
W_DISP = 768                       # 표시 이미지 너비 (1920×1200 → 768×480)
JPG_Q = 80
# 키포인트 연결: 위 4개(전지판 모서리), 아래 4개(몸체 바닥 모서리), 안테나 끝 3개
EDGES = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7],
         [1, 8], [2, 9], [3, 10]]


def full_config(d: Path) -> Path:
    return d / "efficientdet_d3" / "full_config"


class Projector:
    def __init__(self):
        cam = json.loads((SPEED / "camera.json").read_text())
        self.K = np.array(cam["cameraMatrix"], float)
        self.dist = np.array(cam["distCoeffs"], float).ravel()
        self.Nu, self.Nv = int(cam["Nu"]), int(cam["Nv"])
        self.s = W_DISP / self.Nu
        m = loadmat(KEYPTS)
        P = np.asarray(m["tango3Dpoints"], float)
        self.P = P.T if P.shape[0] == 3 else P

    def __call__(self, R_body2cam: np.ndarray, t: np.ndarray) -> list[list[float]]:
        """몸체 → 카메라 회전과 위치로 키포인트를 표시 이미지 좌표에 투영 (렌즈 왜곡 포함)."""
        rvec, _ = cv2.Rodrigues(np.asarray(R_body2cam, float))
        pts, _ = cv2.projectPoints(self.P, rvec, np.asarray(t, float).reshape(3, 1), self.K, self.dist)
        return np.round(pts.reshape(-1, 2) * self.s, 1).tolist()

    def from_q(self, q, r):
        return self(quat2dcm(q).T, r)


def save_img(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    img = cv2.imread(str(src), cv2.IMREAD_GRAYSCALE)
    h = int(round(img.shape[0] * W_DISP / img.shape[1]))
    dst.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dst), cv2.resize(img, (W_DISP, h), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, JPG_Q])


def read_csv(p: Path) -> list[dict]:
    return list(csv.DictReader(open(p))) if p.exists() else []


def predictions(ev: Path, labels: list[dict], effi_T: bool) -> dict:
    ps = load_per_sample(ev / "per_sample_performance.mat")
    pr = loadmat(ev / "predictions_pose.mat")
    n = len(labels)
    heat_q = np.asarray(pr["heat_q"], float).reshape(n, 4)
    heat_t = np.asarray(pr["heat_t"], float).reshape(n, 3)
    effi_R = np.asarray(pr["effi_R"], float).reshape(n, 3, 3)
    if effi_T:
        effi_R = np.transpose(effi_R, (0, 2, 1))
    effi_t = np.asarray(pr["effi_t"], float).reshape(n, 3)
    return dict(eR=ps["heat_eR"], reject=ps["h_reject"], heat_q=heat_q, heat_t=heat_t, effi_R=effi_R, effi_t=effi_t)


def pred_kp(proj: Projector, P: dict, i: int) -> tuple[list, str]:
    """heatmap 헤드가 답을 냈으면 그 자세, 거부했으면 EfficientPose 헤드 자세를 그린다."""
    if not P["reject"][i] and np.all(np.isfinite(P["heat_q"][i])):
        return proj.from_q(P["heat_q"][i], P["heat_t"][i]), "heatmap"
    return proj(P["effi_R"][i].T, P["effi_t"][i]), "efficientpose"


def fnum(x, nd=2):
    x = float(x)
    return None if not np.isfinite(x) else round(x, nd)


def sweep_section(proj: Projector, a, sc: dict, effi_T: bool) -> dict:
    run = a.sweep_run
    rdir = ROOT / "outputs" / "renders" / run / "sunsweep"
    meta = read_csv(rdir / "meta.csv")
    labels = json.loads((rdir / "test.json").read_text())
    P = predictions(full_config(ROOT / "outputs" / "spnv2_eval_renders" / run / a.wd) / "sunsweep", labels, effi_T)
    feats = {r["filename"]: r for r in read_csv(ROOT / "outputs" / "self_check" / a.wd / "features_renders.csv")}
    fail = P["reject"] | ~np.isfinite(P["eR"]) | (np.nan_to_num(P["eR"], nan=np.inf) > 10)
    pose = np.array([int(r["pose_id"]) for r in meta])
    ph = np.array([float(r["phase_deg"]) for r in meta])
    az = np.array([float(r["azimuth_deg"]) for r in meta])
    # 칸별 실패율 (자세 100개 전체)
    cells = {}
    for p_ in sorted(set(ph)):
        for a_ in (sorted(set(az[ph == p_]))):
            m = (ph == p_) & (az == a_)
            cells[f"{int(p_)}_{int(a_)}"] = round(float(fail[m].mean()), 4)
    by_phase = {int(p_): round(float(fail[ph == p_].mean()), 4) for p_ in sorted(set(ph))}
    # 보여줄 자세: 자세별 실패 수의 분위수에서 고른다 (튼튼한 자세부터 약한 자세까지)
    per_pose = {k: int(fail[pose == k].sum()) for k in sorted(set(pose))}
    order = sorted(per_pose, key=lambda k: (per_pose[k], k))
    picks = sorted({order[int(round(q * (len(order) - 1)))] for q in np.linspace(0, 1, a.n_poses)}, key=lambda k: per_pose[k])
    poses = []
    for k in picks:
        idx = np.where(pose == k)[0]
        lab = labels[idx[0]]
        frames = {}
        for i in idx:
            fn = labels[i]["filename"]
            save_img(rdir / "images" / fn, OUT / "img" / "sweep" / fn)
            kp, src = pred_kp(proj, P, i)
            f = feats.get(fn, {})
            frames[f"{int(ph[i])}_{int(az[i])}"] = dict(
                img=f"img/sweep/{fn}", eR=fnum(P["eR"][i], 1), fail=bool(fail[i]), reject=bool(P["reject"][i]),
                warn=f.get("warn") == "1", score=fnum(f["score"]) if f.get("score") else None, kp=kp, kp_src=src)
        poses.append(dict(pose_id=int(k), fails=per_pose[k], kp_true=proj.from_q(lab["q_vbs2tango_true"], lab["r_Vo2To_vbs_true"]),
                          dist_m=round(float(np.linalg.norm(lab["r_Vo2To_vbs_true"])), 2), frames=frames))
    return dict(run=run, phases=sorted({int(x) for x in ph}), azimuths=sorted({int(x) for x in az[ph > 0]}),
                cells=cells, by_phase=by_phase, n_poses_total=len(per_pose), poses=poses)


def hil_section(proj: Projector, a, sc: dict, effi_T: bool) -> dict:
    out = dict(domains={})
    rng = np.random.default_rng(0)
    for dom, js in (("lightbox", "test.json"), ("sunlamp", "test.json")):
        ev = full_config(ROOT / "outputs" / "spnv2_eval" / a.wd) / dom
        feats = read_csv(ROOT / "outputs" / "self_check" / a.wd / f"features_{dom}.csv")
        if not feats or not (ev / "predictions_pose.mat").exists():
            continue
        labels = json.loads((SPEED / dom / js).read_text())
        P = predictions(ev, labels, effi_T)
        fail = np.array([r["fail"] == "1" for r in feats])
        warn = np.array([r["warn"] == "1" for r in feats])
        score = np.array([float(r["score"]) if r["score"] else np.inf for r in feats])
        rej = np.array([r["reject"] == "1" for r in feats])
        # 위험-포함률 곡선 (확신 높은 순으로 받아들임, 거부는 받지 않음), 100점으로 줄임
        s = np.where(rej, np.inf, score)
        order = np.argsort(s, kind="stable")
        f = fail[order].astype(float)
        k = np.arange(1, len(f) + 1)
        keep = np.isfinite(s[order])
        cov, risk = (k / len(f))[keep], (np.cumsum(f) / k)[keep]
        sel = np.unique(np.linspace(0, len(cov) - 1, 100).round().astype(int))
        groups = {"caught": fail & warn, "missed": fail & ~warn, "false_alarm": ~fail & warn, "ok": ~fail & ~warn}
        ex = []
        for g, n_pick in (("caught", 4), ("missed", 2), ("false_alarm", 2), ("ok", 3)):
            idx = np.where(groups[g])[0]
            for i in sorted(rng.choice(idx, min(n_pick, len(idx)), replace=False).tolist()) if len(idx) else []:
                fn = labels[i]["filename"]
                save_img(SPEED / dom / "images" / fn, OUT / "img" / dom / fn)
                kp, src = pred_kp(proj, P, i)
                ex.append(dict(group=g, img=f"img/{dom}/{fn}", eR=fnum(P["eR"][i], 1), reject=bool(rej[i]),
                               score=fnum(score[i]) if np.isfinite(score[i]) else None, kp=kp, kp_src=src,
                               kp_true=proj.from_q(labels[i]["q_vbs2tango_true"], labels[i]["r_Vo2To_vbs_true"])))
        st = sc["domains"][dom]["sets"][sc.get("primary", "전체 신호")]
        out["domains"][dom] = dict(n=len(fail), fail_rate=float(fail.mean()), warn_rate=st["warn_rate"], recall=st["recall"],
                                   kept_fail_rate=st["kept_fail_rate"], auroc=st["auroc"],
                                   auroc_by_signal={k: v["auroc"] for k, v in sc["domains"][dom]["sets"].items()},
                                   curve=dict(coverage=np.round(cov[sel], 4).tolist(), risk=np.round(risk[sel], 4).tolist()),
                                   examples=ex)
    return out


def orbit_section(proj: Projector, a, effi_T: bool) -> dict:
    out = dict(plan=None, passes=[])
    ps = ROOT / "outputs" / "orbit" / "plan_summary.json"
    if ps.exists():
        out["plan"] = json.loads(ps.read_text())
        rows = read_csv(ROOT / "outputs" / "orbit" / "plan_timeline.csv")
        out["plan_curves"] = {}
        for r in rows:
            key = f"{float(r['beta_deg']):.0f}|{r['hold']}"
            c = out["plan_curves"].setdefault(key, dict(t=[], p=[], eclipse=[]))
            c["t"].append(round(float(r["t_min"]), 2))
            c["p"].append(None if r["p_fail_map"] in ("", "None") else round(float(r["p_fail_map"]), 4))
            c["eclipse"].append(r["eclipse"] == "True")
    order = {"rbar-": 0, "vbar-": 1, "hbar-": 2, "hbar+": 3, "vbar+": 4}
    paths = sorted((ROOT / "outputs" / "orbit").glob(f"speedplus_orbit_*_{a.wd}.json"),
                   key=lambda q: order.get(json.loads(q.read_text())["hold"], 9))
    for res_path in paths:
        res = json.loads(res_path.read_text())
        run = res["run"]
        rdir = ROOT / "outputs" / "renders" / run
        cfg = json.loads((rdir / "jobs.json").read_text())
        labels = json.loads((rdir / "sunsweep" / "test.json").read_text())
        P = predictions(full_config(ROOT / "outputs" / "spnv2_eval_renders" / run / a.wd) / "sunsweep", labels, effi_T)
        rows = {r["name"]: r for r in read_csv(res_path.with_suffix(".csv"))}
        frames = []
        for i, lab in enumerate(labels):
            name = Path(lab["filename"]).stem
            r = rows[name]
            save_img(rdir / "sunsweep" / "images" / lab["filename"], OUT / "img" / "orbit" / run / lab["filename"])
            kp, src = pred_kp(proj, P, i)
            frames.append(dict(t=round(float(r["t_min"]), 3), u=round(float(r["u_deg"]), 2), phase=round(float(r["phase_deg"]), 1),
                               p_map=round(float(r["p_fail_map"]), 4), eR=fnum(r["heat_eR"], 1) if r["heat_eR"] else None,
                               fail=r["fail"] == "1", warn=r["warn"] == "1", img=f"img/orbit/{run}/{lab['filename']}", kp=kp))
        tl = read_csv(rdir / "timeline.csv")
        ecl = [[round(float(x["t_min"]), 3), round(float(x["u_deg"]), 2)] for x in tl if x["eclipse"] == "True"]
        out["passes"].append(dict(run=run, **{k: cfg["orbit"][k] for k in ("beta_deg", "hold", "hold_ko", "step_s", "period_s", "dist_m")},
                                  kp_true=proj.from_q(cfg["jobs"][0]["q"], cfg["jobs"][0]["r"]), result=res,
                                  eclipse=ecl, frames=frames))
    return out


def write_data(name: str, obj: dict) -> None:
    """data/<name>.json과, 서버 없이(file://) 열어도 읽히는 data/<name>.js (window.ORBITLIGHT.<name>)를 쓴다."""
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    (OUT / "data" / f"{name}.json").write_text(txt)
    (OUT / "data" / f"{name}.js").write_text(f"window.ORBITLIGHT=window.ORBITLIGHT||{{}};window.ORBITLIGHT.{name}={txt};\n")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--weights", default="offline")
    p.add_argument("--sweep-run", default="speedplus_sunsweep_v01")
    p.add_argument("--n-poses", type=int, default=6)
    p.add_argument("--sections", default="sweep,hil,orbit")
    p.add_argument("--clean", action="store_true")
    a = p.parse_args()
    a.wd = a.weights.replace(":", "_")
    if a.clean and OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    proj = Projector()
    sc_path = ROOT / "outputs" / "self_check" / a.wd / "summary.json"
    sc = json.loads(sc_path.read_text()) if sc_path.exists() else {"domains": {}, "effi_R_transposed": False}
    effi_T = bool(sc.get("effi_R_transposed", False))
    secs = a.sections.split(",")
    meta = dict(weights=a.weights, edges=EDGES, image_w=W_DISP, image_h=int(round(proj.Nv * W_DISP / proj.Nu)))
    if "sweep" in secs:
        write_data("sweep", dict(meta=meta, **sweep_section(proj, a, sc, effi_T)))
        print("[site] sweep")
    if "hil" in secs and sc.get("domains"):
        write_data("hil", dict(meta=meta, models=sc.get("models"), **hil_section(proj, a, sc, effi_T)))
        print("[site] hil")
    if "orbit" in secs:
        write_data("orbit", dict(meta=meta, **orbit_section(proj, a, effi_T)))
        print("[site] orbit")
    n = sum(1 for _ in (OUT / "img").rglob("*.jpg")) if (OUT / "img").exists() else 0
    mb = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"-> {OUT}: {n} images, {mb:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
