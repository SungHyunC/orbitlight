"""SPNv2 `per_sample_performance.mat` 읽기.

주의: SPNv2(`core/engine/inference.py`)는 heatmap 헤드가 자세 계산을 포기한(reject) 이미지를
`heat_*` 배열에 **넣지 않는다**. `h_reject`만 전체 이미지 길이다. 그래서 `heat_*`의 i번째 값은
i번째 이미지가 아니다. `load_per_sample`은 `heat_*`를 전체 길이로 펼치고 거부 위치를 NaN으로 채운다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.io import loadmat


def load_per_sample(path: str | Path) -> dict[str, np.ndarray]:
    m = loadmat(path)
    d = {k: np.ravel(v) for k, v in m.items() if not k.startswith("__")}
    reject = d["h_reject"].astype(bool)
    n = len(reject)
    for k, v in list(d.items()):
        if k.startswith("heat_") and len(v) != n:
            assert len(v) == n - reject.sum(), (k, len(v), n, reject.sum())
            full = np.full(n, np.nan)
            full[~reject] = v
            d[k] = full
    d["h_reject"] = reject
    return d


def failed(d: dict[str, np.ndarray], deg: float = 10.0) -> np.ndarray:
    """실패 = heatmap 회전 오차 > deg 또는 거부."""
    e = d["heat_eR"]
    return d["h_reject"] | ~np.isfinite(e) | (np.nan_to_num(e, nan=np.inf) > deg)
