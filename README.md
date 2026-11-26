# OrbitLight

**English** | [한국어](README.ko.md)

A lighting simulator for orbital scenes that maps **under which sun conditions a spacecraft pose estimation network fails**
(a "failure map"), and tests whether targeted synthetic data can reduce those failures.

> Status: **v0.2** — on top of v0.1 (reproduce the problem, sun-angle rendering, failure map + retraining experiments) it adds
> **(1) a self-check that warns when the estimate is likely wrong, (2) one-orbit scenarios, (3) a web demo and a demo video**.
> v0.1 ended with "a gain on synthetic data is not a gain on real data"; v0.2 follows that rule: thresholds are set on renders only and
> evaluated on real-lighting images. Every GPU step was re-run on Modal and reproduces the v0.1 numbers (`cloud/`).

## TL;DR

| | Result |
|---|---|
| Reproduce the gap | SPNv2 public weights: pose score is 5–8× worse on real-lighting (HIL) images than on synthetic; ~1 in 10 HIL images is off by >10° |
| Failure map | As the sun phase angle goes from 0° to 160°, the failure rate rises from 1% to 71%. The key variable is how much of the satellite is in shadow |
| Retraining | Mixing in back-lit renders cuts failures on the same-renderer sun-angle test from 26% to 14%, but raises HIL failures from 9% to 11% (lightbox) and 16% to 21% (sunlamp) |
| Domain randomization | Randomizing materials/textures in the same renders keeps the sun-angle gain (26% → 14%) and brings sunlamp failures back to the control level (15.1% vs 15.7%); lightbox is still slightly worse (9.9% vs 8.9%) |
| Lesson | An improvement on a synthetic failure map does not imply a real-world improvement. **Claims must be checked on real-lighting data** |
| **v0.2 (1) Self-check** | Disagreement between SPNv2's two heads plus keypoint confidence flags "this estimate is probably wrong". Fitted on renders only; on real-lighting images, dropping the warned images cuts failures **13.0% → 3.2% (sunlamp)** and **8.1% → 2.2% (lightbox)**, AUROC 0.906 / 0.924 |
| **v0.2 (2) One orbit** | In a 500 km circular orbit, where the chaser waits changes the risky time (beta = 30°: H-bar on the sun side 0 min vs the far side 61 min, predicted from the map). Rendering those passes: 2.9% vs 11.1% failures |
| **v0.2 (3) Web demo** | Open `site/index.html` (no server, no network): move the sun, see warnings on real-lighting photos, play an orbit |

## Problem

- **Sim-to-real gap**: pose estimation networks are trained on synthetic images, but real orbital images have extreme
  contrast (no atmospheric scattering) and mirror-like surfaces, so accuracy drops.
- **Lighting is not controlled systematically**: sun direction, Earth albedo and eclipse change along the orbit,
  but existing benchmarks do not break results down by lighting condition.

## Approach

1. Reproduce the synthetic → HIL (Hardware-in-the-Loop) performance gap with the SPEED+ dataset and the SPNv2 baseline.
2. Render the Tango satellite in Blender while sweeping only the sun direction.
3. Plot error vs. sun angle (failure map), then retrain with synthetic data that targets the weak conditions.

## Results

### Phase 1 — Reproducing the gap: SPNv2 baseline

The authors' public SPNv2 weights (φ=3, BN, trained on synthetic images only) evaluated on the three SPEED+ domains.
Metrics follow SPEC2021 (E_T: translation error, E_R: rotation error, E_pose: normalized combined score, lower is better).

| Domain | Images | E_T [m] | E_R [°] | E_pose | Paper E_pose | Median rot. error | Share > 10° |
|---|---|---|---|---|---|---|---|
| Synthetic validation | 11,994 | 0.054 | 0.99 | 0.027 | – | 0.77° | 0.2% |
| lightbox (HIL) | 6,740 | 0.175 | 6.44 | 0.141 | 0.142 | 1.74° | 8.1% |
| sunlamp (HIL) | 2,791 | 0.225 | 10.87 | 0.227 | 0.230 | 2.67° | 13.0% |

- Paper numbers reproduced. Moving from synthetic to real lighting makes the score **5–8× worse**.
- Most images are still accurate (median 2–3°), but **about 1 in 10 is off by more than 10°**.

![rotation error CDF](docs/figures/spnv2_rotation_error_cdf_offline.png)

Reproduce: `bash scripts/eval_spnv2_baseline.sh && python scripts/summarize_spnv2_eval.py && python scripts/plot_spnv2_error_cdf.py`

