# third_party

외부 코드는 git에 넣지 않고 여기에 클론한다.

| 이름 | 저장소 | 용도 |
|---|---|---|
| spnv2 | https://github.com/tpark94/spnv2 (커밋 `debee80`, MIT) | 기준 자세 추정 모델 (Phase 1) |

```bash
git clone https://github.com/tpark94/spnv2.git third_party/spnv2
git -C third_party/spnv2 checkout debee80
```

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
