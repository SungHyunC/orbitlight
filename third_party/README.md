# third_party

외부 코드는 git에 넣지 않고 여기에 클론한다.

| 이름 | 저장소 | 용도 |
|---|---|---|
| spnv2 | https://github.com/tpark94/spnv2 (커밋 `debee80`, MIT) | 기준 자세 추정 모델 (Phase 1) |
| SPIN Tango 모형 | https://github.com/vpulab/SPIN (커밋 `26bd56f`, **GPL-3.0**) | Phase 2 렌더링용 3D 모형. `tango_fix.obj`만 사용 |

```bash
git clone https://github.com/tpark94/spnv2.git third_party/spnv2
git -C third_party/spnv2 checkout debee80
git -C third_party/spnv2 apply ../patches/spnv2-savemat-none.patch
git -C third_party/spnv2 apply ../patches/spnv2-albumentations14.patch
git -C third_party/spnv2 apply ../patches/spnv2-heatmap-peaks.patch
```

### 패치
- `patches/spnv2-savemat-none.patch`: 평가 마지막에 이미지별 결과(`per_sample_performance.mat`, `predictions_pose.mat`)를
  저장할 때, heatmap 헤드가 자세 계산을 포기한(reject) 샘플의 `None` 값을 최신 SciPy가 저장하지 못해 멈춘다.
  `None`을 `NaN`으로 바꿔 저장하도록 고쳤다. 평균 점수 계산에는 영향이 없다 (패치 전후 sunlamp 결과 동일).
- `patches/spnv2-albumentations14.patch`: **학습**할 때만 필요. SPNv2의 사용자 정의 증강 두 개(`CoarseDropout`, `RandomSunFlare`)가
  albumentations 1.4(고정 버전 1.4.24)와 안 맞아서 멈춘다. ① 부모 클래스 인자 순서가 `(p, always_apply)`로 바뀜 → 이름으로 전달,
  ② `A.functional.cutout` 삭제 → 같은 동작의 작은 함수로 대체, `add_sun_flare` → `add_sun_flare_overlay`(같은 기능, 인자 묶음만 다름),
  ③ 상자(bbox)를 그대로 통과시키는 `apply_to_bboxes` 추가 (1.4는 기본 통과를 안 함), ④ 구멍 채움 값이 `randint(0, 256)`이라
  256이 나오면 NumPy 2에서 오류 → 예전 NumPy처럼 256을 0으로 처리. 증강 동작 자체는 바꾸지 않았다.
- `patches/spnv2-heatmap-peaks.patch` (v0.2): 평가할 때 이미지마다 키포인트 11개 히트맵의 최댓값을
  `predictions_pose.mat`의 `heat_peak`(N×11)로 저장한다. 실패 자가 경고(`scripts/self_check.py`)의 "키포인트 확신도" 신호다.
  원래 코드는 전체 히트맵(이미지당 약 1 MB)을 메모리에 모으기만 하고 저장하지 않았는데, 그 자리에서 최댓값만 모으므로
  평가 메모리도 줄어든다. 자세 계산과 점수는 바뀌지 않는다.
- 주의: SPNv2 `per_sample_performance.mat`의 `heat_*` 배열은 자세 계산 거부 이미지를 **빼고** 저장된다 (`h_reject`만 전체 길이).
  이미지별로 맞춰 쓰려면 `src/orbitlight/eval/spnv2_results.py::load_per_sample`을 쓴다.

## SPNv2 공개 학습 가중치

SPNv2 README의 OneDrive 링크(`pretrained_models` 폴더)에서 브라우저로 받아 `outputs/pretrained/`에 둔다 (git 제외).
OneDrive가 스크립트 접근을 막아서 자동 다운로드 스크립트는 없다.

| 파일 | 크기 | SHA-256 | 내용 |
|---|---|---|---|
| `spnv2_efficientnetb3_fullconfig_offline.pth.tar` | 55,320,971 B | `d8f9c281…b719514cc` | φ=3, BN, 합성 데이터로만 학습 (offline) |
| `spnv2_efficientnetb3_fullconfig_odr_B4_N1024.pth.tar` | 55,320,971 B | `b3e5278b…b884ef9e9` | 위 모델 + ODR(Online Domain Refinement), B=4, N=1024 |

전체 해시는 `outputs/pretrained/SHA256SUMS`. 두 파일 모두 `offline_train_full_config_phi3_BN.yaml`로 만든 모델에
`load_state_dict(strict=True)`로 문제없이 들어간다 (`torch.load(..., weights_only=True)`).
φ=6(GN) 가중치는 공개 폴더에 없다.

## Tango 3D 모형 (SPIN)

`bash scripts/download_tango_model.sh` → `data/models/spin_tango/tango_fix.obj` (git 제외, SHA-256 `162fc7a1…1e9881`).
GPL-3.0 파일이라 이 저장소에 넣지 않고 받아서 쓴다.

- 단위 cm, 축은 SPNv2 키포인트(`tangoPoints.mat`)와 같다 → **0.01배만 하면 회전·이동 보정 없이 맞는다**.
  태양전지판 모서리 키포인트 4개는 메시 꼭짓점과 1.5mm 이내, 나머지 7개(몸체 아래 모서리, 안테나 끝)는 18~25mm 차이.
  SPEED+ 이미지에 정답 자세로 투영한 실루엣이 합성·lightbox·sunlamp 모두에서 위성 윤곽과 겹치는 것을 눈으로 확인했다.
- 얇은 와이어 안테나 몇 개는 모형에 없다.
- 원래 재질 파일(`tango v32.mtl`)과 맞는 텍스처는 저장소에 없다 (`mangotango.tga`는 이 OBJ의 UV와 안 맞음).
  재질은 OBJ의 재질 이름을 보고 `src/orbitlight/render/blender_render.py`에서 직접 정했다.
