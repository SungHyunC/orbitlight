"""렌더링 원본(핀홀, RGB 16-bit PNG) → SPEED+ 형식 이미지(렌즈 왜곡 적용, 흑백 8-bit JPG, 센서 노이즈)와 마스크.

SPEED+ 합성 이미지 실측 (검증셋 200장, 검은 배경 모서리 100×100, LOG render-001): 평균 약 3.6, 표준편차 약 3.0.
"""

from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np

from orbitlight.render.geometry import body_to_cam


@lru_cache(maxsize=4)
def distortion_maps(K_flat: tuple, dist: tuple, Nu: int, Nv: int) -> tuple[np.ndarray, np.ndarray]:
    """왜곡된 출력 픽셀마다, 핀홀 렌더에서 가져올 위치(map_x, map_y)."""
    K = np.array(K_flat, dtype=np.float64).reshape(3, 3)
    u, v = np.meshgrid(np.arange(Nu, dtype=np.float64), np.arange(Nv, dtype=np.float64))
    pts = np.stack([u.ravel(), v.ravel()], axis=1).reshape(-1, 1, 2)
    und = cv2.undistortPoints(pts, K, np.array(dist), R=None, P=K,
                              criteria=(cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 40, 1e-6))
    und = und.reshape(Nv, Nu, 2).astype(np.float32)
    return und[..., 0], und[..., 1]


def to_speedplus_image(raw_rgb16: np.ndarray, camera: dict, rng: np.random.Generator,
                       noise_std: float = 3.0, noise_offset: float = 2.0) -> np.ndarray:
    """16-bit RGB(OpenCV BGR 순서) → 왜곡 적용 흑백 uint8."""
    gray = cv2.cvtColor(raw_rgb16.astype(np.float32) / 65535.0, cv2.COLOR_BGR2GRAY) * 255.0
    K = tuple(np.ravel(camera["cameraMatrix"]))
    mx, my = distortion_maps(K, tuple(camera["distCoeffs"]), camera["Nu"], camera["Nv"])
    img = cv2.remap(gray, mx, my, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    img = img + noise_offset + rng.normal(0.0, noise_std, img.shape)
    return np.clip(np.rint(img), 0, 255).astype(np.uint8)


def load_obj(path) -> tuple[np.ndarray, np.ndarray]:
    """OBJ의 정점(m 단위, cm→m)과 삼각형 면 인덱스."""
    V, F = [], []
    with open(path, errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                V.append([float(t) for t in line.split()[1:4]])
            elif line.startswith("f "):
                idx = [int(t.split("/")[0]) for t in line.split()[1:]]
                idx = [i - 1 if i > 0 else len(V) + i for i in idx]
                F.extend([idx[0], idx[j], idx[j + 1]] for j in range(1, len(idx) - 1))
    return np.asarray(V) * 0.01, np.asarray(F, dtype=np.int64)


def project(points_body: np.ndarray, q, r, camera: dict) -> np.ndarray:
    """몸체 좌표 점 → 왜곡 포함 픽셀 좌표 (N×2). SPNv2 project_keypoints와 같은 식."""
    T = body_to_cam(q, r)
    X = points_body @ T[:3, :3].T + T[:3, 3]
    x0, y0 = X[:, 0] / X[:, 2], X[:, 1] / X[:, 2]
    d = np.asarray(camera["distCoeffs"], float)
    r2 = x0 * x0 + y0 * y0
    c = 1 + d[0] * r2 + d[1] * r2**2 + d[4] * r2**3
    x = x0 * c + d[2] * 2 * x0 * y0 + d[3] * (r2 + 2 * x0 * x0)
    y = y0 * c + d[2] * (r2 + 2 * y0 * y0) + d[3] * 2 * x0 * y0
    K = np.asarray(camera["cameraMatrix"], float)
    return np.stack([K[0, 0] * x + K[0, 2], K[1, 1] * y + K[1, 2]], axis=1)


def silhouette_mask(V: np.ndarray, F: np.ndarray, q, r, camera: dict) -> np.ndarray:
    """모델 실루엣 마스크 (uint8 0/255). 면을 투영해 채운다 (가림은 실루엣 합집합이라 무관)."""
    p = project(V, q, r, camera)
    tris = np.rint(p[F]).astype(np.int32)
    m = np.zeros((camera["Nv"], camera["Nu"]), np.uint8)
    cv2.fillPoly(m, list(tris.reshape(-1, 3, 1, 2)), 255)
    return m
