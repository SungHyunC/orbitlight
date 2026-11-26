"""반복 학습의 편차 그림: 조건별(비교군 A, 전체 + 렌더 C) 시드마다의 실패율을 점으로, 공개 가중치를 선으로.

    python scripts/seed_spread_figure.py          # outputs/failure_map/finetune_stats.json → outputs/figures/seed_spread.png
    python scripts/seed_spread_figure.py --deck   # 발표자료용(한글, 큰 글씨, 제목 없음) → outputs/figures/seed_spread_deck.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = {"lightbox": 0.081, "sunlamp": 0.130, "renders": 0.253}   # 공개 offline 가중치 (base-004, sweep-005)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--deck", action="store_true", help="발표자료용: 한글 라벨, 큰 글씨, 제목 없음, 슬라이드 그림 카드와 같은 종이색 배경")
    a = p.parse_args()
    deck = a.deck
    BG, INK, INK2, GRID = ("#F7F6F2" if deck else "#fcfcfb"), "#0b0b0b", "#52514e", "#e4e3df"
    COL = {"A": "#2a78d6", "C": "#e08a1c"}
    if deck:
        from matplotlib import font_manager   # 설치된 한글 글꼴만 (없는 이름은 글자마다 경고가 남)
        have = {f.name for f in font_manager.fontManager.ttflist}
        plt.rcParams["font.family"] = [f for f in ("Apple SD Gothic Neo", "AppleGothic", "NanumGothic", "Noto Sans CJK KR") if f in have] + ["DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
    fs = dict(tick=17, val=14, leg=15, lab=16) if deck else dict(tick=10, val=9, leg=9, lab=10)
    lab_a, lab_c, lab_p = (("A 비교군: SPEED+ 16k", "C: A + 무작위 재질 렌더 7.5k", "공개 가중치") if deck else
                           ("A: SPEED+ 16k (control)", "C: SPEED+ 16k + randomized renders", "public weights"))
    st = json.loads((ROOT / "outputs" / "failure_map" / "finetune_stats.json").read_text())
    groups = {}
    for g in st["seeds"]:
        cond = "A" if "ftctrl" in g["weights"][0] else "C"
        groups[(cond, g["domain"])] = g["rates"]
    doms = ([("lightbox", "lightbox\n(실물 조명)"), ("sunlamp", "sunlamp\n(실물 조명)"), ("renders", "태양 실험 렌더")] if deck else
            [("lightbox", "lightbox (real lighting)"), ("sunlamp", "sunlamp (real lighting)"), ("renders", "sun-sweep renders")])
    fig, ax = plt.subplots(figsize=(9, 4.1) if deck else (11, 5.2), dpi=200 if deck else 180, facecolor=BG)
    ax.set_facecolor(BG)
    for i, (d, lab) in enumerate(doms):
        for j, cond in enumerate(("A", "C")):
            r = groups.get((cond, d), [])
            x = i + (j - 0.5) * (0.44 if deck else 0.36)   # 발표용은 글씨가 커서 값 라벨이 겹치지 않게 더 벌림
            if r:
                ax.plot([x, x], [min(r) * 100, max(r) * 100], color=COL[cond], lw=6, alpha=0.35, solid_capstyle="round")
                ax.scatter([x] * len(r), [v * 100 for v in r], s=140 if deck else 90, color=COL[cond], zorder=3,
                           label=(lab_a if cond == "A" else lab_c) if i == 0 else None)
                ax.text(x + (0 if deck else 0.07), max(r) * 100 + 1.0, " · ".join(f"{v:.1%}" for v in r), color=INK2, fontsize=fs["val"], va="bottom", ha="center")
        ax.hlines(PUBLIC[d] * 100, i - 0.42, i + 0.42, color=INK2, lw=1.2, ls=":", label=lab_p if i == 0 else None)
    ax.set_xticks(range(len(doms)), [lab for _, lab in doms], color=INK, fontsize=fs["tick"])
    ax.set_ylabel("실패율 (%)" if deck else "failure rate [%] (rotation error > 10° or rejected)", color=INK2, fontsize=fs["lab"])
    ax.set_ylim(0, 30)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.tick_params(colors=INK2, labelsize=fs["tick"] - 2)
    ax.tick_params(axis="x", labelsize=fs["tick"], length=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    if not deck:
        ax.set_title("Same recipe, two training seeds each: real-lighting failure moves by up to 5.7 points;"
                     " the render gain is stable", color=INK, fontsize=11, loc="left")
    leg = ax.legend(frameon=False, fontsize=fs["leg"], loc="upper left")
    for t in leg.get_texts():
        t.set_color(INK)
    fig.tight_layout()
    out = ROOT / "outputs" / "figures" / f"seed_spread{'_deck' if deck else ''}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=BG)
    print("->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
