"""v0.1 태양 각도 실험: 고정된 위성 자세들에서 태양 방향(위상각 × 방위각)만 바꿔 가며 렌더링한다.

    python scripts/sunsweep.py jobs   --run speedplus_sunsweep_v01      # 작업 목록 jobs.json
    python scripts/sunsweep.py render --run speedplus_sunsweep_v01      # Blender 렌더링 (raw/*.png)
    python scripts/sunsweep.py post   --run speedplus_sunsweep_v01      # SPEED+ 형식으로 변환 (+ SPNv2 평가 준비)

결과 폴더 outputs/renders/<run>/ (git 제외) 는 SPNv2가 바로 읽는 구조다:
    camera.json, sunsweep/images/*.jpg, sunsweep/masks/*.png, sunsweep/test.json, sunsweep/meta.csv
SPNv2 평가: DATASET.ROOT=outputs/renders DATASET.DATANAME=<run>, 라벨 JSON = sunsweep/test.json
(SPNv2가 DATANAME에 'speedplus'가 있어야 읽으므로 run 이름은 speedplus_로 시작한다)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from orbitlight.render.geometry import (blender_object_matrix, C_CV2BL, phase_angle_deg,  # noqa: E402
                                        sun_direction_cam)

SPEED = ROOT / "data" / "speedplus" / "speedplusv2"
MODEL = ROOT / "data" / "models" / "spin_tango" / "tango_fix.obj"
BLENDER = Path(os.environ.get("BLENDER", Path.home() / "apps" / "blender-5.2.4-linux-x64" / "blender"))
DOMAIN = "sunsweep"


def floats(s: str) -> list[float]:
    return [float(x) for x in s.split(",") if x.strip()]


def cmd_jobs(a) -> None:
    run = ROOT / "outputs" / "renders" / a.run
    run.mkdir(parents=True, exist_ok=True)
    camera = json.loads((SPEED / "camera.json").read_text())
    labels = json.loads((SPEED / a.pose_source).read_text())
    rng = np.random.default_rng(a.seed)
    picks = sorted(rng.choice(len(labels), a.n_poses, replace=False).tolist())

    conds = []
    for p in a.phases:
        for az in ([0.0] if p == 0 else a.azimuths):  # 위상각 0°는 방위각과 무관
            conds.append((p, az))

    jobs = []
    for k, li in enumerate(picks):
        lab = labels[li]
        q, r = lab["q_vbs2tango_true"], lab["r_Vo2To_vbs_true"]
        M = blender_object_matrix(q, r)
        for p, az in conds:
            s_cam = sun_direction_cam(r, p, az)
            assert abs(phase_angle_deg(r, s_cam) - p) < 1e-6
            jobs.append(dict(
                name=f"p{k:03d}_ph{int(p):03d}_az{int(az):03d}",
                pose_id=k, source_image=lab["filename"], q=q, r=r,
                phase_deg=p, azimuth_deg=az,
                sun_dir_cam=s_cam.tolist(), sun_dir_world=(C_CV2BL @ s_cam).tolist(),
                object_matrix=M.tolist(),
            ))
    cfg = dict(
        created=time.strftime("%Y-%m-%d %H:%M:%S"),
        camera=camera, model=str(MODEL.relative_to(ROOT)), pose_source=a.pose_source, seed=a.seed,
        render=dict(sun_strength=a.sun_strength, samples=a.samples, denoise=True, max_bounces=6, seed=0, exposure=0.0),
        post=dict(noise_std=a.noise_std, noise_offset=a.noise_offset, jpg_quality=95),
        conditions=[dict(phase_deg=p, azimuth_deg=az) for p, az in conds],
        jobs=jobs,
    )
    (run / "jobs.json").write_text(json.dumps(cfg, indent=1))
    print(f"{run / 'jobs.json'}: {a.n_poses} poses × {len(conds)} sun conditions = {len(jobs)} images")


def cmd_render(a) -> None:
    run = ROOT / "outputs" / "renders" / a.run
    cmd = [str(BLENDER), "-b", "--factory-startup", "-P", str(ROOT / "src" / "orbitlight" / "render" / "blender_render.py"),
           "--", "--jobs", str(run / "jobs.json"), "--model", str(MODEL), "--device", a.device, "--skip-existing"]
    if a.count >= 0:
        cmd += ["--start", str(a.start), "--count", str(a.count)]
    print(" ".join(cmd), flush=True)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in p.stdout.splitlines():
        if line.startswith("[render]") or "Error" in line or "ERROR" in line or "Traceback" in line:
            print(line)
    if p.returncode != 0:
        print(p.stdout[-3000:])
        raise SystemExit(p.returncode)


def cmd_post(a) -> None:
    import cv2
    from orbitlight.render.postprocess import load_obj, silhouette_mask, to_speedplus_image

    run = ROOT / "outputs" / "renders" / a.run
    cfg = json.loads((run / "jobs.json").read_text())
    camera, post = cfg["camera"], cfg["post"]
    dom = run / DOMAIN
    (dom / "images").mkdir(parents=True, exist_ok=True)
    (dom / "masks").mkdir(parents=True, exist_ok=True)
    (run / "camera.json").write_text(json.dumps(camera, indent=2))
    V, F = load_obj(ROOT / cfg["model"])
    rng = np.random.default_rng(cfg["seed"] + 1)

    labels, rows, masks_done = [], [], {}
    for j in cfg["jobs"]:
        raw = run / "raw" / f"{j['name']}.png"
        if not raw.exists():
            continue
        fn = f"{j['name']}.jpg"
        img = to_speedplus_image(cv2.imread(str(raw), cv2.IMREAD_UNCHANGED), camera, rng,
                                 post["noise_std"], post["noise_offset"])
        cv2.imwrite(str(dom / "images" / fn), img, [cv2.IMWRITE_JPEG_QUALITY, post["jpg_quality"]])
        # 마스크는 자세에만 의존 → 자세당 한 번 계산해서 재사용
        if j["pose_id"] not in masks_done:
            masks_done[j["pose_id"]] = silhouette_mask(V, F, j["q"], j["r"], camera)
        m = masks_done[j["pose_id"]]
        cv2.imwrite(str(dom / "masks" / fn.replace(".jpg", ".png")), m)
        fg = img[m > 0]
        labels.append(dict(filename=fn, q_vbs2tango_true=j["q"], r_Vo2To_vbs_true=j["r"]))
        rows.append(dict(filename=fn, pose_id=j["pose_id"], source_image=j["source_image"],
                         phase_deg=j["phase_deg"], azimuth_deg=j["azimuth_deg"],
                         dist_m=float(np.linalg.norm(j["r"])),
                         fg_mean=float(fg.mean()) if fg.size else 0.0,
                         fg_p95=float(np.percentile(fg, 95)) if fg.size else 0.0,
                         fg_sat_frac=float((fg >= 250).mean()) if fg.size else 0.0,
                         fg_dark_frac=float((fg <= 10).mean()) if fg.size else 0.0))
    (dom / "test.json").write_text(json.dumps(labels, indent=1))
    with open(dom / "meta.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(labels)} images -> {dom}")


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("jobs")
    j.add_argument("--run", required=True)
    j.add_argument("--n-poses", type=int, default=50)
    j.add_argument("--pose-source", default="synthetic/validation.json")
    j.add_argument("--phases", type=floats, default=floats("0,20,40,60,80,100,120,140,160"))
    j.add_argument("--azimuths", type=floats, default=floats("0,45,90,135,180,225,270,315"))
    j.add_argument("--sun-strength", type=float, default=5.0)
    j.add_argument("--samples", type=int, default=64)
    j.add_argument("--noise-std", type=float, default=3.0)
    j.add_argument("--noise-offset", type=float, default=2.0)
    j.add_argument("--seed", type=int, default=0)
    r = sub.add_parser("render")
    r.add_argument("--run", required=True)
    r.add_argument("--device", default="OPTIX")
    r.add_argument("--start", type=int, default=0)
    r.add_argument("--count", type=int, default=-1)
    o = sub.add_parser("post")
    o.add_argument("--run", required=True)
    a = p.parse_args()
    {"jobs": cmd_jobs, "render": cmd_render, "post": cmd_post}[a.cmd](a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
