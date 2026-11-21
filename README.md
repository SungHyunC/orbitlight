# OrbitLight

궤도 조명 조건을 재현하는 시뮬레이터로 위성 자세 추정(spacecraft pose estimation) 모델이
**어떤 조명에서 실패하는지 "실패 지도(failure map)"로 보여주고**, 그 실패를 줄이는 합성 데이터를 만드는 프로젝트.

> 상태: v0.1 개발 중 — Phase 1(문제 재현)·Phase 2(태양 각도 렌더링)·실패 지도 완료, 재학습은 다음 단계

## 문제 정의

- **Sim-to-real gap(시뮬레이션-현실 격차)**: 자세 추정 신경망은 합성 이미지로 학습하지만, 실제 궤도 이미지는
  대기 산란이 없어 명암 대비가 극단적이고 위성 표면이 거울처럼 반사돼 성능이 떨어진다.
- **조명 변화를 체계적으로 통제하지 않음**: 궤도 위치에 따라 태양 방향, 지구 반사광(albedo),
  식(eclipse)이 바뀌는데 기존 벤치마크는 이를 조건별로 나눠 평가하지 않는다.

## 방법 (v0.1 계획)

1. SPEED+ 데이터셋과 SPNv2 기준 모델로 합성 → HIL(Hardware-in-the-Loop) 도메인 성능 격차를 재현한다.
2. Blender로 태양 방향 각도를 바꿔 가며 Tango 위성 이미지를 렌더링한다.
3. 태양 각도별 오차를 시각화해 실패 지도를 만들고, 취약 구간을 보강하는 합성 데이터로 재학습한다.

## 결과

### Phase 1 — 문제 재현: SPNv2 기준 성능 (2026-11-21)

SPNv2 저자 공개 가중치(φ=3, BN, 합성 이미지로만 학습)를 SPEED+ 세 도메인에서 평가했다.
지표는 SPEC2021 방식이다 (E_T: 위치 오차, E_R: 회전 오차, E_pose: 정규화한 종합 점수, 낮을수록 좋음).

| 도메인 | 이미지 수 | E_T [m] | E_R [°] | E_pose | 논문 E_pose | 회전 오차 중앙값 | 10° 넘는 비율 |
|---|---|---|---|---|---|---|---|
| 합성 검증셋 | 11,994 | 0.054 | 0.99 | 0.027 | – | 0.77° | 0.2% |
| lightbox (HIL) | 6,740 | 0.175 | 6.44 | 0.141 | 0.142 | 1.74° | 8.1% |
| sunlamp (HIL) | 2,791 | 0.225 | 10.87 | 0.227 | 0.230 | 2.67° | 13.0% |

- 논문 수치를 재현했다. 합성 → 실물 조명 환경으로 가면 종합 점수가 **5~8배 나빠진다**.
- 대부분의 이미지는 여전히 잘 맞추지만(중앙값 2~3°), **10장 중 1장꼴로 10° 이상 크게 틀린다**.
  이 큰 실패들이 어떤 조명 조건에서 생기는지 밝히는 것이 다음 단계(실패 지도)의 목표다.

![rotation error CDF](docs/figures/spnv2_rotation_error_cdf_offline.png)

재현: `bash scripts/eval_spnv2_baseline.sh && python scripts/summarize_spnv2_eval.py && python scripts/plot_spnv2_error_cdf.py`

### Phase 2·3 — 태양 각도별 실패 지도 (2026-11-21)

SPEED+ 합성 검증셋의 실제 자세 100개를 고정하고, **태양 방향만** 바꿔 가며 Blender(Cycles)로 6,500장을 렌더링한 뒤
같은 SPNv2 공개 가중치로 평가했다.

- 태양 방향 = **위상각**(phase angle, 위성에서 본 카메라 방향과 태양 방향 사이 각: 0° 정면 조명 ~ 180° 역광) 0~160°(20° 간격)
  × **방위각**(이미지에서 태양이 있는 쪽) 8방향.