### Phase 2·3 — Failure map over sun angle

100 real poses from the SPEED+ synthetic validation set were fixed and **only the sun direction** was varied.
6,500 images were rendered with Blender (Cycles) and evaluated with the same public SPNv2 weights.

- Sun direction = **phase angle** (angle between the camera and sun directions as seen from the satellite: 0° front-lit … 180° back-lit),
  0–160° in 20° steps, × **azimuth** (which side of the image the sun is on), 8 directions.
- Satellite model: the Tango model from the SPIN simulator (GPL-3.0, not included in this repo, see `scripts/download_tango_model.sh`).
  SPEED+ camera intrinsics and lens distortion are reproduced, then images are converted to grayscale with sensor noise and saved in SPEED+ format.
- Failure = rotation error > 10° or pose rejected (same criterion as "Share > 10°" above).

![failure map](docs/figures/failure_map_offline.png)

| Phase angle | 0° | 20° | 40° | 60° | 80° | 100° | 120° | 140° | 160° |
|---|---|---|---|---|---|---|---|---|---|
| Failure rate (offline) | 1.0% | 1.6% | 4.0% | 11.5% | 15.2% | 23.0% | 31.4% | 47.6% | 70.6% |
| Median rot. error | 1.51° | 1.61° | 1.87° | 2.14° | 2.49° | 3.19° | 4.45° | 8.74° | 48.3° |

- **Failures rise steadily as the light moves to the side and back.** At 60° the rate already matches the real-lighting tests (lightbox 8.1%, sunlamp 13.0%).
- Which side of the image the sun is on (azimuth) matters little (22.9–28.5% by azimuth).
- The key variable is **the fraction of the satellite surface in shadow**. Within the same phase angle, the darker half fails about twice as often (140°: 33.5% → 61.8%).
- 43.5% of failures are **symmetric flips** with errors above 90°: the network picks the opposite orientation, not a slightly wrong one.
- The ODR weights (adapted to sunlamp) do not reduce back-lit failures either (71.1% at 160°).

![examples](docs/figures/sunsweep_examples.jpg)

**Limitations**: the original SPEED+ images of the same poses have 0% failures and a 0.72° median error, while our renders
are slightly worse even when front-lit (1.0%, 1.51°). There is a renderer (model/material) gap, so **read the trend over phase
angle rather than the absolute values.** The background is black space only; Earth albedo is not modeled yet (v0.2).

Reproduce:
```bash
bash scripts/download_tango_model.sh
python scripts/sunsweep.py jobs --run speedplus_sunsweep_v01 --n-poses 100 --sun-strength 4.0
python scripts/sunsweep.py render --run speedplus_sunsweep_v01   # ~34 min on an RTX 4070 Ti SUPER
python scripts/sunsweep.py post --run speedplus_sunsweep_v01
RUN=speedplus_sunsweep_v01 bash scripts/eval_spnv2_renders.sh
python scripts/failure_map.py --run speedplus_sunsweep_v01
```

### Phase 3b — Retraining with back-lit renders (fine-tuning)

Renders targeting the weaknesses found above (side and back lighting, shadows) were used to fine-tune SPNv2.
A **control** model with identical settings but SPEED+ images only was trained to isolate the effect of the renders.

- Training renders: 4,000 poses from the SPEED+ **synthetic train set** × 2 random sun directions = 8,000 images
  (phase angle uniform in 0–170°, random azimuth and sun strength). No overlap with the evaluation poses.
- Both models start from the public offline weights: 6 epochs, learning rate 1e-4, batch 4, single GPU.
  - Control: 16,000 SPEED+ synthetic training images
  - Experiment: 8,000 SPEED+ images + 7,500 OrbitLight renders
- SPNv2's original style augmentation (texture randomization) is off because its style images are not public. All other augmentations are unchanged.
- Both are evaluated at the final epoch to avoid model-selection bias. One training run per condition.

![fine-tuning comparison](docs/figures/finetune_compare.png)

| Model | lightbox E_pose | sunlamp E_pose | lightbox fail | sunlamp fail | Sun-angle test fail 0–40° | 60–100° | 120–160° |
|---|---|---|---|---|---|---|---|
| Public weights (offline) | 0.141 | 0.227 | 8.1% | 13.0% | 2.7% | 16.6% | 49.9% |
| Control: SPEED+ only | 0.164 | 0.278 | 8.9% | 15.7% | 3.2% | 16.3% | 53.0% |
| Experiment: + OrbitLight renders | 0.211 | 0.353 | **10.7%** | **20.6%** | **0.7%** | **5.0%** | **31.5%** |

