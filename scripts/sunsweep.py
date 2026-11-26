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


def sample_material(rng: np.random.Generator) -> dict:
    """도메인 무작위화(domain randomization)용 재질·텍스처 값 한 세트.

    렌더러가 실제 위성 재질을 정확히 모르므로, 한 가지 모습에 과적합하지 않도록 넓게 흔든다.
    이미지는 결국 흑백이므로 색은 밝기(gray)만 바꾼다. 이름은 blender_render.MATERIALS의 키.
    """
    body_metal = float(rng.uniform(0.3, 1.0)) if rng.random() < 0.4 else 0.0
    mats = {
        "Oro_-_Pulido": dict(gray=float(rng.uniform(0.2, 0.9)), metallic=body_metal,
                             roughness=float(rng.uniform(0.1, 0.8))),
        "Espejo_(1)": dict(gray=float(rng.uniform(0.01, 0.2)), roughness=float(rng.uniform(0.02, 0.4))),
    }
    for name, gray in (("Cromo", 0.56), ("Aluminio_-_Satinado", 0.92), ("Acero_-_Satinado", 0.57),
                       ("Pintura_-_Esmaltado_brillante_(gris_oscuro)", 0.05), ("Revestimiento_-_Óxido_negro", 0.02)):
        mats[name] = dict(gray=float(np.clip(gray * rng.uniform(0.6, 1.4), 0.0, 1.0)))
    texture = dict(scale=float(np.exp(rng.uniform(np.log(2.0), np.log(200.0)))),   # 1/m, 로그 균등
                   albedo_contrast=float(rng.uniform(0.0, 0.6)),
                   roughness_contrast=float(rng.uniform(0.0, 0.5)),
                   bump=float(rng.uniform(0.0, 0.5)))
    return dict(materials=mats, texture=texture)


def cmd_jobs(a) -> None:
    run = ROOT / "outputs" / "renders" / a.run
    run.mkdir(parents=True, exist_ok=True)
    camera = json.loads((SPEED / "camera.json").read_text())
    labels = json.loads((SPEED / a.pose_source).read_text())
    rng = np.random.default_rng(a.seed)
    picks = sorted(rng.choice(len(labels), a.n_poses, replace=False).tolist())

    jobs, conds = [], []
    if a.random_per_pose > 0:
        # 학습용: 자세마다 태양 방향을 무작위로 (위상각 균등 0~phase_max, 방위각 균등, 태양 세기 범위 균등)
        for k, li in enumerate(picks):
            lab = labels[li]
            q, r = lab["q_vbs2tango_true"], lab["r_Vo2To_vbs_true"]
            M = blender_object_matrix(q, r)
            for j in range(a.random_per_pose):
                p = float(rng.uniform(0.0, a.phase_max))
                az = float(rng.uniform(0.0, 360.0))
                strength = float(rng.uniform(*a.strength_range))
                s_cam = sun_direction_cam(r, p, az)
                jobs.append(dict(
                    name=f"p{k:04d}_s{j}", pose_id=k, source_image=lab["filename"], q=q, r=r,
                    phase_deg=p, azimuth_deg=az, sun_strength=strength,
                    sun_dir_cam=s_cam.tolist(), sun_dir_world=(C_CV2BL @ s_cam).tolist(),
                    object_matrix=M.tolist(),
                ))
        desc = f"{a.n_poses} poses × {a.random_per_pose} random sun directions"
    else:
        for p in a.phases:
            for az in ([0.0] if p == 0 else a.azimuths):  # 위상각 0°는 방위각과 무관
                conds.append((p, az))
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
        desc = f"{a.n_poses} poses × {len(conds)} sun conditions"
    if a.randomize_materials:
        # 자세·태양 방향 난수열과 분리 (같은 seed면 재질만 다르고 자세·태양은 무작위화 안 한 run과 똑같다)
        mrng = np.random.default_rng(a.seed + 10007)
        for j in jobs:
            j["material"] = sample_material(mrng)
        desc += " + randomized materials"
    cfg = dict(
        created=time.strftime("%Y-%m-%d %H:%M:%S"),
        camera=camera, model=str(MODEL.relative_to(ROOT)), pose_source=a.pose_source, seed=a.seed, randomize_materials=a.randomize_materials,
        render=dict(sun_strength=a.sun_strength, samples=a.samples, denoise=True, max_bounces=6, seed=0, exposure=0.0,
                    color_depth=a.color_depth),
        post=dict(noise_std=a.noise_std, noise_offset=a.noise_offset, jpg_quality=95),
        conditions=[dict(phase_deg=p, azimuth_deg=az) for p, az in conds],
        jobs=jobs,
    )
    (run / "jobs.json").write_text(json.dumps(cfg, indent=1))
    print(f"{run / 'jobs.json'}: {desc} = {len(jobs)} images")


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


_W: dict = {}   # 병렬 변환 작업자마다 한 번 읽는 모형·마스크 캐시


def _init_worker(model_path: str) -> None:
    from orbitlight.render.postprocess import load_obj
    _W["VF"] = load_obj(Path(model_path))
    _W["masks"] = {}


