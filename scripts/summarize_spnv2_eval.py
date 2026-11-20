"""SPNv2 기준 평가 결과(mean_performance.txt)를 표로 모은다.

    python scripts/summarize_spnv2_eval.py            # 마크다운 표 출력
    python scripts/summarize_spnv2_eval.py --csv out.csv

SPNv2 코드의 최종 점수(final_pose) 정의에 맞춰
  E_R  = heatmap 헤드의 회전 오차 [deg]   (키포인트 + PnP로 구한 자세)
  E_T  = efficientpose 헤드의 위치 오차 [m] (직접 회귀한 위치)
  E_pose = 이미지별 (회전 점수 + 정규화 위치 점수)의 평균, SPEC2021 방식(임계값 이하 0 처리)
로 정리한다. 논문 값은 SPNv2 README(커밋 debee80)의 표를 옮긴 것이다.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "outputs" / "spnv2_eval"

# SPNv2 README, φ=3 BN. 합성 검증셋 값은 README에 없음.
PAPER = {
    ("offline", "lightbox"): (0.175, 6.479, 0.142),
    ("offline", "sunlamp"): (0.225, 11.065, 0.230),
    ("odr_B4_N1024", "lightbox"): (0.142, 5.624, 0.122),
    ("odr_B4_N1024", "sunlamp"): (0.182, 9.601, 0.198),
}
DOMAINS = ["synthetic", "lightbox", "sunlamp"]
WEIGHTS = ["offline", "odr_B4_N1024"]


def parse(path: Path) -> dict[str, float]:
    out, head = {}, None
    for line in path.read_text().splitlines():
        if m := re.match(r"Head: (\w+)", line):
            head = m.group(1)
        elif m := re.match(r"(\w+) \[[^\]]*\]: ([-\d.eE+naN]+)", line):
            out[f"{head}.{m.group(1)}"] = float(m.group(2))
        elif m := re.match(r"# reject: ([\d,]+)", line):
            out["heatmap.reject"] = int(m.group(1).replace(",", ""))
        elif m := re.match(r"Final Pose: ([-\d.eE+naN]+)", line):
            out["final_pose"] = float(m.group(1))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path)
    args = p.parse_args()

    rows = []
    for w in WEIGHTS:
        for d in DOMAINS:
            f = EVAL / w / "efficientdet_d3" / "full_config" / d / "mean_performance.txt"
            if not f.exists():
                continue
            r = parse(f)
            paper = PAPER.get((w, d))
            rows.append({
                "weights": w,
                "domain": d,
                "E_T_m": r.get("efficientpose.eT"),
                "E_R_deg": r.get("heatmap.eR"),
                "E_pose": r.get("final_pose"),
                "effi_E_R_deg": r.get("efficientpose.eR"),
                "heat_reject": r.get("heatmap.reject"),
                "iou": r.get("efficientpose.iou"),
                "paper_E_T_m": paper[0] if paper else None,
                "paper_E_R_deg": paper[1] if paper else None,
                "paper_E_pose": paper[2] if paper else None,
            })

    fmt = lambda v, n=3: "-" if v is None else (f"{v:,d}" if isinstance(v, int) else f"{v:.{n}f}")
    print("| 가중치 | 도메인 | E_T [m] | E_R [°] | E_pose | 논문 E_T | 논문 E_R | 논문 E_pose | heatmap 거부 수 | bbox IoU |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['weights']} | {r['domain']} | {fmt(r['E_T_m'])} | {fmt(r['E_R_deg'], 2)} | {fmt(r['E_pose'])} "
              f"| {fmt(r['paper_E_T_m'])} | {fmt(r['paper_E_R_deg'], 2)} | {fmt(r['paper_E_pose'])} "
              f"| {fmt(r['heat_reject'])} | {fmt(r['iou'])} |")

    if args.csv:
        with args.csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