(On the synthetic validation set all three models fail 0.2% of the time, E_pose 0.027–0.031.)

What we learned:
- **Large gains inside our own renderer.** Overall sun-angle test failures 26.4% → 13.6%; at 60–100° phase, 16.3% → 5.0%.
- **Worse on real-lighting HIL images.** Versus the control: lightbox 8.9% → 10.7%, sunlamp 15.7% → 20.6%.
  A paired McNemar test on the same images rules out chance for both (p = 1.8e-8 and 1.2e-13).
- The model also improved under front lighting (phase 0°: median rotation error 1.46° → 1.11°). That has nothing to do with
  lighting, so part of the sun-angle gain looks like **adaptation to our renderer's appearance rather than learning to handle back-lighting**.
- Training further on SPEED+ alone without style augmentation (control) already made HIL slightly worse than the public weights,
  suggesting the original style augmentation matters for robustness to real lighting.

Conclusion: **an improvement on a synthetic failure map does not guarantee a real-world improvement.** The current renders do not
transfer to real lighting. The failure map is useful for finding weaknesses, but any improvement claim has to be confirmed on real-lighting (HIL) data.

Possible causes and next experiments:
- Renderer gap: one fixed material/texture setup → randomize materials and textures in the renders (domain randomization) — **tested in Phase 3c**
- Geometry gap: checked and ruled out as a major cause — the SPIN model outline matches SPEED+ images to ~2 px (about 5 mm) and the keypoints sit in the same place relative to both (an earlier "18–25 mm" figure measured distance to the nearest mesh vertex, not to the actual feature)
- Nearly invisible back-lit images may dilute the training signal → tune the render share and phase-angle distribution
- One run per condition, so run-to-run variance is unknown → repeat training

Reproduce:
```bash
python scripts/sunsweep.py jobs --run speedplus_trainrender_v01 --pose-source synthetic/train.json \
    --n-poses 4000 --random-per-pose 2 --phase-max 170 --strength-range 3,5 --color-depth 8 --seed 1
python scripts/sunsweep.py render --run speedplus_trainrender_v01   # ~1.5 h
python scripts/sunsweep.py post --run speedplus_trainrender_v01
python scripts/build_finetune_set.py --name speedplus_ftctrl_v01 --speed-n 16000 --val-n 500
python scripts/build_finetune_set.py --name speedplus_ft_v01 --renders speedplus_trainrender_v01 --speed-n 8000 --val-n 500
DATA=speedplus_ftctrl_v01 EXP=ftctrl_v01 BATCH=4 bash scripts/finetune_spnv2.sh   # ~80 min
DATA=speedplus_ft_v01 EXP=ft_v01 BATCH=4 bash scripts/finetune_spnv2.sh
WEIGHTS="ftctrl_v01:final ft_v01:final" bash scripts/eval_spnv2_baseline.sh
RUN=speedplus_sunsweep_v01 WEIGHTS="ftctrl_v01:final ft_v01:final" bash scripts/eval_spnv2_renders.sh
python scripts/compare_finetune.py --weights offline ftctrl_v01:final ft_v01:final
```

### Phase 3c — Randomizing materials and textures (domain randomization)

Phase 3b suggested the model was adapting to one fixed look of our renderer. To test that, the **same 8,000 training renders**
were rendered again with only the surface appearance changed per image. Poses, sun directions, sun strength, the SPEED+ images
and the train/validation split are identical to Phase 3b (checked file by file), so the material setup is the only difference.

- Per image: main body brightness 0.2–0.9, metallic (0 or 0.3–1), roughness 0.1–0.8; solar panel brightness and gloss;
  other parts' brightness ×0.6–1.4.
- A procedural noise texture on every part: pattern size 2–200 per metre, brightness contrast, roughness contrast and surface bump, all random.
- With randomization off, the renderer still reproduces the earlier renders (max pixel difference 1/255).

![domain randomization comparison](docs/figures/finetune_compare_dr.png)

