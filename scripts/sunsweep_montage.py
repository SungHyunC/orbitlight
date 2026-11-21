"""한 자세를 위상각별로 나란히 보여주는 예시 그림 (+ SPNv2 회전 오차 표시).

    python scripts/sunsweep_montage.py --run speedplus_sunsweep_v01 --poses 0,1,2 --azimuth 90
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2
import numpy as np
from scipy.io import loadmat

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run", default="speedplus_sunsweep_v01")
    p.add_argument("--weights", default="offline")
    p.add_argument("--poses", default="0,1,2")
    p.add_argument("--azimuth", type=float, default=90.0)
    p.add_argument("--phases", default="0,40,80,120,160")
    p.add_argument("--tile", type=int, default=260)
    a = p.parse_args()

    dom = ROOT / "outputs" / "renders" / a.run / "sunsweep"
    rows = list(csv.DictReader(open(dom / "meta.csv")))
    mat = ROOT / "outputs" / "spnv2_eval_renders" / a.run / a.weights / "efficientdet_d3" / "full_config" / "sunsweep" \
        / "per_sample_performance.mat"
    eR = np.ravel(loadmat(mat)["heat_eR"]) if mat.exists() else None
    phases = [float(x) for x in a.phases.split(",")]
    T = a.tile
    lines = []
    for pid in [int(x) for x in a.poses.split(",")]:
        mrow = next(r for r in rows if int(r["pose_id"]) == pid)
        m = cv2.imread(str(dom / "masks" / mrow["filename"].replace(".jpg", ".png")), 0)
        ys, xs = np.nonzero(m)
        cx, cy = (xs.min() + xs.max()) // 2, (ys.min() + ys.max()) // 2
        s = int(max(np.ptp(xs), np.ptp(ys)) * 0.62)
        tiles = []
        for ph in phases:
            i = next(i for i, r in enumerate(rows) if int(r["pose_id"]) == pid and float(r["phase_deg"]) == ph
                     and (ph == 0 or float(r["azimuth_deg"]) == a.azimuth))
            im = cv2.imread(str(dom / "images" / rows[i]["filename"]), 0)
            im = cv2.copyMakeBorder(im, s, s, s, s, cv2.BORDER_CONSTANT)
            im = cv2.resize(im[cy:cy + 2 * s, cx:cx + 2 * s], (T, T), interpolation=cv2.INTER_AREA)
            im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
            cv2.putText(im, f"phase {ph:g} deg", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 235, 235), 1, cv2.LINE_AA)
            if eR is not None:
                e = eR[i]
                bad = (not np.isfinite(e)) or e > 10
                txt = "rejected" if not np.isfinite(e) else f"rot. err {e:.1f} deg"
                # 실패 = 주황(#eb6834), 성공 = 회색 글씨. 색만으로 구분하지 않도록 "FAIL" 글자도 붙인다
                col = (52, 104, 235) if bad else (200, 200, 200)
                cv2.putText(im, txt + ("  FAIL" if bad else ""), (8, T - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1,
                            cv2.LINE_AA)
            tiles.append(im)
        lines.append(np.hstack([np.pad(t, ((2, 2), (2, 2), (0, 0)), constant_values=40) for t in tiles]))
    out = ROOT / "outputs" / "figures" / f"sunsweep_examples_{a.run}.png"
    cv2.imwrite(str(out), np.vstack(lines))
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
