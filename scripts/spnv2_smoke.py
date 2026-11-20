"""SPNv2 동작 확인 (데이터 없이).

공식 설정 파일로 모델을 만들고, 무작위 입력 이미지로 GPU 순전파(forward)를 돌려
현재 orbitlight 환경(Python 3.11, PyTorch 2.x)에서 SPNv2 코드가 실행되는지 본다.

    python scripts/spnv2_smoke.py
    python scripts/spnv2_smoke.py --cfg third_party/spnv2/experiments/offline_train_full_config_phi6_GN.yaml
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
SPNV2 = ROOT / "third_party" / "spnv2"
sys.path.insert(0, str(SPNV2 / "core"))

from config import cfg  # noqa: E402  (SPNv2 yacs 설정)
from config.default import EFFICIENTDET_EXTRAS  # noqa: E402
from nets import build_spnv2  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cfg", type=Path, default=SPNV2 / "experiments" / "offline_train_full_config_phi3_BN.yaml")
    p.add_argument("--batch", type=int, default=1)
    p.add_argument("--dataset-root", type=Path, default=ROOT / "data",
                   help="DATASET.ROOT. <root>/speedplus/camera.json 이 있어야 한다")
    args = p.parse_args()

    cfg.defrost()
    cfg.merge_from_file(str(args.cfg))
    cfg.MODEL.BACKBONE.EXTRA = EFFICIENTDET_EXTRAS[cfg.MODEL.BACKBONE.NAME]
    cfg.DATASET.ROOT = str(args.dataset_root)
    # update_config()와 같은 방식으로 보조 파일 경로를 채운다
    cfg.DATASET.CAMERA = str(args.dataset_root / cfg.DATASET.DATANAME / cfg.DATASET.CAMERA)
    cfg.DATASET.KEYPOINTS = str(args.dataset_root / cfg.DATASET.KEYPOINTS)
    cfg.DATASET.CADMODEL = str(args.dataset_root / cfg.DATASET.CADMODEL)
    cfg.MODEL.BACKBONE.PRETRAINED = ""  # ImageNet 사전학습 가중치 없이 구조만 확인
    cfg.MODEL.PRETRAIN_FILE = ""
    cfg.freeze()

    device = torch.device("cuda:0")
    model = build_spnv2(cfg).to(device).eval()
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[spnv2] cfg={args.cfg.name} backbone={cfg.MODEL.BACKBONE.NAME} params={n_params / 1e6:.2f}M")

    w, h = cfg.DATASET.INPUT_SIZE
    x = torch.randn(args.batch, 3, h, w)
    torch.cuda.reset_peak_memory_stats()
    with torch.no_grad(), torch.autocast("cuda", enabled=cfg.FP16):
        model(x, is_train=False, gpu=device)  # 워밍업
        torch.cuda.synchronize()
        t = time.perf_counter()
        out = model(x, is_train=False, gpu=device)
        torch.cuda.synchronize()
        dt = time.perf_counter() - t

    names = [cfg.TEST.HEAD[i] if i < len(cfg.TEST.HEAD) else "?" for i in range(len(out))]
    for name, o in zip(names, out):
        shapes = [tuple(t.shape) for t in (o if isinstance(o, (list, tuple)) else [o]) if torch.is_tensor(t)]
        print(f"[spnv2] head={name} outputs={shapes}")
    print(f"[spnv2] input={w}x{h} batch={args.batch} forward={dt * 1000:.1f}ms "
          f"peak_vram={torch.cuda.max_memory_allocated() / 2**30:.2f}GiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
