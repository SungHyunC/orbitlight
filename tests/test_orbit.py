"""궤도 장면 계산 검사.  python -m pytest tests/ -q"""

import numpy as np
import pytest

from orbitlight.orbit.scenario import (HOLDS, R_EARTH, Orbit, cam_from_lvlh, dcm2quat, p_fail_from_map,
                                       phase_azimuth_deg, relative_pose, sun_in_camera, target_attitude_lvlh)
from orbitlight.render.geometry import phase_angle_deg, quat2dcm, sun_direction_cam

Q_EX = np.array([0.556984, -0.711815, 0.168095, -0.393487])   # SPEED+ 합성 검증셋 img000014 자세


def test_dcm2quat_roundtrip():
    rng = np.random.default_rng(0)
    for _ in range(200):
        q = rng.normal(size=4)
        q /= np.linalg.norm(q)
        q2 = dcm2quat(quat2dcm(q))
        assert np.allclose(quat2dcm(q2), quat2dcm(q), atol=1e-9)
        assert min(np.linalg.norm(q2 - q), np.linalg.norm(q2 + q)) < 1e-9


@pytest.mark.parametrize("hold", list(HOLDS))
def test_camera_frame_is_rotation(hold):
    C = cam_from_lvlh(hold)
    assert np.allclose(C @ C.T, np.eye(3), atol=1e-12)
    assert np.isclose(np.linalg.det(C), 1.0)


def test_reference_hold_reproduces_pose():
    body = target_attitude_lvlh(Q_EX, "vbar-")
    q, r = relative_pose(body, "vbar-", 6.5)
    assert np.allclose(quat2dcm(q), quat2dcm(Q_EX), atol=1e-9)
    assert np.allclose(r, [0, 0, 6.5])


def test_eclipse_fraction():
    o = Orbit(altitude_km=500, beta_deg=0)
    u = np.linspace(0, 360, 36000, endpoint=False)
    frac = o.state(u)["eclipse"].mean()
    expect = 2 * np.degrees(np.arcsin(R_EARTH / o.a)) / 360       # 원통 그림자, β = 0
    assert abs(frac - expect) < 1e-3
    assert 94 < o.period_s / 60 < 95.5                              # 500 km 원궤도 약 94.6분
    assert not Orbit(altitude_km=500, beta_deg=70).state(u)["eclipse"].any()   # β가 크면 식이 없다


def test_phase_matches_geometry_and_vbar_profile():
    o = Orbit(altitude_km=500, beta_deg=0)
    u = np.array([0.0, 90.0, 270.0])
    s_cam = sun_in_camera(o.state(u)["s_lvlh"], "vbar-")
    r = np.array([0.0, 0.0, 7.0])
    phase, az = phase_azimuth_deg(r, s_cam)
    for k in range(3):
        assert abs(phase[k] - phase_angle_deg(r, s_cam[k])) < 1e-9
    # 뒤에서 앞을 보는 카메라: 진행 방향 쪽에 태양이 있으면(u = 90°) 정면 조명, 반대(u = 270°)면 역광
    assert phase[1] < 1e-6 and abs(phase[2] - 180) < 1e-6 and abs(phase[0] - 90) < 1e-6


@pytest.mark.parametrize("ph,az", [(30, 0), (60, 90), (120, 200), (150, 300)])
def test_azimuth_matches_sunsweep_definition(ph, az):
    r = np.array([0.0, 0.0, 7.0])
    s = sun_direction_cam(r, ph, az)
    p2, a2 = phase_azimuth_deg(r, s)
    assert abs(p2[0] - ph) < 1e-6 and abs((a2[0] - az + 180) % 360 - 180) < 1e-6


def test_failure_map_interp():
    assert np.isclose(p_fail_from_map([0])[0], 0.010)
    assert np.isclose(p_fail_from_map([70])[0], (0.115 + 0.152) / 2)
    assert np.isclose(p_fail_from_map([175])[0], 0.706)
