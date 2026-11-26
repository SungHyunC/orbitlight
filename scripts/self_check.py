"""실패 자가 경고(self-check): SPNv2가 "이번 추정은 틀렸을 수 있다"를 스스로 알리는 점수.

    python scripts/self_check.py                               # offline 가중치
    python scripts/self_check.py --weights ftdr_v01:final      # 미세조정 모델

실패 지도(어디서 틀리나)의 다음 단계. 재학습 없이 SPNv2 평가 결과와 입력 이미지만 쓴다.

신호
- head_dR : 두 헤드가 낸 회전의 차이 [deg]. heatmap 헤드(키포인트 → PnP)와 EfficientPose 헤드(회전 직접 회귀)는
            계산 경로가 달라서, 둘이 크게 어긋나면 적어도 하나는 틀렸다.
- head_dT : 두 헤드의 위치 차이 / 거리
- peak_*  : 키포인트 11개 히트맵 최댓값(확신도). 평균, 최솟값, 다섯 번째로 큰 값(PnP에 최소 5개 필요), 0.5 넘는 개수.
            third_party/patches/spnv2-heatmap-peaks.patch가 저장한다.
- img_*   : 예측 상자(bbox) 안 밝기. 어두운(≤10) 비율, 밝은(≥40) 비율, 평균, 포화(≥250) 비율, 상자 넓이 비율
- 거부(heatmap 헤드가 자세 계산을 포기)는 그 자체로 경고다. 점수와 따로 센다.

평가 원칙 (실패 지도의 교훈: 합성에서 좋아진 것은 실물 조명에서 확인한다)
- 점수 모델(로지스틱 회귀)과 경고 기준은 렌더(태양 실험)에서만 정한다. lightbox·sunlamp(실물 조명 HIL)은 평가에만 쓴다.
- 실패 = heatmap 회전 오차 10° 초과 또는 거부 (실패 지도와 같은 기준).
- AUROC는 거부를 뺀 "답을 낸 이미지"에서 잰다 (거부는 자명하게 잡히므로).
- 경고 기준: 렌더에서 답을 낸 실패의 90%를 잡는 점수. 그 기준을 HIL에 그대로 적용해 경고율과 남은 실패율을 본다.

출력: outputs/self_check/<w>/features_<도메인>.csv, summary.json / docs/figures/self_check_<w>.png
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from scipy.io import loadmat
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from orbitlight.eval.spnv2_results import load_per_sample  # noqa: E402
from orbitlight.render.geometry import quat2dcm  # noqa: E402

FAIL_DEG = 10.0
RECALL_TARGET = 0.90
SPEED = ROOT / "data" / "speedplus" / "speedplusv2"
FEATURES = ["log_head_dR", "log_head_dT", "peak_mean", "peak_min", "peak_5th", "peak_n05",
            "img_dark", "img_lit", "img_mean", "img_sat", "box_area"]
SINGLE = {"두 헤드 불일치": ["log_head_dR"], "키포인트 확신도": ["peak_mean", "peak_5th"], "밝기(어두운 비율)": ["img_dark"]}


def rot_angle_deg(Ra: np.ndarray, Rb: np.ndarray) -> np.ndarray:
    """회전행렬 묶음 사이 각 [deg]: arccos((tr(Ra^T Rb) - 1) / 2)."""
    tr = np.einsum("nij,nij->n", Ra, Rb)
    return np.degrees(np.arccos(np.clip((tr - 1.0) / 2.0, -1.0, 1.0)))


def full_config(d: Path) -> Path:
    return d / "efficientdet_d3" / "full_config"


def label_rows(json_path: Path) -> list[dict]:
    return json.loads(json_path.read_text())


def load_domain(eval_dir: Path, img_dir: Path, labels: list[dict], effi_transpose: bool | None) -> tuple[dict, bool]:
    ps = load_per_sample(eval_dir / "per_sample_performance.mat")
    pr = loadmat(eval_dir / "predictions_pose.mat")
    n = len(ps["h_reject"])
    assert len(labels) == n, (eval_dir, len(labels), n)
    reject = ps["h_reject"]
    heat_q = np.asarray(pr["heat_q"], float).reshape(n, 4)
    heat_t = np.asarray(pr["heat_t"], float).reshape(n, 3)
    effi_R = np.asarray(pr["effi_R"], float).reshape(n, 3, 3)
    effi_t = np.asarray(pr["effi_t"], float).reshape(n, 3)
    bbox = np.asarray(pr["bbox"], float).reshape(n, 4)
    peak = np.asarray(pr["heat_peak"], float).reshape(n, -1) if "heat_peak" in pr else np.full((n, 11), np.nan)

    # EfficientPose 회전행렬의 규약 확인: 정답 DCM과의 각이 SPNv2가 저장한 effi_eR과 같아야 한다
    R_gt = np.stack([quat2dcm(l["q_vbs2tango_true"]) for l in labels])
    if effi_transpose is None:
        k = min(500, n)
        a_plain = rot_angle_deg(R_gt[:k], effi_R[:k])
        a_trans = rot_angle_deg(R_gt[:k], np.transpose(effi_R[:k], (0, 2, 1)))
        ref = ps["effi_eR"][:k]
        effi_transpose = bool(np.nanmedian(np.abs(a_trans - ref)) < np.nanmedian(np.abs(a_plain - ref)))
        err = np.nanmedian(np.abs((a_trans if effi_transpose else a_plain) - ref))
        assert err < 0.05, f"EfficientPose 회전 규약을 확인하지 못함 (중앙값 차이 {err:.3f}°)"
    if effi_transpose:
        effi_R = np.transpose(effi_R, (0, 2, 1))

    ok = ~reject & np.all(np.isfinite(heat_q), axis=1)
    R_heat = np.full((n, 3, 3), np.nan)
    R_heat[ok] = np.stack([quat2dcm(q) for q in heat_q[ok]])
    head_dR = np.full(n, np.nan)
    head_dR[ok] = rot_angle_deg(R_heat[ok], effi_R[ok])
    head_dT = np.linalg.norm(heat_t - effi_t, axis=1) / np.maximum(np.linalg.norm(effi_t, axis=1), 1e-6)

    # 예측 상자 안 밝기. 상자 좌표는 정규화 값이거나 입력(768×512) 픽셀 값이다
    img_feats = np.full((n, 5), np.nan)
    for i, lab in enumerate(labels):
        img = cv2.imread(str(img_dir / lab["filename"]), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        H, W = img.shape
        b = bbox[i].copy()
        if np.nanmax(np.abs(b)) <= 1.5:
            b *= [W, H, W, H]
        x1, y1, x2, y2 = np.clip(np.round(b), 0, [W, H, W, H]).astype(int)
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        roi = img[y1:y2, x1:x2].astype(np.float32)
        img_feats[i] = [(roi <= 10).mean(), (roi >= 40).mean(), roi.mean() / 255.0, (roi >= 250).mean(),
                        (x2 - x1) * (y2 - y1) / (W * H)]

    ps_sorted = -np.sort(-peak, axis=1)
    eR = ps["heat_eR"]
    fail = reject | ~np.isfinite(eR) | (np.nan_to_num(eR, nan=np.inf) > FAIL_DEG)
    d = dict(filename=np.array([l["filename"] for l in labels]), reject=reject, fail=fail, heat_eR=eR, effi_eR=ps["effi_eR"],
             head_dR=head_dR, head_dT=head_dT, log_head_dR=np.log1p(head_dR), log_head_dT=np.log1p(10 * head_dT),
             peak_mean=np.nanmean(peak, axis=1), peak_min=np.nanmin(peak, axis=1), peak_5th=ps_sorted[:, 4],
             peak_n05=(peak > 0.5).sum(axis=1).astype(float),
             img_dark=img_feats[:, 0], img_lit=img_feats[:, 1], img_mean=img_feats[:, 2], img_sat=img_feats[:, 3],
             box_area=img_feats[:, 4])
    return d, effi_transpose


def usable(d: dict, feats: list[str]) -> np.ndarray:
    """답을 냈고(거부 아님) 신호가 모두 있는 이미지."""
    m = ~d["reject"]
    for f in feats:
        m &= np.isfinite(d[f])
    return m


def fit_logreg(X: np.ndarray, y: np.ndarray, l2: float = 1e-2) -> dict:
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = np.c_[np.ones(len(X)), (X - mu) / sd]

    def f(w):
        s = Z @ w
        loss = np.mean(np.logaddexp(0.0, s) - y * s) + 0.5 * l2 * np.sum(w[1:] ** 2)
        g = Z.T @ (expit(s) - y) / len(y) + l2 * np.r_[0.0, w[1:]]
        return loss, g

    w = minimize(f, np.zeros(Z.shape[1]), jac=True, method="L-BFGS-B").x
    return dict(mu=mu, sd=sd, w=w)


def score(model: dict, X: np.ndarray) -> np.ndarray:
    return np.c_[np.ones(len(X)), (X - model["mu"]) / model["sd"]] @ model["w"]


def auroc(s: np.ndarray, y: np.ndarray) -> float:
    pos, neg = y.sum(), (~y).sum()
    if pos == 0 or neg == 0:
        return float("nan")
    r = rankdata(s)
    return float((r[y].sum() - pos * (pos + 1) / 2) / (pos * neg))


def risk_coverage(s_all: np.ndarray, fail: np.ndarray, reject: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """확신 높은 순으로 받아들일 때 (받아들인 비율, 받아들인 것 중 실패율). 거부는 항상 마지막(받지 않음)."""
    s = np.where(reject | ~np.isfinite(s_all), np.inf, s_all)
    order = np.argsort(s, kind="stable")
    f = fail[order].astype(float)
    k = np.arange(1, len(f) + 1)
    cov, risk = k / len(f), np.cumsum(f) / k
    keep = np.isfinite(s[order])
    return cov[keep], risk[keep]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--weights", default="offline")
    p.add_argument("--run", default="speedplus_sunsweep_v01", help="점수 모델과 경고 기준을 정할 렌더 run")
    a = p.parse_args()
    wd = a.weights.replace(":", "_")
    out = ROOT / "outputs" / "self_check" / wd
    out.mkdir(parents=True, exist_ok=True)

    rdir = ROOT / "outputs" / "renders" / a.run / "sunsweep"
    sources = {
        "renders": (full_config(ROOT / "outputs" / "spnv2_eval_renders" / a.run / wd) / "sunsweep",
                    rdir / "images_768x512_RGB", label_rows(rdir / "test.json")),
        "synthetic": (full_config(ROOT / "outputs" / "spnv2_eval" / wd) / "synthetic",
                      SPEED / "synthetic" / "images_768x512_RGB", label_rows(SPEED / "synthetic" / "validation.json")),
        "lightbox": (full_config(ROOT / "outputs" / "spnv2_eval" / wd) / "lightbox",
                     SPEED / "lightbox" / "images_768x512_RGB", label_rows(SPEED / "lightbox" / "test.json")),
        "sunlamp": (full_config(ROOT / "outputs" / "spnv2_eval" / wd) / "sunlamp",
                    SPEED / "sunlamp" / "images_768x512_RGB", label_rows(SPEED / "sunlamp" / "test.json")),
    }
    data, tr = {}, None
    for name, (ed, idir, labels) in sources.items():
        if not (ed / "predictions_pose.mat").exists():
            print(f"[skip] {name}: {ed} 없음")
            continue
        data[name], tr = load_domain(ed, idir, labels, tr)
        d = data[name]
        print(f"[load] {name}: {len(d['fail'])} images, reject {d['reject'].sum()}, fail {d['fail'].mean():.3f}", flush=True)
        with open(out / f"features_{name}.csv", "w", newline="") as fh:
            cols = ["filename", "reject", "fail", "heat_eR", "effi_eR", "head_dR", "head_dT"] + FEATURES[2:]
            w = csv.writer(fh)
            w.writerow(cols)
            for i in range(len(d["fail"])):
                w.writerow([d[c][i] if c == "filename" else (int(d[c][i]) if d[c].dtype == bool else
                            ("" if not np.isfinite(d[c][i]) else round(float(d[c][i]), 5))) for c in cols])
    assert "renders" in data, "점수 모델을 정할 렌더 평가 결과가 없다"
    has_peak = bool(np.isfinite(data["renders"]["peak_mean"]).any())
    feats = FEATURES if has_peak else [f for f in FEATURES if not f.startswith("peak")]
    sets = {"전체 신호": feats, **{k: v for k, v in SINGLE.items() if has_peak or not v[0].startswith("peak")}}

    # 1) 렌더에서 점수 모델과 경고 기준
    R = data["renders"]
    summary = dict(weights=a.weights, run=a.run, fail_deg=FAIL_DEG, recall_target=RECALL_TARGET,
                   effi_R_transposed=tr, features=feats, models={}, domains={})
    models = {}
    for sname, fs in sets.items():
        m = usable(R, fs)
        X, y = np.c_[[R[f][m] for f in fs]].T, R["fail"][m]
        models[sname] = fit_logreg(X, y)
        s = score(models[sname], X)
        thr = float(np.quantile(s[y], 1.0 - RECALL_TARGET))   # 렌더 실패의 90%가 이 점수 이상
        models[sname]["thr"] = thr
        summary["models"][sname] = dict(features=fs, threshold=thr, n_fit=int(m.sum()), fail_fit=float(y.mean()),
                                        weights={f: round(float(v), 4) for f, v in zip(fs, models[sname]["w"][1:])},
                                        mu=models[sname]["mu"].tolist(), sd=models[sname]["sd"].tolist(),
                                        w=models[sname]["w"].tolist())

    # 2) 도메인별 평가 (렌더는 맞춘 데이터라 참고용)
    curves = {}
    for name, d in data.items():
        row = dict(n=int(len(d["fail"])), reject=int(d["reject"].sum()), fail_rate=float(d["fail"].mean()), sets={})
        for sname, fs in sets.items():
            m = usable(d, fs)
            X = np.c_[[d[f][m] for f in fs]].T
            s_all = np.full(len(d["fail"]), np.nan)
            s_all[m] = score(models[sname], X)
            y = d["fail"][m]
            warn = d["reject"] | (np.nan_to_num(s_all, nan=np.inf) >= models[sname]["thr"])
            kept = ~warn
            row["sets"][sname] = dict(
                auroc=auroc(s_all[m], y), n_answered=int(m.sum()), answered_fail_rate=float(y.mean()) if m.any() else None,
                warn_rate=float(warn.mean()), recall=float((warn & d["fail"]).sum() / max(d["fail"].sum(), 1)),
                kept_fail_rate=float(d["fail"][kept].mean()) if kept.any() else None)
            if sname == "전체 신호" or sname == "두 헤드 불일치":
                curves[(name, sname)] = risk_coverage(s_all, d["fail"], d["reject"])
        summary["domains"][name] = row
        s0 = row["sets"]["전체 신호"]
        print(f"[{name}] 실패율 {row['fail_rate']:.3f} → 경고 {s0['warn_rate']:.3f}, 경고 뒤 남은 실패율 "
              f"{s0['kept_fail_rate']:.3f}, 실패 중 경고 {s0['recall']:.3f}, AUROC {s0['auroc']:.3f}", flush=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    plot(summary, curves, ROOT / "docs" / "figures" / f"self_check_{wd}.png")
    print(f"-> {out / 'summary.json'}")
    return 0


def plot(summary: dict, curves: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
    COL = {"lightbox": "#d9622b", "sunlamp": "#2b7bd9", "synthetic": "#8a8a86", "renders": "#3a9e6b"}
    doms = [d for d in ("lightbox", "sunlamp") if d in summary["domains"]]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), facecolor=SURFACE)
    ax = axes[0]
    for d in doms:
        for sname, ls in (("전체 신호", "-"), ("두 헤드 불일치", "--")):
            if (d, sname) in curves:
                cov, risk = curves[(d, sname)]
                ax.plot(cov * 100, risk * 100, ls, color=COL[d], lw=2 if ls == "-" else 1.3,
                        label=f"{d} · {'all signals' if sname == '전체 신호' else 'head disagreement'}")
        fr = summary["domains"][d]["fail_rate"]
        ax.axhline(fr * 100, color=COL[d], lw=0.8, ls=":")
    ax.set_xlabel("images accepted (most confident first) [%]")
    ax.set_ylabel("failure rate among accepted [%]")
    ax.set_title("(a) Risk-coverage on real-lighting HIL images\nscore fitted on renders only; dotted = no self-check", loc="left", fontsize=10)
    ax.legend(frameon=False, fontsize=8)
    ax = axes[1]
    snames = list(next(iter(summary["domains"].values()))["sets"].keys())
    x = np.arange(len(snames))
    for k, d in enumerate(doms):
        v = [summary["domains"][d]["sets"][s]["auroc"] for s in snames]
        ax.bar(x + (k - 0.5) * 0.38, v, 0.36, color=COL[d], label=d)
    ax.set_xticks(x, ["all", "head dR", "keypoint peak", "darkness"][: len(snames)])
    ax.set_ylim(0.5, 1.0)
    ax.set_ylabel("AUROC (answered images)")
    ax.set_title("(b) Which signal finds failures on HIL", loc="left", fontsize=10)
    ax.legend(frameon=False, fontsize=8)
    for ax in axes:
        ax.set_facecolor(SURFACE)
        ax.grid(color=GRID, lw=0.6)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors=INK2)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE)


if __name__ == "__main__":
    raise SystemExit(main())
