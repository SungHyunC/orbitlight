"""미세조정(fine-tuning)용 학습 폴더를 만든다: SPEED+ 합성 학습 이미지 + 우리 렌더를 한 도메인(mix)으로 섞는다.

    python scripts/build_finetune_set.py --name speedplus_ft_v01 --renders speedplus_trainrender_v01 \
        --speed-n 8000 --val-n 500

결과 outputs/renders/<name>/ (git 제외, SPNv2가 바로 읽는 구조):
    camera.json
    mix/images/      원본 이미지로 가는 심볼릭 링크 (sp_*: SPEED+, r_*: 우리 렌더)
    mix/masks/       전체 해상도 마스크. SPNv2가 이미지와 같은 파일 이름(.jpg)으로 찾으므로 PNG 내용을 .jpg 이름으로 저장
                     (cv2.imread는 확장자가 아니라 내용으로 형식을 판별한다)
    mix/train.json, mix/val.json
    mix/labels/{train,val}.csv, mix/images_768x512_RGB/, mix/masks_192x128/   (SPNv2 preprocess.py가 만듦)

SPEED+ 이미지에는 마스크가 없어서, SPIN Tango 모형을 정답 자세로 투영한 실루엣으로 만든다 (얇은 와이어 안테나는 빠짐).
SPEED+는 synthetic/train.json에서만 고른다 (검증셋 = 평가용이므로 쓰지 않음). 렌더는 자세 단위로 학습/검증을 나눈다.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from orbitlight.render.postprocess import load_obj, silhouette_mask  # noqa: E402

SPEED = ROOT / "data" / "speedplus" / "speedplusv2"
MODEL = ROOT / "data" / "models" / "spin_tango" / "tango_fix.obj"
SPN = ROOT / "third_party" / "spnv2"
CFG = SPN / "experiments" / "offline_train_full_config_phi3_BN.yaml"
PY = os.environ.get("PY", str(Path.home() / "anaconda3" / "envs" / "orbitlight" / "bin" / "python"))
DOMAIN = "mix"


def write_png_as(path: Path, mask: np.ndarray) -> None:
    ok, buf = cv2.imencode(".png", mask)
    assert ok
    path.write_bytes(buf.tobytes())


def link(src: Path, dst: Path) -> None:
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    dst.symlink_to(src.resolve())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--renders", nargs="*", default=[], help="outputs/renders 아래 렌더 run 이름들")
    p.add_argument("--speed-n", type=int, default=8000, help="학습에 넣을 SPEED+ 합성 이미지 수")
    p.add_argument("--val-n", type=int, default=500, help="검증용 (SPEED+ 몇 장, 렌더 몇 장 — 각각)")
    p.add_argument("--max-renders", type=int, default=-1)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    assert "speedplus" in a.name, "SPNv2는 DATANAME에 'speedplus'가 있어야 읽는다"

    out = ROOT / "outputs" / "renders" / a.name
    dom = out / DOMAIN
    (dom / "images").mkdir(parents=True, exist_ok=True)
    (dom / "masks").mkdir(parents=True, exist_ok=True)
    camera = json.loads((SPEED / "camera.json").read_text())
    (out / "camera.json").write_text(json.dumps(camera, indent=2))
    rng = np.random.default_rng(a.seed)
    train, val = [], []

    # 1) SPEED+ 합성 학습 이미지 + 투영 마스크
    labels = json.loads((SPEED / "synthetic" / "train.json").read_text())
    pick = rng.choice(len(labels), a.speed_n + a.val_n, replace=False)
    V, F = load_obj(MODEL)
    for n, i in enumerate(tqdm(pick, desc="SPEED+ masks")):
        lab = labels[i]
        fn = f"sp_{lab['filename']}"
        link(SPEED / "synthetic" / "images" / lab["filename"], dom / "images" / fn)
        # 항상 다시 쓴다 (예전 구멍 난 마스크가 남지 않도록)
        write_png_as(dom / "masks" / fn, silhouette_mask(V, F, lab["q_vbs2tango_true"], lab["r_Vo2To_vbs_true"], camera))
        item = dict(filename=fn, q_vbs2tango_true=lab["q_vbs2tango_true"], r_Vo2To_vbs_true=lab["r_Vo2To_vbs_true"])
        (val if n >= a.speed_n else train).append(item)

    # 2) 우리 렌더 (자세 단위로 검증 분리)
    for run in a.renders:
        rdom = ROOT / "outputs" / "renders" / run / "sunsweep"
        rlab = json.loads((rdom / "test.json").read_text())
        meta = {r.split(",")[0]: r.split(",")[1] for r in (rdom / "meta.csv").read_text().splitlines()[1:]}
        if a.max_renders > 0:
            rlab = rlab[: a.max_renders]
        poses = sorted({meta[l["filename"]] for l in rlab})
        n_val_pose = max(1, int(round(len(poses) * a.val_n / max(len(rlab), 1))))
        val_poses = set(rng.choice(poses, n_val_pose, replace=False).tolist())
        for lab in tqdm(rlab, desc=f"renders {run}"):
            fn = f"r_{run.replace('speedplus_', '')}_{lab['filename']}"
            link(rdom / "images" / lab["filename"], dom / "images" / fn)
            mpath = dom / "masks" / fn
            m = cv2.imread(str(rdom / "masks" / lab["filename"].replace(".jpg", ".png")), cv2.IMREAD_GRAYSCALE)
            write_png_as(mpath, m)
            item = dict(filename=fn, q_vbs2tango_true=lab["q_vbs2tango_true"], r_Vo2To_vbs_true=lab["r_Vo2To_vbs_true"])
            (val if meta[lab["filename"]] in val_poses else train).append(item)

    rng.shuffle(train)
    (dom / "train.json").write_text(json.dumps(train, indent=1))
    (dom / "val.json").write_text(json.dumps(val, indent=1))
    n_r = sum(t["filename"].startswith("r_") for t in train)
    print(f"train {len(train)} (SPEED+ {len(train) - n_r}, renders {n_r}) / val {len(val)}")

    # 3) SPNv2 전처리 (768×512 축소, 192×128 마스크, CSV 라벨). 마스크로 bbox 계산
    common = ["DATASET.ROOT", str(ROOT / "outputs" / "renders"), "DATASET.DATANAME", a.name,
              "DATASET.KEYPOINTS", str(SPN / "core" / "utils" / "models" / "tangoPoints.mat"),
              "DIST.MULTIPROCESSING_DISTRIBUTED", "False"]
    for split in ("train", "val"):
        subprocess.run([PY, "-W", "ignore", str(SPN / "tools" / "preprocess.py"), "--cfg", str(CFG),
                        "--jsonfile", f"{DOMAIN}/{split}.json", *common], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
