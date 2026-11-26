"""궤도 위 근접 운용 장면: 원궤도 한 바퀴 동안 태양 방향·지구 그림자(식)·카메라에서 본 조명을 계산한다.

목표 위성은 저궤도 원궤도를 돌고, 자세는 궤도 기준 좌표(LVLH)에 고정돼 있다(지구를 향해 자세를 유지하는 위성).
추적 위성은 목표 위성 근처의 한 점(정지 위치, hold point)에 머물며 카메라로 목표를 바라본다.

좌표
- 궤도면 좌표: P(궤도면 안, 태양 쪽), Q(궤도면 안, P에서 진행 방향으로 90°), H(궤도면 법선).
  태양은 P-H 평면에 있고 궤도면과 β(베타각)만큼 기운다: s = cos β · P + sin β · H. 지구-태양 거리가 커서 위성에서 본
  태양 방향도 같다고 둔다.
- 위성 위치 r(u) = a (cos u · P + sin u · Q). u(위도 인수)는 태양 아래 지점 기준 각도라, u = 180° 근처가 지구 그림자다.
- LVLH: r̂(지구 반대쪽, 천정), t̂ = ĥ × r̂(진행 방향), ĥ(궤도면 법선).
- 카메라: OpenCV 규약(x 오른쪽, y 아래, z 시선). SPEED+ 자세 라벨과 같다 (geometry.py 참고).

정지 위치 (목표에서 본 추적 위성 방향, 이름은 HOLDS)
- vbar-: 진행 방향 뒤쪽(-t̂)에서 앞을 본다. vbar+: 앞(+t̂)에서 뒤를 본다. 화면 위쪽 = 천정.
- rbar-: 목표 아래(지구 쪽, -r̂)에서 위를 본다. 화면 위쪽 = 진행 방향. (위쪽 +r̂에서 내려다보면 배경이 지구라 뺐다)
- hbar+, hbar-: 궤도면 양옆(±ĥ)에서 본다. 화면 위쪽 = 천정.
모든 경우 지구 가장자리는 시야(세로 ±11°) 밖이라(고도 500 km에서 수평선은 22° 아래) 배경은 검은 우주다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from orbitlight.render.geometry import quat2dcm

MU_EARTH = 398600.4418      # km^3/s^2
R_EARTH = 6378.137          # km

HOLDS = {
    # 이름: (목표 → 추적 위성 방향(LVLH), 화면 위쪽 기준(LVLH))
    "vbar-": ("-t", "r"),    # 뒤에서 앞을 봄 (V-bar 뒤쪽 정지)
    "vbar+": ("t", "r"),     # 앞에서 뒤를 봄
    "rbar-": ("-r", "t"),    # 아래(지구 쪽)에서 위를 봄. 한낮에는 태양이 목표 바로 뒤
    "hbar+": ("h", "r"),     # 궤도면 옆 +ĥ 쪽 (β > 0이면 태양 쪽)
    "hbar-": ("-h", "r"),    # 궤도면 옆 -ĥ 쪽 (β > 0이면 태양 반대쪽)
}
HOLD_KO = {"vbar-": "뒤(V-bar)", "vbar+": "앞(V-bar)", "rbar-": "아래(R-bar)", "hbar+": "옆·태양 쪽(H-bar)",
           "hbar-": "옆·반대쪽(H-bar)"}
_AX = {"r": np.array([1.0, 0, 0]), "t": np.array([0, 1.0, 0]), "h": np.array([0, 0, 1.0])}


def _axis(s: str) -> np.ndarray:
    return -_AX[s[1]] if s.startswith("-") else _AX[s]


def dcm2quat(D: np.ndarray) -> np.ndarray:
    """quat2dcm의 역 (스칼라 먼저, q0 ≥ 0). quat2dcm(dcm2quat(D)) == D."""
    D = np.asarray(D, float)
    # quat2dcm(q)는 수동(passive) 회전행렬이라 표준 능동 행렬 A = D^T 에서 사원수를 뽑는다
    A = D.T
    tr = np.trace(A)
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        q = [0.25 * s, (A[2, 1] - A[1, 2]) / s, (A[0, 2] - A[2, 0]) / s, (A[1, 0] - A[0, 1]) / s]
    elif A[0, 0] > A[1, 1] and A[0, 0] > A[2, 2]:
        s = np.sqrt(1.0 + A[0, 0] - A[1, 1] - A[2, 2]) * 2
        q = [(A[2, 1] - A[1, 2]) / s, 0.25 * s, (A[0, 1] + A[1, 0]) / s, (A[0, 2] + A[2, 0]) / s]
    elif A[1, 1] > A[2, 2]:
        s = np.sqrt(1.0 + A[1, 1] - A[0, 0] - A[2, 2]) * 2
        q = [(A[0, 2] - A[2, 0]) / s, (A[0, 1] + A[1, 0]) / s, 0.25 * s, (A[1, 2] + A[2, 1]) / s]
    else:
        s = np.sqrt(1.0 + A[2, 2] - A[0, 0] - A[1, 1]) * 2
        q = [(A[1, 0] - A[0, 1]) / s, (A[0, 2] + A[2, 0]) / s, (A[1, 2] + A[2, 1]) / s, 0.25 * s]
    q = np.array(q)
    q /= np.linalg.norm(q)
    return q if q[0] >= 0 else -q


def cam_from_lvlh(hold: str) -> np.ndarray:
    """LVLH 벡터 → 카메라 좌표 회전행렬 (행 = 카메라 x, y, z 축을 LVLH로 쓴 것)."""
    toward, up_name = HOLDS[hold]
    u = _axis(toward)            # 목표 → 추적 위성
    z = -u                       # 카메라는 목표를 본다
    up = _axis(up_name)
    up = up - up.dot(z) * z
    y = -up / np.linalg.norm(up)  # 이미지 y는 아래쪽
    x = np.cross(y, z)
    return np.vstack([x, y, z])


@dataclass
class Orbit:
    altitude_km: float = 500.0
    beta_deg: float = 30.0

    @property
    def a(self) -> float:
        return R_EARTH + self.altitude_km

    @property
    def period_s(self) -> float:
        return 2 * np.pi * np.sqrt(self.a ** 3 / MU_EARTH)

    def state(self, u_deg: np.ndarray) -> dict[str, np.ndarray]:
        """위도 인수 u [deg]에서 LVLH로 쓴 태양 방향과 식 여부."""
        u = np.radians(np.asarray(u_deg, float))
        b = np.radians(self.beta_deg)
        # 궤도면 좌표 (P, Q, H) 성분
        s_pqh = np.array([np.cos(b), 0.0, np.sin(b)])
        r_hat = np.stack([np.cos(u), np.sin(u), np.zeros_like(u)], -1)
        t_hat = np.stack([-np.sin(u), np.cos(u), np.zeros_like(u)], -1)
        # 태양 방향을 LVLH(r̂, t̂, ĥ)로
        s_lvlh = np.stack([r_hat @ s_pqh, t_hat @ s_pqh, np.full_like(u, s_pqh[2])], -1)
        # 원통 그림자: 태양 반대편이고 태양-지구 축에서 지구 반지름 안
        r_vec = self.a * r_hat
        along = r_vec @ s_pqh
        perp = np.linalg.norm(r_vec - along[:, None] * s_pqh[None, :], axis=1)
        eclipse = (along < 0) & (perp < R_EARTH)
        return dict(u_deg=np.degrees(u) % 360, s_lvlh=s_lvlh, eclipse=eclipse)


def target_attitude_lvlh(q_ref, ref_hold: str = "vbar-") -> np.ndarray:
    """기준 정지 위치에서 SPEED+ 자세 q_ref로 보이도록 목표의 LVLH 고정 자세(body ← LVLH DCM)를 정한다."""
    return quat2dcm(q_ref) @ cam_from_lvlh(ref_hold)


def relative_pose(body_from_lvlh: np.ndarray, hold: str, dist_m: float) -> tuple[np.ndarray, np.ndarray]:
    """정지 위치 hold에서 본 목표 자세 (q_vbs2tango, r_Vo2To_vbs). 목표는 화면 가운데."""
    C = cam_from_lvlh(hold)
    body_from_cam = body_from_lvlh @ C.T
    return dcm2quat(body_from_cam), np.array([0.0, 0.0, float(dist_m)])


def sun_in_camera(s_lvlh: np.ndarray, hold: str) -> np.ndarray:
    return s_lvlh @ cam_from_lvlh(hold).T


def phase_azimuth_deg(r_cam: np.ndarray, s_cam: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """위상각(위성에서 본 카메라 방향과 태양 방향 사이 각)과 이미지 기준 방위각(0° 오른쪽, 90° 위).

    geometry.sun_direction_cam의 정의와 같다.
    """
    r = np.asarray(r_cam, float)
    to_cam = -r / np.linalg.norm(r)
    right = np.array([1.0, 0.0, 0.0])
    right = right - right.dot(to_cam) * to_cam
    right /= np.linalg.norm(right)
    up = np.cross(to_cam, right)
    if up.dot(np.array([0.0, -1.0, 0.0])) < 0:
        up = -up
    s = np.atleast_2d(s_cam)
    phase = np.degrees(np.arccos(np.clip(s @ to_cam, -1.0, 1.0)))
    az = np.degrees(np.arctan2(s @ up, s @ right)) % 360
    return phase, az


# 실패 지도 (README Phase 2·3, SPNv2 offline, 렌더 6,500장): 위상각 → 실패율. 다시 만든 표가 있으면 그것을 쓴다.
FAILURE_MAP_V01 = {0: 0.010, 20: 0.016, 40: 0.040, 60: 0.115, 80: 0.152, 100: 0.230, 120: 0.314, 140: 0.476, 160: 0.706}


def p_fail_from_map(phase_deg: np.ndarray, table: dict[float, float] | None = None) -> np.ndarray:
    """위상각별 실패율을 선형 보간. 160° 넘는 역광은 160° 값(하한)으로 둔다."""
    t = table or FAILURE_MAP_V01
    xs = np.array(sorted(t))
    ys = np.array([t[x] for x in xs])
    return np.interp(np.asarray(phase_deg, float), xs, ys, left=ys[0], right=ys[-1])
