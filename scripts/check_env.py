"""Phase 0 환경 점검 스크립트.

PyTorch GPU 인식, MuJoCo, Blender Cycles GPU 렌더링을 한 번에 확인한다.

    python scripts/check_env.py            # 전부
    python scripts/check_env.py --skip-blender
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_BLENDER = Path.home() / "apps" / "blender-5.2.4-linux-x64" / "blender"


def check_torch() -> bool:
    import torch

    print(f"[torch] version={torch.__version__} cuda_build={torch.version.cuda}")
    ok = torch.cuda.is_available()
    print(f"[torch] cuda.is_available()={ok}")
    if not ok:
        return False
    name = torch.cuda.get_device_name(0)
    total = torch.cuda.get_device_properties(0).total_memory / 2**30
    print(f"[torch] device={name} vram={total:.1f}GiB")
    # 실제로 GPU 연산이 도는지 작은 행렬곱으로 확인
    a = torch.randn(4096, 4096, device="cuda")
    torch.cuda.synchronize()
    t = time.perf_counter()
    for _ in range(10):
        a @ a
    torch.cuda.synchronize()
    dt = time.perf_counter() - t
    print(f"[torch] 10x matmul 4096^2: {dt * 1000:.1f} ms")
    return True


def check_mujoco() -> bool:
    import mujoco

    model = mujoco.MjModel.from_xml_string(
        "<mujoco><worldbody><body><freejoint/><geom size='0.1'/></body></worldbody></mujoco>"
    )
    data = mujoco.MjData(model)
    for _ in range(100):
        mujoco.mj_step(model, data)
    print(f"[mujoco] version={mujoco.__version__} sim_time={data.time:.3f}s z={data.qpos[2]:.4f}")
    return True


BLENDER_TEST = r"""
import bpy, sys
argv = sys.argv[sys.argv.index("--") + 1:]
out, backend = argv[0], argv[1]
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = backend
prefs.get_devices()
used = []
for d in prefs.devices:
    d.use = d.type == backend
    if d.use:
        used.append(d.name)
print("BLENDER_DEVICES", backend, used)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "GPU"
scene.cycles.samples = 64
scene.render.resolution_x = 640
scene.render.resolution_y = 480
# 기본 장면의 조명을 태양광(평행광)으로 바꿔 우주 조명과 비슷하게
light = bpy.data.objects["Light"]
light.data.type = "SUN"
light.data.energy = 5.0
scene.world.color = (0, 0, 0)
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
"""


def check_blender(blender: Path) -> bool:
    if not blender.exists():
        found = shutil.which("blender")
        if not found:
            print(f"[blender] 없음: {blender}")
            return False
        blender = Path(found)
    ok_any = False
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "t.py"
        script.write_text(BLENDER_TEST)
        for backend in ("OPTIX", "CUDA"):
            out = Path(tmp) / f"{backend}.png"
            t = time.perf_counter()
            r = subprocess.run(
                [str(blender), "-b", "--factory-startup", "-P", str(script), "--", str(out), backend],
                capture_output=True,
                text=True,
            )
            dt = time.perf_counter() - t
            devices = [l for l in r.stdout.splitlines() if l.startswith("BLENDER_DEVICES")]
            # GPU 장치가 하나도 안 잡히면 Cycles가 조용히 CPU로 렌더링하므로 실패로 본다
            has_gpu = bool(devices) and not devices[0].endswith("[]")
            ok = r.returncode == 0 and out.exists() and has_gpu
            print(f"[blender] {backend}: ok={ok} {devices[0] if devices else ''} wall={dt:.1f}s")
            if not ok:
                print(r.stdout[-1500:], r.stderr[-1500:])
            ok_any |= ok
    return ok_any


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--blender", type=Path, default=Path(os.environ.get("BLENDER", DEFAULT_BLENDER)))
    p.add_argument("--skip-blender", action="store_true")
    args = p.parse_args()

    results = {"torch": check_torch(), "mujoco": check_mujoco()}
    if not args.skip_blender:
        results["blender"] = check_blender(args.blender)
    print("SUMMARY", results)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
