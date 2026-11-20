# third_party

외부 코드는 git에 넣지 않고 여기에 클론한다.

| 이름 | 저장소 | 용도 |
|---|---|---|
| spnv2 | https://github.com/tpark94/spnv2 (커밋 `debee80`, MIT) | 기준 자세 추정 모델 (Phase 1) |

```bash
git clone https://github.com/tpark94/spnv2.git third_party/spnv2
git -C third_party/spnv2 checkout debee80
```