| Model | lightbox E_pose | sunlamp E_pose | lightbox fail | sunlamp fail | Sun-angle test fail 0–40° | 60–100° | 120–160° |
|---|---|---|---|---|---|---|---|
| Control: SPEED+ only | 0.164 | 0.278 | 8.9% | 15.7% | 3.2% | 16.3% | 53.0% |
| + renders (fixed materials, 3b) | 0.211 | 0.353 | 10.7% | 20.6% | 0.7% | 5.0% | 31.5% |
| + renders (randomized materials, 3c) | 0.181 | 0.267 | **9.9%** | **15.1%** | **0.7%** | **5.0%** | **32.0%** |

Paired McNemar tests on the same HIL images (images only one of the two models fails):

| Comparison | lightbox | sunlamp |
|---|---|---|
| Randomized vs fixed materials | 216 vs 158, p = 0.003 → **randomized better** | 224 vs 72, p = 3e-19 → **randomized better** |
| Randomized vs control | 208 vs 276, p = 0.002 → control still better | 168 vs 153, p = 0.43 → no difference |

What we learned:
- **Randomizing appearance recovers most of the real-lighting loss** while the sun-angle gain is unchanged (overall 13.9% vs 13.6%).
  So the Phase 3b HIL drop was largely caused by the single fixed material setup, not by the back-lit renders themselves.
- On sunlamp the render-trained model now matches the control; on lightbox it is still slightly worse. **It does not yet beat
  the control on real lighting**, so the renders are not yet a net real-world improvement.
- Translation (position) error is higher for both render-trained models than for the control (lightbox mean 0.30 m vs 0.22 m,
  0.38 m with fixed materials). The cause is not yet known. A model-geometry mismatch was checked and ruled out: the SPIN model outline lines up with
  SPEED+ images to about 2 px (~5 mm), with no systematic shift.
- Caveat: the render-trained models saw 8,000 SPEED+ images versus 16,000 for the control (same number of training steps),
  so part of the remaining HIL gap may come from seeing fewer SPEED+ images rather than from the renders. One run per condition.

Next: add renders on top of the full SPEED+ set instead of replacing half of it, tune the render share and phase-angle distribution,
and repeat training runs to measure run-to-run variance.

Reproduce (after Phase 3b):
```bash
python scripts/sunsweep.py jobs --run speedplus_trainrender_dr_v01 --pose-source synthetic/train.json \
    --n-poses 4000 --random-per-pose 2 --phase-max 170 --strength-range 3,5 --color-depth 8 --seed 1 --randomize-materials
python scripts/sunsweep.py render --run speedplus_trainrender_dr_v01   # ~55 min
python scripts/sunsweep.py post --run speedplus_trainrender_dr_v01
python scripts/build_finetune_set.py --name speedplus_ftdr_v01 --renders speedplus_trainrender_dr_v01 --speed-n 8000 --val-n 500
DATA=speedplus_ftdr_v01 EXP=ftdr_v01 BATCH=4 bash scripts/finetune_spnv2.sh
WEIGHTS="ftdr_v01:final" bash scripts/eval_spnv2_baseline.sh
RUN=speedplus_sunsweep_v01 WEIGHTS="ftdr_v01:final" bash scripts/eval_spnv2_renders.sh
python scripts/compare_finetune.py --weights offline ftctrl_v01:final ft_v01:final ftdr_v01:final
```

The full experiment log is in [`experiments/LOG.md`](experiments/LOG.md) (Korean).

## v0.2 — self-check, one orbit, web demo

### Reproduction on Modal

All GPU steps were re-run on Modal (`cloud/modal_app.py`, command order in `cloud/experiments.sh`). Containers lack the OptiX denoiser
weights (`/usr/share/nvidia/nvoptix.bin`), so renders are denoised with OIDN on the GPU (`blender_render.py --denoiser`).
SPNv2 offline E_pose is 0.141 / 0.227 on lightbox / sunlamp (same as v0.1), and the sun-sweep failure rates at 0°, 60°, 100°, 140°, 160°
are 1.0, 11.0, 24.0, 47.6, 69.9% (v0.1: 1.0, 11.5, 23.0, 47.6, 70.6%; every v0.1 value is inside the v0.2 95% interval).

### (1) Self-check: knowing when it is wrong

`scripts/self_check.py`, no retraining. Signals: rotation and translation disagreement between the heatmap+PnP head and the
EfficientPose head, the 11 keypoint heatmap peaks (saved by `third_party/patches/spnv2-heatmap-peaks.patch`), and, for comparison,
image darkness inside the predicted box. A logistic regression and the warning threshold (catch 90% of render failures) are fitted on
the sun-sweep renders only; HIL is used only for evaluation. Failure = rotation error > 10° or rejected, as in v0.1.

![self-check](docs/figures/self_check_offline.png)