def _post_job(task):
    """렌더 한 장을 SPEED+ 형식으로 (병렬 변환용). 노이즈 난수는 이미지마다 (seed + 1, 순번)으로 정해 작업자 수와 무관하다."""
    import cv2
    from orbitlight.render.postprocess import silhouette_mask, to_speedplus_image

    j, idx, run_dir, camera, post, seed, masks_only = task
    dom = run_dir / DOMAIN
    raw = run_dir / "raw" / f"{j['name']}.png"
    if not raw.exists():
        return None
    fn = f"{j['name']}.jpg"
    if masks_only:
        img = cv2.imread(str(dom / "images" / fn), cv2.IMREAD_GRAYSCALE)
    else:
        rng = np.random.default_rng([seed + 1, idx])
        img = to_speedplus_image(cv2.imread(str(raw), cv2.IMREAD_UNCHANGED), camera, rng, post["noise_std"], post["noise_offset"])
        cv2.imwrite(str(dom / "images" / fn), img, [cv2.IMWRITE_JPEG_QUALITY, post["jpg_quality"]])
    key = (j["pose_id"], tuple(np.round(j["q"], 9)), tuple(np.round(j["r"], 9)))
    if key not in _W["masks"]:
        V, F = _W["VF"]
        _W["masks"][key] = silhouette_mask(V, F, j["q"], j["r"], camera)
    m = _W["masks"][key]
    cv2.imwrite(str(dom / "masks" / fn.replace(".jpg", ".png")), m)
    fg = img[m > 0]
    label = dict(filename=fn, q_vbs2tango_true=j["q"], r_Vo2To_vbs_true=j["r"])
    row = dict(filename=fn, pose_id=j["pose_id"], source_image=j["source_image"],
               phase_deg=j["phase_deg"], azimuth_deg=j["azimuth_deg"],
               dist_m=float(np.linalg.norm(j["r"])),
               fg_mean=float(fg.mean()) if fg.size else 0.0,
               fg_p95=float(np.percentile(fg, 95)) if fg.size else 0.0,
               fg_sat_frac=float((fg >= 250).mean()) if fg.size else 0.0,
               fg_dark_frac=float((fg <= 10).mean()) if fg.size else 0.0)
    return label, row


def cmd_post(a) -> None:
    import cv2
    from orbitlight.render.postprocess import load_obj, silhouette_mask, to_speedplus_image

    if a.workers > 1:
        return _post_parallel(a)

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
        if a.masks_only:   # 이미지는 그대로 두고 마스크와 밝기 통계만 다시 계산
            img = cv2.imread(str(dom / "images" / fn), cv2.IMREAD_GRAYSCALE)
        else:
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
    if not a.masks_only:   # 라벨은 그대로이므로 다시 쓰지 않음 (SPNv2 전처리를 불필요하게 다시 돌리지 않게)
        (dom / "test.json").write_text(json.dumps(labels, indent=1))
    with open(dom / "meta.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(labels)} images -> {dom}")


def _post_parallel(a) -> None:
    from multiprocessing import Pool

    run = ROOT / "outputs" / "renders" / a.run
    cfg = json.loads((run / "jobs.json").read_text())
    dom = run / DOMAIN
    (dom / "images").mkdir(parents=True, exist_ok=True)
    (dom / "masks").mkdir(parents=True, exist_ok=True)
    (run / "camera.json").write_text(json.dumps(cfg["camera"], indent=2))
    tasks = [(j, i, run, cfg["camera"], cfg["post"], cfg["seed"], a.masks_only) for i, j in enumerate(cfg["jobs"])]
    with Pool(a.workers, initializer=_init_worker, initargs=(str(ROOT / cfg["model"]),)) as pool:
        res = [r for r in pool.imap(_post_job, tasks, chunksize=8) if r is not None]
    labels, rows = [r[0] for r in res], [r[1] for r in res]
    if not a.masks_only:
        (dom / "test.json").write_text(json.dumps(labels, indent=1))
    with open(dom / "meta.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(labels)} images -> {dom} ({a.workers} workers)")


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
    j.add_argument("--random-per-pose", type=int, default=0, help=">0이면 격자 대신 자세마다 무작위 태양 방향 N개 (학습용)")
    j.add_argument("--phase-max", type=float, default=170.0)
    j.add_argument("--strength-range", type=floats, default=floats("3,5"))
    j.add_argument("--randomize-materials", action="store_true", help="이미지마다 재질·텍스처 무작위 (도메인 무작위화)")
    j.add_argument("--color-depth", default="16", choices=["8", "16"], help="raw PNG 비트 수 (8이면 디스크 절반)")
    r = sub.add_parser("render")
    r.add_argument("--run", required=True)
    r.add_argument("--device", default="OPTIX")
    r.add_argument("--start", type=int, default=0)
    r.add_argument("--count", type=int, default=-1)
    o = sub.add_parser("post")
    o.add_argument("--run", required=True)
    o.add_argument("--masks-only", action="store_true", help="이미지는 다시 만들지 않고 마스크·meta.csv만 갱신")
    o.add_argument("--workers", type=int, default=1,
                   help=">1이면 병렬 변환. 노이즈 난수를 이미지마다 따로 정하므로 1(순차, v0.1과 같은 노이즈)과 값이 다르다")
    a = p.parse_args()
    {"jobs": cmd_jobs, "render": cmd_render, "post": cmd_post}[a.cmd](a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
