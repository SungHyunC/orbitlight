# 실험 기록

실행해서 나온 값만 적는다. 한 줄에 한 실험.

| 날짜 | ID | 설정 | 결과 | 메모 |
|---|---|---|---|---|
| 2026-11-21 | env-001 | Blender 5.2.4 Cycles, 기본 큐브 + SUN 조명, 640×480, 64 samples, 드라이버 580.95.05 | OptiX 성공 3.3s, CUDA 성공 1.5s (프로세스 전체 시간, RTX 4070 Ti SUPER 인식) | 드라이버 업그레이드 전 측정 |
| 2026-11-21 | env-002 | torch 2.15.0+cu132 (PyPI 기본) | `cuda.is_available()=False`, Error 804 | 드라이버가 CUDA 13.0까지만 지원 → cu130 빌드로 교체 |
| 2026-11-21 | env-003 | mujoco 4.0.1, 자유낙하 구 100 step | sim_time 0.200s, z=-0.1982 | 정상 |
| 2026-11-21 | env-004 | 재부팅 후 드라이버 580.178.04, torch 2.14.1+cu130, `scripts/check_env.py` | torch GPU 인식(VRAM 15.5GiB), 4096² 행렬곱 10회 91.5ms / Blender OptiX 2.5s, CUDA 1.4s / MuJoCo 정상 | Secure Boot MOK 키 등록 후 드라이버 정상 로드 |
