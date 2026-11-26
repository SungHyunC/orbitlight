"""시연 영상 만들기: 장면별 한국어 내레이션(macOS say) → 웹 데모 자동 녹화 → 소리·자막 합성.

    python3 demo/make.py                    # demo/out/orbitlight-demo.mp4
    python3 demo/make.py --voice Yuna --rate 185
    python3 demo/make.py --dry              # 녹화 없이 장면 길이만 출력
    python3 demo/make.py --narration-dir 내_녹음_폴더   # 장면 id.m4a/.wav로 직접 녹음한 목소리 사용

필요: macOS(say), ffmpeg(libass), Node + demo/node_modules(playwright), Google Chrome.
장면과 동작은 demo/narration.json. 숫자는 결과에 맞춰 그 파일에서 고친다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
OUT = DEMO / "out"
FONT = "Apple SD Gothic Neo"


def sh(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def duration(path: Path) -> float:
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]).strip())


def srt_time(t: float) -> str:
    h, r = divmod(max(t, 0.0), 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def split_lines(text: str, width: int = 34) -> list[str]:
    """문장 단위로 자르고, 길면 어절 단위로 다시 나눈다 (자막 한 줄 최대 width자)."""
    out = []
    for sent in re.split(r"(?<=[.?!])\s+", text.strip()):
        cur = ""
        for w in sent.split():
            if len(cur) + len(w) + 1 > width and cur:
                out.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            out.append(cur)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--voice", default="Yuna")
    p.add_argument("--rate", type=int, default=185, help="say 말하기 속도 (단어/분)")
    p.add_argument("--narration-dir", default=None, help="장면 id 이름의 녹음 파일(.m4a/.wav/.aiff)이 있으면 TTS 대신 사용")
    p.add_argument("--width", type=int, default=1600)
    p.add_argument("--height", type=int, default=900)
    p.add_argument("--dry", action="store_true")
    a = p.parse_args()
    cfg = json.loads((DEMO / "narration.json").read_text())
    (OUT / "tts").mkdir(parents=True, exist_ok=True)

    # 1) 장면별 음성과 길이
    t, scenes = 0.0, []
    for sc in cfg["scenes"]:
        audio = None
        if a.narration_dir:
            for ext in (".m4a", ".wav", ".aiff", ".mp3"):
                cand = Path(a.narration_dir) / f"{sc['id']}{ext}"
                if cand.exists():
                    audio = cand
        if audio is None:
            audio = OUT / "tts" / f"{sc['id']}.aiff"
            sh(["say", "-v", a.voice, "-r", str(a.rate), "-o", str(audio), sc["text"]])
        d = duration(audio)
        dur = max(d + sc.get("pad", 0.9), sc.get("min", 0.0))
        scenes.append(dict(id=sc["id"], start=t, dur=dur, speech=d, audio=str(audio), text=sc["text"], actions=sc.get("actions", [])))
        t += dur
    total = t + 1.0
    print("\n".join(f"{s['id']:>10s} {s['start']:6.1f}s +{s['dur']:5.1f}s  (말 {s['speech']:.1f}s)" for s in scenes))
    print(f"total {total:.1f}s")
    if a.dry:
        return 0

    # 2) 녹화
    tl = dict(page=str(ROOT / "site" / "index.html"), width=a.width, height=a.height, total=total,
              scenes=[{k: s[k] for k in ("id", "start", "dur", "actions")} for s in scenes])
    (OUT / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1))
    rec = OUT / "rec"
    for f in rec.glob("*.webm"):
        f.unlink()
    print(sh(["node", str(DEMO / "record.mjs"), str(OUT / "timeline.json"), str(rec)]))
    lead = float((rec / "lead.txt").read_text())

    # 3) 자막 (문장 길이에 비례해 말하는 시간을 나눔)
    n, lines = 1, []
    for s in scenes:
        parts = split_lines(s["text"])
        total_chars = sum(len(x) for x in parts) or 1
        cur = s["start"] + 0.15
        for x in parts:
            d = s["speech"] * len(x) / total_chars
            lines.append(f"{n}\n{srt_time(cur)} --> {srt_time(cur + d)}\n{x}\n")
            n += 1
            cur += d
    (OUT / "subtitles.srt").write_text("\n".join(lines), encoding="utf-8")

    # 4) 소리: 장면 시작 시각에 맞춰 이어 붙임
    inputs, filters = [], []
    for i, s in enumerate(scenes):
        inputs += ["-i", s["audio"]]
        ms = int(round(s["start"] * 1000))
        filters.append(f"[{i}:a]aresample=48000,adelay={ms}|{ms},apad[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(scenes))) + f"amix=inputs={len(scenes)}:normalize=0,atrim=0:{total:.2f}[aout]"
    sh(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters) + ";" + mix, "-map", "[aout]",
        "-ac", "1", str(OUT / "narration.wav")])

    # 5) 합성: 앞부분(로딩) 잘라내고, 자막을 입히고, 소리를 붙인다
    style = f"FontName={FONT},FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=28"
    final = OUT / "orbitlight-demo.mp4"
    sh(["ffmpeg", "-y", "-v", "error", "-ss", f"{lead:.2f}", "-i", str(rec / "screen.webm"), "-i", str(OUT / "narration.wav"),
        "-vf", f"subtitles={OUT / 'subtitles.srt'}:force_style='{style}',fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}",
        "-movflags", "+faststart", str(final)])
    print(f"-> {final} ({duration(final):.1f}s, {final.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
