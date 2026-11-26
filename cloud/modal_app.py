"""OrbitLight를 Modal GPU에서 돌린다: SPEED+ 준비, SPNv2 평가·미세조정, Blender 렌더.

GPU가 없는 컴퓨터에서도 이 저장소의 scripts/*.sh, scripts/*.py를 그대로 쓰기 위한 얇은 포장이다.
컨테이너 안 /work/orbitlight에 저장소를 복사하고, data/와 outputs/는 Modal 볼륨(orbitlight-data)에,
third_party/spnv2는 이미지에 미리 받아 둔 SPNv2(고정 커밋 + third_party/patches)에 연결한다.

    M="modal"   # 이 맥에서는 M="uvx --python 3.12 modal"
    $M run cloud/modal_app.py::gpu_info                          # GPU·드라이버·torch·Blender 장치 확인
    $M run --detach cloud/modal_app.py::fetch_data               # SPEED+ 16.9 GB + Tango 모형 → 볼륨, SPNv2 전처리
    $M volume put orbitlight-data ~/Downloads/spnv2_efficientnetb3_fullconfig_offline.pth.tar /outputs/pretrained/
    $M run cloud/modal_app.py::run_sh --cmd "bash scripts/eval_spnv2_baseline.sh" --gpu L4
    $M run cloud/modal_app.py::run_sh --cmd "python scripts/sunsweep.py jobs --run speedplus_sunsweep_v01"   # GPU 없이
    $M run cloud/modal_app.py::run_render --run speedplus_sunsweep_v01 --chunks 16
    $M volume get orbitlight-data /outputs/<경로> outputs/<경로>   # 결과를 로컬로

비용: 초 단위 과금. 모든 함수에 시간 제한(timeout)을 둬서 멈춘 작업이 계속 돌지 않게 한다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import modal

REPO = Path(__file__).resolve().parents[1]
VOL = "/vol"                    # 볼륨 마운트 위치: /vol/data, /vol/outputs
SRC = "/src/orbitlight"         # 업로드된 저장소 (읽기 전용으로 취급)
WORK = "/work/orbitlight"       # 실행용 복사본 (data/ outputs/ third_party/spnv2 링크를 건다)
BLENDER_VER = "5.2.4"           # LOG env-001과 같은 버전
SPNV2_COMMIT = "debee80"        # third_party/README.md와 같은 커밋

vol = modal.Volume.from_name("orbitlight-data", create_if_missing=True, version=2)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "git", "curl", "unzip", "xz-utils", "procps",
        # 헤드리스 Blender(Cycles)와 OpenCV가 찾는 공유 라이브러리
        "libgl1", "libegl1", "libglib2.0-0", "libsm6", "libx11-6", "libxext6", "libxfixes3",
        "libxi6", "libxkbcommon0", "libxrender1", "libxxf86vm1", "libgomp1",
    )
    .pip_install_from_requirements(str(REPO / "requirements.txt"))   # torch 2.14.1+cu130 (Modal 드라이버 620에서 동작)
    # Stanford(SPEED+) 서버 인증서의 루트(SSL.com TLS RSA Root CA 2022)가 Debian 기본 인증서 목록에 없어서
    # curl이 거부한다 → 최신 certifi 묶음을 curl과 Python이 쓰게 한다
    .pip_install("certifi>=2025.1.31")
    .env({"CURL_CA_BUNDLE": "/usr/local/lib/python3.11/site-packages/certifi/cacert.pem",
          "SSL_CERT_FILE": "/usr/local/lib/python3.11/site-packages/certifi/cacert.pem"})
    .run_commands(
        f"curl -fsSL https://download.blender.org/release/Blender{BLENDER_VER.rsplit('.', 1)[0]}/"
        f"blender-{BLENDER_VER}-linux-x64.tar.xz | tar -xJ -C /opt && mv /opt/blender-{BLENDER_VER}-linux-x64 /opt/blender",
        f"git clone -q https://github.com/tpark94/spnv2.git /opt/spnv2 && git -C /opt/spnv2 checkout -q {SPNV2_COMMIT}",
    )
    .add_local_dir(str(REPO / "third_party" / "patches"), "/opt/patches", copy=True)
    .run_commands("cd /opt/spnv2 && git apply /opt/patches/spnv2-savemat-none.patch "
                  "&& git apply /opt/patches/spnv2-albumentations14.patch "
                  "&& git apply /opt/patches/spnv2-heatmap-peaks.patch")
    .env({"PY": "/usr/local/bin/python", "BLENDER": "/opt/blender/blender", "PYTHONUNBUFFERED": "1"})
    # 코드는 마지막 층: 코드를 고쳐도 위 층(torch, Blender)은 다시 만들지 않는다
    .add_local_dir(str(REPO), SRC, ignore=[
        ".git", ".git/**", ".venv", ".venv/**", "data/**", "outputs/**", "third_party/spnv2", "third_party/spnv2/**",
        "**/__pycache__", "**/__pycache__/**", "**/*.pyc", "**/.DS_Store", "demo", "demo/**", "site", "site/**",
        "docs", "docs/**", "experiments", "experiments/**", "README.md", "README.ko.md",
    ])
)

app = modal.App("orbitlight", image=image)


def _workdir() -> Path:
    """저장소 복사본을 만들고 data/ outputs/ third_party/spnv2를 볼륨·이미지 경로에 연결한다."""
    w = Path(WORK)
    if not w.exists():
        shutil.copytree(SRC, w, symlinks=True)
    for name in ("data", "outputs"):
        target = Path(VOL) / name
        target.mkdir(parents=True, exist_ok=True)
        link = w / name
        if link.is_symlink():
            continue
        if link.exists():
            shutil.rmtree(link)
        link.symlink_to(target)
    spn = w / "third_party" / "spnv2"
    if not spn.exists():
        spn.parent.mkdir(parents=True, exist_ok=True)
        spn.symlink_to("/opt/spnv2")
    return w


class _Autocommit:
    """긴 작업 중에도 볼륨에 주기적으로 커밋해, 밖에서 진행 로그(outputs/.../train.log 등)를 볼 수 있게 한다."""

    def __init__(self, every: float = 300.0):
        import threading
        self.every, self.stop = every, threading.Event()
        self.t = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self.stop.wait(self.every):
            try:
                vol.commit()
            except Exception as e:  # 커밋 실패는 작업을 멈추지 않는다
                print(f"[autocommit] {e}", flush=True)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()


def _run(cmd: str, cwd: Path | str) -> int:
    print(f"$ {cmd}", flush=True)
    t0 = time.time()
    rc = subprocess.run(["bash", "-c", f"set -o pipefail; {cmd}"], cwd=str(cwd)).returncode
    print(f"[exit {rc}] {time.time() - t0:.0f}s", flush=True)
    return rc


# ---------------------------------------------------------------- 점검

@app.function(gpu="L4", cpu=2, memory=8192, timeout=900)
def gpu_info() -> None:
    w = _workdir()
    _run("nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader", w)
    _run("$PY -c 'import torch, torchvision; print(\"torch\", torch.__version__, \"cuda\", torch.version.cuda, "
         "torch.cuda.is_available(), torch.cuda.get_device_name(0)); x = torch.randn(4096, 4096, device=\"cuda\"); "
         "torch.cuda.synchronize(); import time; t = time.time(); [x @ x for _ in range(10)]; torch.cuda.synchronize(); "
         "print(\"matmul x10\", round((time.time() - t) * 1000, 1), \"ms\")'", w)
    expr = ("import bpy\n"
            "p = bpy.context.preferences.addons['cycles'].preferences\n"
            "for t in ('OPTIX', 'CUDA'):\n"
            "    p.compute_device_type = t\n"
            "    p.get_devices()\n"
            "    print('[blender]', t, [d.name for d in p.devices if d.type == t])\n")
    Path("/tmp/devices.py").write_text(expr)
    _run("$BLENDER -b --factory-startup --python /tmp/devices.py 2>&1 | grep -E '^\\[blender\\]|Blender [0-9]'", w)
    _run("$PY scripts/spnv2_smoke.py 2>&1 | tail -n 5", w)


# ---------------------------------------------------------------- 데이터

@app.function(volumes={VOL: vol}, cpu=8, memory=16384, timeout=4 * 3600)
def fetch_data() -> None:
    """SPEED+(16.9 GB)를 받아 볼륨에 풀고, Tango 모형을 받고, 평가용 세 도메인을 SPNv2 형식으로 전처리한다.

    네트워크 파일 시스템인 볼륨에 17 GB zip을 쓰지 않도록 컨테이너 로컬 디스크에서 받아 풀고 옮긴다.
    다시 실행하면 이미 있는 단계는 건너뛴다.
    """
    w = _workdir()
    vol.reload()
    speed = Path(VOL) / "data" / "speedplus" / "speedplusv2"
    if not (speed / "camera.json").exists():
        tmp = Path("/tmp/dl")
        (tmp / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy(w / "scripts" / "download_speedplus.sh", tmp / "scripts")
        if _run("PARALLEL=32 bash scripts/download_speedplus.sh", tmp) != 0:
            raise RuntimeError("SPEED+ 다운로드 실패")
        speed.parent.mkdir(parents=True, exist_ok=True)
        if _run(f"cp -r /tmp/dl/data/speedplus/speedplusv2 {speed.parent}/ && du -sh {speed}", "/") != 0:
            raise RuntimeError("볼륨으로 복사 실패")
        vol.commit()
    if not (Path(VOL) / "data" / "models" / "spin_tango" / "tango_fix.obj").exists():
        _run("bash scripts/download_tango_model.sh", w)
        vol.commit()

    # 평가용 전처리 (eval_spnv2_baseline.sh의 전처리 부분과 같음). 세 도메인을 동시에.
    # SPNv2는 DATASET.KEYPOINTS 등을 DATASET.ROOT 기준으로 이어 붙이므로 경로는 모두 절대 경로로 준다.
    cfg = f"{w}/third_party/spnv2/experiments/offline_train_full_config_phi3_BN.yaml"
    common = (f"DATASET.ROOT {w}/data/speedplus DATASET.DATANAME speedplusv2 "
              f"DATASET.KEYPOINTS {w}/third_party/spnv2/core/utils/models/tangoPoints.mat DIST.MULTIPROCESSING_DISTRIBUTED False")
    jobs = []
    for dom, js in (("synthetic", "synthetic/validation.json"), ("lightbox", "lightbox/test.json"), ("sunlamp", "sunlamp/test.json")):
        csv = speed / dom / "labels" / (Path(js).stem + ".csv")
        if csv.exists() and (speed / dom / "images_768x512_RGB").exists():
            continue
        jobs.append(f"$PY -W ignore third_party/spnv2/tools/preprocess.py --cfg {cfg} --jsonfile {js} --no_masks {common} "
                    f"> /tmp/pre_{dom}.log 2>&1")
    if jobs:
        # 동시에 돌리고, 하나라도 실패하면 실패로 끝낸다
        script = "pids=(); " + " ".join(f"( {j} ) & pids+=($!);" for j in jobs) + \
                 ' fail=0; for p in "${pids[@]}"; do wait "$p" || fail=1; done; tail -n 3 /tmp/pre_*.log; exit $fail'
        rc = _run(script, w)
        vol.commit()
        if rc != 0:
            raise RuntimeError("전처리 실패")
    _run("ls data/speedplus/speedplusv2/*/labels/ && du -sh data/speedplus", w)


# ---------------------------------------------------------------- 임의 명령

@app.function(volumes={VOL: vol}, cpu=8, memory=16384, timeout=6 * 3600)
def sh_cpu(cmd: str) -> int:
    w = _workdir()
    vol.reload()
    with _Autocommit():
        rc = _run(cmd, w)
    vol.commit()
    return rc


@app.function(volumes={VOL: vol}, gpu=["L4", "A10", "L40S"], cpu=4, memory=16384, timeout=6 * 3600)
def sh_gpu(cmd: str) -> int:
    w = _workdir()
    vol.reload()
    _run("nvidia-smi --query-gpu=name --format=csv,noheader", w)
    with _Autocommit():
        rc = _run(cmd, w)
    vol.commit()
    return rc


@app.local_entrypoint()
def run_sh(cmd: str, gpu: str = "") -> None:
    """GPU 없이: --gpu ""(기본). GPU: --gpu L4 | A10 | L40S | "L4,A10,L40S"(앞에서부터 남는 것) ..."""
    gpus = [g.strip() for g in gpu.split(",") if g.strip()]
    if not gpus:
        rc = sh_cpu.remote(cmd)
    else:
        # with_options는 GPU 하나(문자열)만 받는다. 여러 개면 함수에 정해 둔 후보 목록(L4 → A10 → L40S)을 쓴다
        rc = sh_gpu.remote(cmd) if len(gpus) > 1 else sh_gpu.with_options(gpu=gpus[0]).remote(cmd)
    if rc != 0:
        raise SystemExit(rc)


@app.function(cpu=0.25, memory=512, timeout=12 * 3600)
def chain(steps: list[list[str]]) -> list[int]:
    """[["cpu"|"gpu", 명령], ...]을 Modal 안에서 차례로 돌린다. 실패하면 멈춘다.
    `modal run --detach ...::run_chain`으로 띄우면 이 컴퓨터의 연결이 끊겨도 끝까지 간다."""
    out = []
    for kind, cmd in steps:
        rc = (sh_gpu if kind == "gpu" else sh_cpu).remote(cmd)
        out.append(rc)
        print(f"[chain] {kind} rc={rc}: {cmd[:100]}", flush=True)
        if rc != 0:
            break
    return out


@app.local_entrypoint()
def run_chain(steps_json: str) -> None:
    rcs = chain.remote(json.loads(steps_json))
    print("chain:", rcs)
    if any(rcs):
        raise SystemExit(1)


# ---------------------------------------------------------------- 렌더 (여러 GPU로 나눠서)

@app.function(volumes={VOL: vol}, gpu=["L4", "A10", "L40S"], cpu=4, memory=16384, timeout=3 * 3600, max_containers=24)
def render_chunk(run: str, start: int, count: int, device: str = "OPTIX", denoiser: str = "OIDN") -> dict:
    w = _workdir()
    vol.reload()
    cmd = ("$BLENDER -b --factory-startup -P src/orbitlight/render/blender_render.py -- "
           f"--jobs outputs/renders/{run}/jobs.json --model data/models/spin_tango/tango_fix.obj "
           f"--device {device} --denoiser {denoiser} --skip-existing --start {start} --count {count} 2>&1 "
           "| grep --line-buffered -E '^\\[render\\]|Error|ERROR|Traceback'")
    t0 = time.time()
    rc = _run(cmd, w)
    vol.commit()
    return dict(start=start, count=count, rc=rc, sec=round(time.time() - t0, 1))


@app.function(volumes={VOL: vol}, cpu=1, memory=2048, timeout=6 * 3600)
def render_all(run: str, chunks: int = 16, device: str = "OPTIX", gpu: str = "L4,A10,L40S") -> list[dict]:
    vol.reload()
    n = len(json.loads((Path(VOL) / "outputs" / "renders" / run / "jobs.json").read_text())["jobs"])
    step = -(-n // chunks)
    args = [(run, s, min(step, n - s), device) for s in range(0, n, step)]
    print(f"{run}: {n} images in {len(args)} chunks of <= {step} on {gpu}", flush=True)
    gpus = [g.strip() for g in gpu.split(",") if g.strip()]
    fn = render_chunk if len(gpus) > 1 else render_chunk.with_options(gpu=gpus[0])
    return list(fn.starmap(args))


@app.local_entrypoint()
def run_render(run: str, chunks: int = 16, device: str = "OPTIX", gpu: str = "L4,A10,L40S") -> None:
    res = render_all.remote(run, chunks, device, gpu)
    bad = [r for r in res if r["rc"] != 0]
    print(f"chunks {len(res)}, failed {len(bad)}, slowest {max(r['sec'] for r in res):.0f}s, "
          f"GPU-seconds {sum(r['sec'] for r in res):.0f}")
    if bad:
        raise SystemExit(f"failed chunks: {bad}")
