"""좌표 변환·태양 방향 계산 검사.  python -m pytest tests/ -q"""

import numpy as np
import pytest

from orbitlight.render.geometry import blender_object_matrix, body_to_cam, phase_angle_deg, sun_direction_cam

R_EX = np.array([-0.423949, -0.14451, 6.509727])   # SPEED+ 합성 검증셋 img000014 위치
Q_EX = np.array([0.556984, -0.711815, 0.168095, -0.393487])


@pytest.mark.parametrize("phase", [0, 20, 90, 160])
@pytest.mark.parametrize("az", [0, 90, 180, 270])
def test_phase_angle_roundtrip(phase, az):
    s = sun_direction_cam(R_EX, phase, az)
    assert np.isclose(np.linalg.norm(s), 1.0)
    assert np.isclose(phase_angle_deg(R_EX, s), phase, atol=1e-6)


def test_azimuth_image_directions():
    # 정면 위치(시선이 +z)에서 방위각 0° = 이미지 오른쪽(+x), 90° = 이미지 위쪽(-y, OpenCV는 y가 아래)
    r = np.array([0.0, 0.0, 5.0])
    assert np.allclose(sun_direction_cam(r, 90, 0), [1, 0, 0], atol=1e-9)
    assert np.allclose(sun_direction_cam(r, 90, 90), [0, -1, 0], atol=1e-9)
    assert np.allclose(sun_direction_cam(r, 0, 0), [0, 0, -1], atol=1e-9)   # 정면 조명 = 카메라 쪽


def test_rotation_proper():
    T = body_to_cam(Q_EX, R_EX)
    R = T[:3, :3]
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)
    assert np.isclose(np.linalg.det(R), 1.0)
    M = blender_object_matrix(Q_EX, R_EX)
    assert np.isclose(np.linalg.det(M[:3, :3]), 1.0)
    # Blender 카메라는 -z를 본다 → 카메라 앞의 위성은 z < 0
    assert M[2, 3] < 0


def test_matches_spnv2_projection():
    spn = pytest.importorskip("core.utils.postprocess", reason="third_party/spnv2가 sys.path에 없음")
    K = np.array([[2988.58, 0, 960], [0, 2988.34, 600], [0, 0, 1]])
    pts = np.array([[0.37, 0.385, 0.3215], [-0.5427, 0.4877, 0.2535]])
    T = body_to_cam(Q_EX, R_EX)
    X = pts @ T[:3, :3].T + T[:3, 3]
    ours = (K @ (X / X[:, 2:3]).T)[:2]
    ref = spn.project_keypoints(Q_EX, R_EX, K, np.zeros(5), pts)
    assert np.allclose(ours, ref, atol=1e-3)