- 위성 3D 모형은 SPIN 시뮬레이터의 Tango 모형(GPL-3.0, 저장소에 포함하지 않음, `scripts/download_tango_model.sh`).
  SPEED+ 카메라 내부 파라미터와 렌즈 왜곡을 그대로 쓰고, 흑백 변환과 센서 노이즈를 더해 SPEED+ 형식으로 저장한다.
- 실패 = 회전 오차 10° 초과 또는 자세 계산 거부 (Phase 1 표의 "10° 넘는 비율"과 같은 기준).

![failure map](docs/figures/failure_map_offline.png)

| 위상각 | 0° | 20° | 40° | 60° | 80° | 100° | 120° | 140° | 160° |
|---|---|---|---|---|---|---|---|---|---|
| 실패율 (offline) | 1.0% | 1.6% | 4.0% | 11.5% | 15.2% | 23.0% | 31.4% | 47.6% | 70.6% |
| 회전 오차 중앙값 | 1.51° | 1.61° | 1.87° | 2.14° | 2.49° | 3.19° | 4.45° | 8.74° | 48.3° |

- **조명이 옆·뒤로 돌수록 실패가 꾸준히 늘어난다.** 위상각 60°에서 이미 실물 조명 시험(lightbox 8.1%, sunlamp 13.0%) 수준이다.
- 태양이 이미지의 어느 쪽에 있는지(방위각)는 영향이 작다 (방위각별 22.9~28.5%).
- 핵심 변수는 **위성 표면이 그림자에 덮인 비율**이다. 같은 위상각 안에서도 어두운 쪽 절반의 실패율이 약 2배다 (140°: 34% → 61%).
- 실패의 43.5%는 90° 넘게 틀리는 **대칭 뒤집힘**이다. 조금 틀리는 게 아니라 아예 반대 방향으로 판단한다.
- sunlamp에 맞춰 보정한 ODR 가중치도 역광 실패를 줄이지 못했다 (160°에서 71.1%).

![examples](docs/figures/sunsweep_examples.jpg)

**한계 (정직하게)**: 같은 자세의 SPEED+ 원본 이미지는 실패 0%, 회전 오차 중앙값 0.72°인데, 우리 렌더는 정면 조명에서도
1.0%, 1.51°로 약간 나쁘다. 렌더러(모형·재질) 차이가 있다는 뜻이라 **절대값보다 위상각에 따른 추세로 읽어야 한다.**
배경은 검은 우주뿐이고 지구 반사광(albedo)은 아직 없다 (v0.2).

재현:
```bash
bash scripts/download_tango_model.sh
python scripts/sunsweep.py jobs --run speedplus_sunsweep_v01 --n-poses 100 --sun-strength 4.0
python scripts/sunsweep.py render --run speedplus_sunsweep_v01   # RTX 4070 Ti SUPER에서 약 34분
python scripts/sunsweep.py post --run speedplus_sunsweep_v01
RUN=speedplus_sunsweep_v01 bash scripts/eval_spnv2_renders.sh
python scripts/failure_map.py --run speedplus_sunsweep_v01
```

실험 기록은 [`experiments/LOG.md`](experiments/LOG.md) 참고.

## 환경 설정

```bash
conda create -n orbitlight python=3.11
conda activate orbitlight
pip install -r requirements.txt   # PyTorch는 CUDA 13.0(cu130) 빌드로 고정
pip install -e . --no-deps
python scripts/check_env.py
```

Blender는 시스템 설치 없이 공식 tarball을 `~/apps/`에 풀어서 쓴다 (`scripts/check_env.py`가 경로를 확인).

## 폴더 구조

```
data/         데이터셋 (git 제외)
outputs/      가중치, 렌더링, 그래프 (git 제외)
third_party/  SPNv2 등 외부 코드 (git 제외, 각자 클론)
src/orbitlight/
  render/     Blender 조명 렌더링
  eval/       평가 지표, 실패 지도
  orbit/      (v0.2) 궤도·조명 계산
scripts/      실행 스크립트
experiments/  실험 기록
```

## 참고

- SPEED+ — https://purl.stanford.edu/wv398fc4383
- SPNv2 (Park & D'Amico) — https://github.com/tpark94/spnv2
- SPIN 시뮬레이터 (Tango 3D 모형) — https://github.com/vpulab/SPIN
