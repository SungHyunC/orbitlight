"""Blender 안에서 실행하는 렌더러. 작업 목록(JSON)을 받아 위성 자세·태양 방향별 이미지를 그린다.

    blender -b --factory-startup -P src/orbitlight/render/blender_render.py -- \
        --jobs outputs/renders/<run>/jobs.json --model data/models/spin_tango/tango_fix.obj

- 출력은 왜곡 없는 핀홀(pinhole) 카메라 이미지(PNG, 선형 아님: Standard 뷰 변환). 렌즈 왜곡·노이즈·흑백 변환은
  `orbitlight.render.postprocess`에서 따로 한다 (Blender 파이썬에는 OpenCV가 없음).
- 이 파일은 Blender 파이썬에서 돌아가므로 orbitlight 패키지를 import하지 않는다. 좌표 변환은 작업 목록을 만들 때
  `orbitlight.render.geometry`로 미리 계산해서 넘긴다 (object_matrix: 4×4, sun_dir_world: 위성→태양 단위 벡터).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

# 재질 이름(OBJ의 usemtl, SPIN 모델 원본 스페인어 이름) → Principled BSDF 값.
# 원래 .mtl 파일은 SPIN 저장소에 없어서, 이름이 뜻하는 재질을 단순한 물리 기반 값으로 잡았다.
MATERIALS = {
    # 몸체 외피. 이름은 '광택 금'이지만 SPEED+ 합성 이미지에서 몸체는 밝은 회색 무광에 가깝게 보여서 그쪽에 맞춤
    # (금속 재질로 두면 검은 우주만 비춰 몸체가 거의 검게 나옴, LOG render-002)
    "Oro_-_Pulido": dict(color=(0.60, 0.60, 0.60), metallic=0.0, roughness=0.45),
    "Cromo": dict(color=(0.55, 0.56, 0.58), metallic=1.0, roughness=0.08),                   # 크롬
    # 태양전지판 윗면(두께 4mm 판). 이름은 '거울'이지만 실제 전지판은 어두운 셀 + 유리 덮개 → 광택 유전체로 둠
    "Espejo_(1)": dict(color=(0.02, 0.02, 0.04), metallic=0.0, roughness=0.05),
    "Pintura_-_Esmaltado_brillante_(gris_oscuro)": dict(color=(0.05, 0.05, 0.05), metallic=0.0, roughness=0.25),
    "Aluminio_-_Satinado": dict(color=(0.91, 0.92, 0.92), metallic=1.0, roughness=0.35),
    "Acero_-_Satinado": dict(color=(0.56, 0.57, 0.58), metallic=1.0, roughness=0.35),
    "Revestimiento_-_Óxido_negro": dict(color=(0.02, 0.02, 0.02), metallic=0.0, roughness=0.5),
}
DEFAULT_MAT = dict(color=(0.5, 0.5, 0.5), metallic=0.0, roughness=0.5)


def parse_args(argv):
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--jobs", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--outdir", type=Path, help="기본값: jobs.json 옆 raw/")
    p.add_argument("--device", default="OPTIX", choices=["OPTIX", "CUDA", "CPU"])
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--count", type=int, default=-1)
    p.add_argument("--skip-existing", action="store_true")
    return p.parse_args(argv)


def setup_device(scene, device: str) -> None:
    scene.render.engine = "CYCLES"
    if device == "CPU":
        scene.cycles.device = "CPU"
        return
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = device
    prefs.get_devices()
    gpus = [d for d in prefs.devices if d.type == device]
    if not gpus:
        raise RuntimeError(f"{device} 장치를 찾지 못함 (CPU로 조용히 넘어가지 않도록 중단)")
    for d in prefs.devices:
        d.use = d.type == device
    scene.cycles.device = "GPU"


def build_material(name: str):
    spec = MATERIALS.get(name, DEFAULT_MAT)
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*spec["color"], 1.0)
    b.inputs["Metallic"].default_value = spec["metallic"]
    b.inputs["Roughness"].default_value = spec["roughness"]
    return m


def build_scene(cfg: dict, model: Path, device: str):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    setup_device(scene, device)

    # 모델: OBJ 원본 좌표를 그대로 (cm → m). forward/up 축을 지정해 Blender의 Y-up 변환을 막는다.
    bpy.ops.wm.obj_import(filepath=str(model), forward_axis="Y", up_axis="Z", global_scale=0.01)
    meshes = [o for o in scene.objects if o.type == "MESH"]
    for o in meshes:
        for slot in o.material_slots:
            if slot.material is not None:
                slot.material = build_material(slot.material.name)
    root = bpy.data.objects.new("tango_root", None)
    scene.collection.objects.link(root)
    for o in meshes:
        o.parent = root

    # 카메라: 원점, 회전 없음 (-Z 시선, +Y 위). SPEED+ 카메라 내부 파라미터를 그대로.
    cam = cfg["camera"]
    cd = bpy.data.cameras.new("cam")
    cd.sensor_fit = "HORIZONTAL"
    cd.sensor_width = cam["Nu"] * cam["ppx"] * 1e3            # [mm]
    cd.lens = cam["cameraMatrix"][0][0] * cam["ppx"] * 1e3      # fx[px] × 픽셀 크기 [mm]
    cd.shift_x = (cam["Nu"] / 2 - cam["cameraMatrix"][0][2]) / cam["Nu"]
    cd.shift_y = (cam["cameraMatrix"][1][2] - cam["Nv"] / 2) / cam["Nu"]
    cd.clip_start, cd.clip_end = 0.05, 100.0
    co = bpy.data.objects.new("cam", cd)
    scene.collection.objects.link(co)
    scene.camera = co

    # 태양: 평행광. 각지름 0.53° (지구 궤도에서 본 태양).
    ld = bpy.data.lights.new("sun", "SUN")
    ld.energy = cfg["render"]["sun_strength"]
    ld.angle = math.radians(0.53)
    sun = bpy.data.objects.new("sun", ld)
    scene.collection.objects.link(sun)

    # 배경: 우주 = 검정, 환경광 없음 (v0.1: 지구 반사광 제외)
    w = bpy.data.worlds.new("space")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    scene.world = w

    r = cfg["render"]
    scene.render.resolution_x, scene.render.resolution_y = cam["Nu"], cam["Nv"]
    scene.render.resolution_percentage = 100
    scene.cycles.samples = r["samples"]
    scene.cycles.use_denoising = r.get("denoise", True)
    if device == "OPTIX":
        scene.cycles.denoiser = "OPTIX"          # 기본(OIDN)은 CPU에서 돌아 느림
    scene.render.use_persistent_data = True      # 매 장마다 장면(BVH)을 다시 만들지 않음
    scene.cycles.max_bounces = r.get("max_bounces", 6)
    scene.cycles.seed = r.get("seed", 0)
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = r.get("exposure", 0.0)
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = str(r.get("color_depth", "16"))
    return scene, root, sun


def main() -> int:
    args = parse_args(sys.argv)
    cfg = json.loads(args.jobs.read_text())
    outdir = args.outdir or args.jobs.parent / "raw"
    outdir.mkdir(parents=True, exist_ok=True)
    scene, root, sun = build_scene(cfg, args.model, args.device)

    jobs = cfg["jobs"][args.start:]
    if args.count >= 0:
        jobs = jobs[: args.count]
    t0 = time.time()
    for i, job in enumerate(jobs):
        out = outdir / f"{job['name']}.png"
        if args.skip_existing and out.exists():
            continue
        root.matrix_world = Matrix(job["object_matrix"])
        s = Vector(job["sun_dir_world"]).normalized()
        # SUN 조명은 자기 -Z 방향으로 빛을 보낸다 → +Z가 태양 쪽(위성→태양)을 향하게 회전
        sun.rotation_euler = s.to_track_quat("Z", "Y").to_euler()
        sun.data.energy = job.get("sun_strength", cfg["render"]["sun_strength"])
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        if i % 20 == 0 or i == len(jobs) - 1:
            el = time.time() - t0
            print(f"[render] {i + 1}/{len(jobs)} {job['name']} {el:.0f}s ({el / (i + 1):.2f}s/img)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