| AUROC (answered images) | Renders (fit) | Synthetic | lightbox | sunlamp |
|---|---|---|---|---|
| **Model-internal** (head disagreement + keypoint confidence) | 0.937 | 0.944 | **0.924** | **0.906** |
| All signals (+ image darkness) | 0.943 | 0.946 | 0.916 | 0.865 |
| Head disagreement only | 0.890 | 0.881 | 0.887 | 0.857 |
| Keypoint confidence only | 0.933 | 0.950 | 0.913 | 0.893 |
| Darkness only | 0.819 | 0.712 | 0.733 | **0.500** |

Image darkness works on renders but not on real lighting (sunlamp 0.50 = chance), the v0.1 lesson again. The default score is the
model-internal set: choosing between {all, model-internal} by AUROC on one HIL domain and testing on the other picks model-internal in
both directions. With it, warned images are 16.4% (lightbox) and 25.2% (sunlamp); 77.4% and 81.5% of failures are caught; the failure
rate of the remaining images is **2.2%** and **3.2%** (from 8.1% and 13.0%).

### (2) One orbit: when is it risky?

`src/orbitlight/orbit/scenario.py`, `scripts/orbit_pass.py`: a 500 km circular orbit (94.6 min) with the sun direction and the Earth's
shadow (cylinder model). The target holds an LVLH-fixed attitude; the chaser waits at a hold point and looks at it. Beta is the angle
between the orbit plane and the sun.

![orbit plan](docs/figures/orbit_plan.png)

Rendering beta = 30° passes (target attitude of SPEED+ `img037540`, robust when front-lit and weak when back-lit; 6.6 m; 244 lit frames each):

| Hold | Actual failures | Map prediction | Failures caught by the self-check | Failures among unwarned frames |
|---|---|---|---|---|
| H-bar, sun side | **2.9%** | 11.0% | 0% (0.4% warned) | 2.9% |
| H-bar, far side | **11.1%** | 33.1% | 92.6% | 1.3% |
| R-bar, looking up | 22.5% | 34.0% | **100%** | **0%** |
| V-bar, behind | **53.7%** | 25.2% | **38.9%** | 41.7% |

The sun-side vs far-side difference holds in the renders. Limits: the failure map averages 100 poses, so a given pose can be much
worse (V-bar: right *when* the map said, after leaving the Earth's shadow, but 54% instead of 25%), and the self-check misses
"confidently wrong" estimates where both heads agree on a ~30° error. Earth albedo and the sun inside the camera's field of view are not rendered.

### (3) Web demo and demo video

Open `site/index.html` (data in `site/data/*.js`, built by `scripts/build_site.py`; image licenses in `site/img/README.md`).
The narrated Korean demo video is made by `python3 demo/make.py` (macOS voice, Playwright recording, ffmpeg subtitles).

## Setup

```bash
conda create -n orbitlight python=3.11
conda activate orbitlight
pip install -r requirements.txt   # PyTorch pinned to the CUDA 13.0 (cu130) build
pip install -e . --no-deps
python scripts/check_env.py
```

- Blender 5.2: unpack the official tarball into `~/apps/` (`scripts/check_env.py` checks the path).
- SPNv2: clone into `third_party/spnv2` and apply the patches in `third_party/patches/` (see [`third_party/README.md`](third_party/README.md)).
- Tested on Ubuntu 22.04, RTX 4070 Ti SUPER (16 GB), Python 3.11, PyTorch 2.14 (cu130).

## Layout

```
data/         datasets (not in git)
outputs/      weights, renders, plots (not in git)
third_party/  external code such as SPNv2 (not in git, clone yourself) + patches
src/orbitlight/
  render/     Blender lighting renders, post-processing
  eval/       reading evaluation results
  orbit/      (v0.2) orbit and lighting computation
scripts/      entry-point scripts
experiments/  experiment log
docs/figures/ README figures
```

## Data, code and licenses

- This repository has no license file (all rights reserved). Datasets, weights, the 3D model and rendered images are not included.
- SPEED+ (Park et al., Stanford SLAB) — CC BY-NC-SA 4.0 — https://purl.stanford.edu/wv398fc4383
- SPNv2 (Park & D'Amico) — MIT — https://github.com/tpark94/spnv2
- SPIN simulator Tango 3D model (vpulab) — GPL-3.0 — https://github.com/vpulab/SPIN
- The render examples in the README figures were made with the SPIN model above and SPEED+ pose labels.
