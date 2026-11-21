"""SPEED+ 자세 표기 ↔ Blender 장면 좌표 변환, 태양 방향 격자 계산.

좌표계
- 위성 몸체(body, Tango) 좌표: SPNv2 `tangoPoints.mat`과 같은 축, 단위 m.
- 카메라 좌표(OpenCV): x 오른쪽, y 아래, z 앞(시선 방향). SPEED+ 라벨의 `r_Vo2To_vbs_true`가 이 좌표.
- Blender 카메라: 원점에 회전 없이 둔다 → x 오른쪽, y 위, -z 시선. OpenCV → Blender 변환은 C = diag(1, -1, -1).

자세 변환은 SPNv2 `core/utils/postprocess.py::project_keypoints`와 같다:
    X_cam = quat2dcm(q)^T @ X_body + r
"""

from __future__ import annotations

import numpy as np

C_CV2BL = np.diag([1.0, -1.0, -1.0])


def quat2dcm(q) -> np.ndarray:
    """SPNv2와 같은 규약의 방향 코사인 행렬 (스칼라 먼저, q = [q0, q1, q2, q3])."""
    q = np.asarray(q, dtype=float)
    q0, q1, q2, q3 = q / np.linalg.norm(q)
    return np.array([
        [2 * q0**2 - 1 + 2 * q1**2, 2 * q1 * q2 + 2 * q0 * q3, 2 * q1 * q3 - 2 * q0 * q2],
        [2 * q1 * q2 - 2 * q0 * q3, 2 * q0**2 - 1 + 2 * q2**2, 2 * q2 * q3 + 2 * q0 * q1],
        [2 * q1 * q3 + 2 * q0 * q2, 2 * q2 * q3 - 2 * q0 * q1, 2 * q0**2 - 1 + 2 * q3**2],
    ])


def body_to_cam(q, r) -> np.ndarray:
    """몸체 → OpenCV 카메라 좌표 4×4 변환."""
    T = np.eye(4)
    T[:3, :3] = quat2dcm(q).T
    T[:3, 3] = np.asarray(r, dtype=float)
    return T


def blender_object_matrix(q, r) -> np.ndarray:
    """카메라를 원점(회전 없음)에 둔 Blender 장면에서 위성 오브젝트의 matrix_world."""
    T = body_to_cam(q, r)
    C = np.eye(4)
    C[:3, :3] = C_CV2BL
    return C @ T


def sun_direction_cam(r, phase_deg: float, azimuth_deg: float) -> np.ndarray:
    """위성 → 태양 방향 단위 벡터 (OpenCV 카메라 좌표).

    phase_deg (위상각): 위성에서 본 카메라 방향과 태양 방향 사이 각.
        0° = 태양이 카메라 바로 뒤(정면 조명), 90° = 옆 조명, 180°에 가까울수록 역광.
    azimuth_deg (방위각): 시선 축을 중심으로 태양이 어느 쪽에 있는지, 이미지 기준.
        0° = 이미지 오른쪽, 90° = 이미지 위쪽, 180° = 왼쪽, 270° = 아래쪽.
    """
    r = np.asarray(r, dtype=float)
    to_cam = -r / np.linalg.norm(r)
    # 이미지 오른쪽(+x)과 위쪽(-y)을 시선에 수직하게 투영
    right = np.array([1.0, 0.0, 0.0])
    right = right - right.dot(to_cam) * to_cam
    right /= np.linalg.norm(right)
    up = np.cross(to_cam, right)  # to_cam × right
    if up.dot(np.array([0.0, -1.0, 0.0])) < 0:
        up = -up
    a, p = np.radians(azimuth_deg), np.radians(phase_deg)
    s = np.cos(p) * to_cam + np.sin(p) * (np.cos(a) * right + np.sin(a) * up)
    return s / np.linalg.norm(s)


def phase_angle_deg(r, sun_cam) -> float:
    """검산용: 위성→카메라 방향과 위성→태양 방향 사이 각 [deg]."""
    to_cam = -np.asarray(r, float) / np.linalg.norm(r)
    s = np.asarray(sun_cam, float) / np.linalg.norm(sun_cam)
    return float(np.degrees(np.arccos(np.clip(to_cam.dot(s), -1.0, 1.0))))
