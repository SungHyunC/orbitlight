/* OrbitLight 웹 데모. 데이터는 data/*.js (scripts/build_site.py)가 window.ORBITLIGHT에 넣는다. 외부 라이브러리 없음. */
(function () {
  "use strict";
  const D = window.ORBITLIGHT || {};
  const S = D.sweep, H = D.hil, O = D.orbit;
  const $ = (s, el = document) => el.querySelector(s);
  const NS = "http://www.w3.org/2000/svg";
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const C = { ok: css("--ok"), fail: css("--fail"), warn: css("--warn"), accent: css("--accent"), sun: css("--sun"),
              ink2: css("--ink-2"), ink3: css("--ink-3"), line: css("--line") };

  const pct = (x, d) => x == null || isNaN(x) ? "–" : (100 * x).toFixed(d != null ? d : (x < 0.1 ? 1 : 0)) + "%";
  const deg = (x) => x == null ? "–" : `${(+x).toFixed(x < 10 ? 1 : 0)}°`;
  function el(tag, attrs = {}, parent) {
    const e = tag.startsWith("svg:") ? document.createElementNS(NS, tag.slice(4)) : document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "text") e.textContent = v; else if (k === "html") e.innerHTML = v; else e.setAttribute(k, v);
    }
    if (parent) parent.appendChild(e);
    return e;
  }
  const svg = (tag, attrs, parent) => el("svg:" + tag, attrs, parent);

  // 실패율 → 색 (낮음: 어두운 파랑, 높음: 빨강)
  const STOPS = [[0, [31, 58, 95]], [0.08, [42, 96, 140]], [0.2, [120, 110, 70]], [0.35, [196, 112, 52]], [0.55, [226, 78, 50]], [0.75, [240, 60, 60]]];
  function rateColor(r) {
    r = Math.max(0, Math.min(0.75, r || 0));
    for (let i = 1; i < STOPS.length; i++) {
      if (r <= STOPS[i][0]) {
        const [a, ca] = STOPS[i - 1], [b, cb] = STOPS[i], t = (r - a) / (b - a);
        return `rgb(${ca.map((c, k) => Math.round(c + t * (cb[k] - c))).join(",")})`;
      }
    }
    return `rgb(${STOPS[STOPS.length - 1][1].join(",")})`;
  }

  // ---------------------------------------------------------------- 그리기 공통
  const imgCache = new Map();
  function loadImg(src) {
    if (!imgCache.has(src)) imgCache.set(src, new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = src; }));
    return imgCache.get(src);
  }
  function drawPose(ctx, kp, edges, color, dashed, w) {
    if (!kp) return;
    ctx.save();
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = w; ctx.lineJoin = "round";
    if (dashed) ctx.setLineDash([7, 6]);
    ctx.beginPath();
    for (const [a, b] of edges) { ctx.moveTo(kp[a][0], kp[a][1]); ctx.lineTo(kp[b][0], kp[b][1]); }
    ctx.stroke();
    if (!dashed) for (const p of kp) { ctx.beginPath(); ctx.arc(p[0], p[1], 3.2, 0, 2 * Math.PI); ctx.fill(); }
    ctx.restore();
  }
  // 정답 키포인트 둘레를 넉넉히 잡아 확대할 영역 [x0, y0, w, h] (표시 이미지 좌표, 화면 비율 유지)
  function cropFor(kp, W, H) {
    if (!kp) return [0, 0, W, H];
    const xs = kp.map((p) => p[0]), ys = kp.map((p) => p[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const ar = W / H;
    let w = Math.max(Math.max(...xs) - Math.min(...xs), (Math.max(...ys) - Math.min(...ys)) * ar) * 1.6;
    w = Math.min(W, Math.max(220, w));
    const h = w / ar;
    const x0 = Math.min(Math.max(0, cx - w / 2), W - w), y0 = Math.min(Math.max(0, cy - h / 2), H - h);
    return [x0, y0, w, h];
  }
  let ZOOM = true;
  async function drawFrame(canvas, f, kpTrue, edges, showTrue, token) {
    const img = await loadImg(f.img);
    if (token && token !== canvas.dataset.token) return;          // 그 사이 다른 프레임이 요청됨
    const ctx = canvas.getContext("2d"), cw = canvas.width, ch = canvas.height;
    const [x0, y0, w, h] = ZOOM ? cropFor(kpTrue, cw, ch) : [0, 0, cw, ch];
    const k = cw / w, T = (kp) => kp && kp.map((p) => [(p[0] - x0) * k, (p[1] - y0) * k]);
    ctx.fillStyle = "#000"; ctx.fillRect(0, 0, cw, ch);
    if (img) {
      const sx = img.naturalWidth / cw, sy = img.naturalHeight / ch;
      ctx.drawImage(img, x0 * sx, y0 * sy, w * sx, h * sy, 0, 0, cw, ch);
    }
    if (showTrue) drawPose(ctx, T(kpTrue), edges, "rgba(255,255,255,.75)", true, 1.6);
    drawPose(ctx, T(f.kp), edges, f.fail ? C.fail : C.ok, false, 2.6);
    if (f.warn) {
      const fs = Math.round(cw / 22);
      ctx.save(); ctx.font = `700 ${fs}px ` + css("--font");
      const tw = ctx.measureText("⚠ 자가 경고").width;
      ctx.fillStyle = "rgba(0,0,0,.55)"; ctx.fillRect(10, 10, tw + 24, fs * 1.6);
      ctx.fillStyle = "rgba(255,194,71,1)"; ctx.fillText("⚠ 자가 경고", 22, 10 + fs * 1.15); ctx.restore();
    }
  }
  const tag = (cls, text) => `<span class="tag ${cls}">${text}</span>`;

  // ---------------------------------------------------------------- 탭
  const tabs = [...document.querySelectorAll(".tabs button")];
  function show(name) {
    for (const b of tabs) b.setAttribute("aria-selected", String(b.dataset.tab === name));
    for (const p of document.querySelectorAll(".panel")) p.hidden = p.id !== "tab-" + name;
    if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  }
  tabs.forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
  const initial = (location.hash || "#sweep").slice(1);
  show(tabs.some((b) => b.dataset.tab === initial) ? initial : "sweep");

  // ---------------------------------------------------------------- 상단 숫자
  (function stats() {
    const box = $("#stats");
    const add = (v, k) => { const d = el("div", { class: "stat" }, box); el("div", { class: "v", html: v }, d); el("div", { class: "k", text: k }, d); };
    if (S) add(`${pct(S.by_phase[S.phases[0]])} → ${pct(S.by_phase[S.phases[S.phases.length - 1]])}`,
      `태양이 위성 뒤로 갈수록 AI 실패율 (위상각 ${S.phases[0]}° → ${S.phases[S.phases.length - 1]}°, 렌더 6,500장)`);
    const sl = H && H.domains && H.domains.sunlamp;
    if (sl) add(`${pct(sl.fail_rate)} → ${pct(sl.kept_fail_rate)}`, `실물 조명(sunlamp) 사진의 실패율, 자가 경고가 뜬 사진을 빼면 (경고 ${pct(sl.warn_rate)})`);
    const rows = O && O.plan && O.plan.rows;
    if (rows) {
      const r30 = rows.filter((r) => r.beta_deg === 30);
      const a = r30.find((r) => r.hold === "hbar+"), b = r30.find((r) => r.hold === "hbar-");
      if (a && b) add(`${a.high_min.toFixed(0)}분 vs ${b.high_min.toFixed(0)}분`, `같은 궤도에서 옆에 서는 쪽만 바꿨을 때 한 바퀴 중 위험 시간 (β=30°)`);
    }
  })();

  // ---------------------------------------------------------------- ① 태양 실험
  (function sweep() {
    const panel = $("#tab-sweep");
    if (!S) { el("p", { class: "empty", text: "태양 실험 데이터가 아직 없습니다 (scripts/build_site.py)." }, panel); return; }
    const edges = S.meta.edges, canvas = $("#sweep-canvas");
    canvas.width = S.meta.image_w; canvas.height = S.meta.image_h;
    let pi = Math.min(2, S.poses.length - 1), ph = 0, az = 0, playing = null;
    const AZ_KO = { 0: "이미지 오른쪽", 45: "오른쪽 위", 90: "위", 135: "왼쪽 위", 180: "왼쪽", 225: "왼쪽 아래", 270: "아래", 315: "오른쪽 아래" };

    // 자세 고르기
    const chips = $("#pose-chips");
    S.poses.forEach((p, i) => {
      const b = el("button", { class: "chip", "aria-pressed": String(i === pi) }, chips);
      el("img", { src: p.frames["0_0"].img, alt: "" }, b);
      el("span", { text: `자세 ${i + 1} · 실패 ${p.fails}/${Object.keys(p.frames).length}` }, b);
      b.addEventListener("click", () => { pi = i; [...chips.children].forEach((c, k) => c.setAttribute("aria-pressed", String(k === i))); render(); });
    });

    // 극좌표 원판: 가운데 = 위상각 0°(정면 조명), 바깥 = 160°(역광). 방위각 0° = 이미지 오른쪽, 90° = 위
    const polar = $("#polar");
    polar.setAttribute("viewBox", "-180 -180 360 360");
    const R0 = 15, W = (150 - R0) / (S.phases.length - 1);
    const pt = (r, a) => [r * Math.cos(a * Math.PI / 180), -r * Math.sin(a * Math.PI / 180)];
    function sector(r0, r1, a0, a1) {
      const [x0, y0] = pt(r1, a0), [x1, y1] = pt(r1, a1), [x2, y2] = pt(r0, a1), [x3, y3] = pt(r0, a0);
      return `M${x0},${y0} A${r1},${r1} 0 0 0 ${x1},${y1} L${x2},${y2} A${r0},${r0} 0 0 1 ${x3},${y3} Z`;
    }
    const cellGeom = {};
    S.phases.forEach((p, k) => {
      if (k === 0) {
        const c = svg("circle", { class: "cell", r: R0, cx: 0, cy: 0, fill: rateColor(S.cells["0_0"]) }, polar);
        c.addEventListener("click", () => select(0, 0));
        el("svg:title", { text: `위상각 0° · 실패율 ${pct(S.cells["0_0"])}` }, c);
        cellGeom["0_0"] = { r: 0, a: 0, r0: 0, r1: R0 };
        return;
      }
      const r0 = R0 + (k - 1) * W, r1 = R0 + k * W;
      for (const a of S.azimuths) {
        const key = `${p}_${a}`;
        const c = svg("path", { class: "cell", d: sector(r0, r1, a - 22.5, a + 22.5), fill: rateColor(S.cells[key]) }, polar);
        el("svg:title", { text: `위상각 ${p}° · 태양 ${AZ_KO[a] || a + "°"} · 실패율 ${pct(S.cells[key])}` }, c);
        c.addEventListener("click", () => select(p, a));
        cellGeom[key] = { r: (r0 + r1) / 2, a, r0, r1 };
      }
    });
    for (const [t, a] of [["오른쪽", 0], ["위", 90], ["왼쪽", 180], ["아래", 270]]) {
      const [x, y] = pt(163, a);
      svg("text", { x, y: y + 4, "text-anchor": "middle" }, polar).textContent = t;
    }
    const dots = svg("g", {}, polar);
    const selRing = svg("path", { class: "sel" }, polar);

    // 범례와 위상각별 막대
    const lg = $("#polar-legend");
    el("span", { text: "0%" }, lg);
    el("div", { class: "bar", style: `background:linear-gradient(90deg,${[0, .1, .2, .35, .55, .75].map(rateColor).join(",")})` }, lg);
    el("span", { text: "75%+" }, lg);
    el("span", { text: "자세 100개 실패율" }, lg);
    const bars = $("#phase-bars");
    const barRows = {};
    for (const p of S.phases) {
      const row = el("div", { class: "row" }, bars);
      el("span", { text: `${p}°` }, row);
      const tr = el("div", { class: "track" }, row);
      el("div", { class: "fill", style: `width:${100 * S.by_phase[p]}%;background:${rateColor(S.by_phase[p])}` }, tr);
      el("span", { text: pct(S.by_phase[p]) }, row);
      barRows[p] = row;
    }
    el("div", { text: "위상각별 실패율 (방위 8곳 평균)", style: "margin-top:4px;color:var(--ink-3)" }, bars);

    function select(p, a) { ph = p; az = p === 0 ? 0 : a; render(); }
    function render() {
      const pose = S.poses[pi], key = ph === 0 ? "0_0" : `${ph}_${az}`, f = pose.frames[key];
      if (!f) return;
      // 고른 자세의 칸별 결과 점
      dots.innerHTML = "";
      for (const [k, g] of Object.entries(cellGeom)) {
        const fr = pose.frames[k];
        if (!fr) continue;
        const [x, y] = pt(g.r, g.a);
        svg("circle", { cx: x, cy: y, r: 3.2, fill: fr.fail ? C.fail : C.ok, stroke: "#000", "stroke-width": 0.8, "pointer-events": "none" }, dots);
      }
      const g = cellGeom[key];
      selRing.setAttribute("d", ph === 0 ? `M${R0},0 A${R0},${R0} 0 1 0 ${-R0},0 A${R0},${R0} 0 1 0 ${R0},0` : sector(g.r0, g.r1, az - 22.5, az + 22.5));
      for (const [p, row] of Object.entries(barRows)) row.classList.toggle("on", +p === ph);
      canvas.dataset.token = key + pi;
      drawFrame(canvas, f, pose.kp_true, edges, $("#show-true").checked, canvas.dataset.token);
      const where = ph === 0 ? "카메라 바로 뒤 (정면 조명)" : `${AZ_KO[az] || az + "°"} 쪽`;
      const res = f.reject ? tag("fail", "자세 계산 포기") : f.fail ? tag("fail", `틀림 ${deg(f.eR)}`) : tag("ok", `맞음 ${deg(f.eR)}`);
      const w = f.warn ? tag("warn", "자가 경고 켜짐") : tag("quiet", "경고 없음");
      $("#sweep-readout").innerHTML = `위상각 <b>${ph}°</b> · 태양: ${where} &nbsp;|&nbsp; 회전 오차 ${res} &nbsp;|&nbsp; ${w}` +
        (f.kp_src === "efficientpose" ? ` <span style="color:var(--ink-3)">(키포인트 부족으로 거부 → 다른 헤드의 답을 그림)</span>` : "");
    }
    $("#show-true").addEventListener("change", render);
    $("#zoom").addEventListener("change", (e) => { ZOOM = e.target.checked; render(); document.dispatchEvent(new Event("zoom")); });
    $("#sweep-play").addEventListener("click", () => {
      if (playing) { clearInterval(playing); playing = null; $("#sweep-play").textContent = "▶ 정면 → 역광으로 돌리기"; return; }
      const a = az || S.azimuths[0];
      let k = 0;
      $("#sweep-play").textContent = "■ 멈춤";
      select(0, 0);
      playing = setInterval(() => {
        k += 1;
        if (k >= S.phases.length) { clearInterval(playing); playing = null; $("#sweep-play").textContent = "▶ 정면 → 역광으로 돌리기"; return; }
        select(S.phases[k], a);
      }, 750);
    });
    render();
  })();

  // ---------------------------------------------------------------- ② 실제 조명
  (function hil() {
    const panel = $("#tab-hil");
    if (!H || !H.domains || !Object.keys(H.domains).length) { el("p", { class: "empty", text: "실물 조명 평가 데이터가 아직 없습니다 (scripts/self_check.py → build_site.py)." }, panel); return; }
    const NAME = { lightbox: "lightbox · 반사광 조명", sunlamp: "sunlamp · 태양 모사 램프" };
    const COL = { lightbox: "#e0a03a", sunlamp: C.accent };
    const box = $("#hil-stats");
    for (const [d, v] of Object.entries(H.domains)) {
      const c = el("div", { class: "card" }, box);
      el("h4", { text: `${NAME[d] || d} (${v.n.toLocaleString()}장)` }, c);
      const kv = el("div", { class: "kv" }, c);
      const row = (k, val) => { el("span", { class: "k", text: k }, kv); el("span", { html: val }, kv); };
      row("실패율", `<b>${pct(v.fail_rate)}</b> → 경고 뜬 사진을 빼면 <b style="color:var(--ok)">${pct(v.kept_fail_rate)}</b>`);
      row("실패 중 경고로 잡은 비율", `<b>${pct(v.recall)}</b>`);
      row("경고가 뜬 사진 비율", pct(v.warn_rate));
      row("AUROC (답을 낸 사진)", (v.auroc || 0).toFixed(3));
    }
    // 위험-포함률 곡선
    const ch = $("#rc-chart"), Wd = 520, Ht = 320, m = { l: 48, r: 14, t: 14, b: 38 };
    const maxR = Math.max(...Object.values(H.domains).map((v) => v.fail_rate)) * 1.15;
    const X = (x) => m.l + x * (Wd - m.l - m.r), Y = (y) => Ht - m.b - (y / maxR) * (Ht - m.t - m.b);
    for (let k = 0; k <= 4; k++) {
      const y = (maxR * k) / 4;
      svg("line", { x1: m.l, x2: Wd - m.r, y1: Y(y), y2: Y(y), stroke: C.line }, ch);
      svg("text", { x: m.l - 6, y: Y(y) + 4, "text-anchor": "end" }, ch).textContent = pct(y, 0);
    }
    for (let k = 0; k <= 5; k++) svg("text", { x: X(k / 5), y: Ht - m.b + 16, "text-anchor": "middle" }, ch).textContent = `${k * 20}%`;
    svg("text", { x: (Wd + m.l) / 2, y: Ht - 4, "text-anchor": "middle" }, ch).textContent = "받아들인 사진 비율 (확신 높은 순)";
    for (const [d, v] of Object.entries(H.domains)) {
      svg("line", { x1: X(0), x2: X(1), y1: Y(v.fail_rate), y2: Y(v.fail_rate), stroke: COL[d], "stroke-dasharray": "4 4", opacity: 0.7 }, ch);
      const pts = v.curve.coverage.map((c, i) => `${X(c)},${Y(v.curve.risk[i])}`).join(" ");
      svg("polyline", { points: pts, fill: "none", stroke: COL[d], "stroke-width": 2.4 }, ch);
      const last = v.curve.coverage.length - 1;
      svg("text", { x: X(v.curve.coverage[last]) - 4, y: Y(v.curve.risk[last]) - 8, "text-anchor": "end", fill: COL[d] }, ch).textContent = d;
    }
    // 신호별 AUROC
    const ac = $("#auroc-card");
    el("h4", { text: "어떤 신호가 실패를 찾나 (AUROC, 0.5 = 찍기)" }, ac);
    const SIG = { "모델 내부 신호": "모델 내부 신호 (기본)", "전체 신호": "+ 이미지 밝기", "두 헤드 불일치": "두 답의 어긋남", "키포인트 확신도": "키포인트 확신도", "밝기(어두운 비율)": "어두운 정도만" };
    const bars = el("div", { class: "bars" }, ac);
    for (const s of Object.keys(SIG)) {
      for (const [d, v] of Object.entries(H.domains)) {
        const a = v.auroc_by_signal && v.auroc_by_signal[s];
        if (a == null) continue;
        const row = el("div", { class: "row" }, bars);
        el("span", { text: `${SIG[s]} · ${d}` }, row);
        const tr = el("div", { class: "track" }, row);
        el("div", { class: "fill", style: `left:0;width:${Math.max(0, (a - 0.5) / 0.5) * 100}%;background:${COL[d]}` }, tr);
        el("span", { text: a.toFixed(2) }, row);
      }
    }
    // 예시
    const GL = { caught: ["잡았다", "fail", "틀렸고 경고가 떴다"], missed: ["놓쳤다", "fail", "틀렸는데 경고가 없었다"],
                 false_alarm: ["괜한 경고", "warn", "맞았는데 경고가 떴다"], ok: ["정상", "ok", "맞았고 경고도 없었다"] };
    const gal = $("#hil-gallery");
    for (const [d, v] of Object.entries(H.domains)) {
      for (const e of v.examples) {
        const card = el("div", { class: "gcard" }, gal);
        const cv = el("canvas", { width: H.meta.image_w, height: H.meta.image_h }, card);
        const f = { img: e.img, kp: e.kp, fail: e.group === "caught" || e.group === "missed", warn: e.group === "caught" || e.group === "false_alarm" };
        cv.dataset.token = e.img;
        drawFrame(cv, f, e.kp_true, H.meta.edges, true, e.img);
        const g = GL[e.group];
        el("div", { class: "cap", html: `${tag(g[1], g[0])} ${g[2]}<br>${d} · 회전 오차 ${e.reject ? "계산 포기" : deg(e.eR)}` }, card);
      }
    }
  })();

  // ---------------------------------------------------------------- ③ 궤도
  (function orbit() {
    const panel = $("#tab-orbit");
    if (!O) { el("p", { class: "empty", text: "궤도 데이터가 아직 없습니다 (scripts/orbit_pass.py → build_site.py)." }, panel); return; }
    // 계획표: 정지 위치 × β, 칸 = 위험 시간(실패율 ≥ 30%)과 빛 받는 동안 평균 실패율
    if (O.plan) {
      const rows = O.plan.rows, betas = [...new Set(rows.map((r) => r.beta_deg))].sort((x, y) => x - y);
      const holds = [...new Set(rows.map((r) => r.hold))];
      const t = el("table", {}, $("#plan"));
      const hr = el("tr", {}, el("thead", {}, t));
      el("th", { text: "정지 위치" }, hr);
      for (const b of betas) el("th", { text: `β ${b}° · 위험 시간 / 평균 실패율` }, hr);
      const tb = el("tbody", {}, t);
      for (const h of holds) {
        const tr = el("tr", {}, tb);
        el("td", { text: rows.find((r) => r.hold === h).hold_ko }, tr);
        for (const b of betas) {
          const r = rows.find((x) => x.hold === h && x.beta_deg === b);
          el("td", { html: `<b class="${r.high_min >= 20 ? "hi" : r.high_min === 0 ? "lo" : ""}">${r.high_min.toFixed(0)}분</b> / ${pct(r.mean_p_lit)}` }, tr);
        }
      }
      const ecl = betas.map((b) => `β ${b}°: ${rows.find((r) => r.beta_deg === b).eclipse_min.toFixed(0)}분`).join(", ");
      el("p", { class: "note", text: `고도 ${O.plan.altitude_km} km 원궤도, 한 바퀴 ${rows[0].period_min.toFixed(1)}분, 지구 그림자(식) ${ecl}. 위험 시간 = 실패 지도로 예측한 실패율이 ${pct(O.plan.high, 0)} 이상인 시간. β가 클수록 태양이 궤도면에서 벗어나 있습니다.` }, $("#plan"));
    }
    const passes = O.passes || [];
    if (!passes.length) { el("p", { class: "empty", text: "렌더링한 궤도 장면이 아직 없습니다." }, $("#pass-chips")); return; }
    const edges = O.meta.edges, canvas = $("#orbit-canvas");
    canvas.width = O.meta.image_w; canvas.height = O.meta.image_h;
    let P = passes[0], k = 0, timer = null;
    const chips = $("#pass-chips");
    passes.forEach((p, i) => {
      const b = el("button", { class: "chip", "aria-pressed": String(i === 0), "data-hold": p.hold,
                               text: `${p.hold_ko} · 실제 실패 ${pct((p.result || {}).actual_fail_rate)}` }, chips);
      b.addEventListener("click", () => { P = p; k = 0; [...chips.children].forEach((c, j) => c.setAttribute("aria-pressed", String(j === i))); setup(); });
    });
    const dia = $("#orbit-diagram"), tl = $("#timeline"), slider = $("#orbit-slider");
    const RO = 112, RE = 58;
    const opt = (u, r) => [r * Math.cos(u * Math.PI / 180), -r * Math.sin(u * Math.PI / 180)];
    let marker, chaser, playhead;
    function setup() {
      // 궤도 그림: 태양은 오른쪽(+P), u = 0이 태양 쪽 지점, 진행 방향은 반시계
      dia.innerHTML = "";
      const defs = svg("defs", {}, dia);
      const gr = svg("radialGradient", { id: "earth", cx: "35%", cy: "35%" }, defs);
      svg("stop", { offset: "0%", "stop-color": "#3d7fd6" }, gr); svg("stop", { offset: "100%", "stop-color": "#0e2b57" }, gr);
      svg("circle", { r: RE, fill: "url(#earth)" }, dia);
      svg("text", { x: 0, y: 4, "text-anchor": "middle" }, dia).textContent = "지구";
      svg("circle", { r: RO, fill: "none", stroke: C.line, "stroke-width": 1.5 }, dia);
      // 식 구간과 위험 구간 (프레임의 실패 지도 위험도)
      const arc = (u0, u1, color, w) => {
        const [x0, y0] = opt(u0, RO), [x1, y1] = opt(u1, RO);
        svg("path", { d: `M${x0},${y0} A${RO},${RO} 0 ${u1 - u0 > 180 ? 1 : 0} 0 ${x1},${y1}`, stroke: color, "stroke-width": w, fill: "none", "stroke-linecap": "butt" }, dia);
      };
      const du = 360 * P.step_s / P.period_s;
      for (const [, u] of P.eclipse) arc(u - du / 2, u + du / 2, "#3a3f4b", 9);
      for (const f of P.frames) arc(f.u - du / 2, f.u + du / 2, rateColor(f.p_map), 9);
      svg("text", { x: -150, y: 0, "text-anchor": "start" }, dia).textContent = "그림자";
      const sun = svg("g", { transform: "translate(146,-128)" }, dia);
      svg("circle", { r: 9, fill: C.sun }, sun);
      svg("text", { x: -14, y: 4, "text-anchor": "end" }, sun).textContent = `태양 →`;
      svg("text", { x: 0, y: 150, "text-anchor": "middle" }, dia).textContent = `β ${P.beta_deg}° · 반시계 방향 진행 · 색 = 예측 실패율`;
      chaser = svg("circle", { r: 3.5, fill: C.accent }, dia);
      marker = svg("circle", { r: 6, fill: "#fff", stroke: "#000", "stroke-width": 1.5 }, dia);
      // 타임라인
      tl.innerHTML = "";
      const Wt = 1000, x0 = 48, x1 = 985, T = P.period_s / 60;
      const X = (t) => x0 + (t / T) * (x1 - x0);
      const top = [26, 112], bot = [146, 226];
      const Yp = (v) => top[1] - (v / 180) * (top[1] - top[0]);
      const Yr = (v) => top[1] - v * (top[1] - top[0]);
      const Ye = (e) => bot[1] - ((Math.log10(Math.max(0.3, Math.min(180, e))) - Math.log10(0.3)) / (Math.log10(180) - Math.log10(0.3))) * (bot[1] - bot[0]);
      for (const [t] of P.eclipse) svg("rect", { x: X(t), y: top[0], width: Math.max(1, X(P.step_s / 60) - x0 + 0.5), height: bot[1] - top[0], fill: "rgba(255,255,255,.05)" }, tl);
      for (const v of [0, 90, 180]) {
        svg("line", { x1: x0, x2: x1, y1: Yp(v), y2: Yp(v), stroke: C.line }, tl);
        svg("text", { x: x0 - 6, y: Yp(v) + 4, "text-anchor": "end" }, tl).textContent = `${v}°`;
      }
      for (const v of [1, 10, 100]) {
        svg("line", { x1: x0, x2: x1, y1: Ye(v), y2: Ye(v), stroke: C.line }, tl);
        svg("text", { x: x0 - 6, y: Ye(v) + 4, "text-anchor": "end" }, tl).textContent = `${v}°`;
      }
      svg("line", { x1: x0, x2: x1, y1: Ye(10), y2: Ye(10), stroke: C.fail, "stroke-dasharray": "3 4", opacity: 0.6 }, tl);
      const fr = P.frames;
      // 식(그림자) 구간에는 프레임이 없으므로 선을 끊어 그린다
      const segs = [[]];
      fr.forEach((f, i) => { if (i && f.t - fr[i - 1].t > 1.5 * P.step_s / 60) segs.push([]); segs[segs.length - 1].push(f); });
      for (const sg of segs) {
        svg("polyline", { points: sg.map((f) => `${X(f.t)},${Yp(f.phase)}`).join(" "), fill: "none", stroke: "#cfd3da", "stroke-width": 1.6 }, tl);
        svg("polyline", { points: sg.map((f) => `${X(f.t)},${Yr(f.p_map)}`).join(" "), fill: "none", stroke: "#e0a03a", "stroke-width": 1.4, "stroke-dasharray": "5 4" }, tl);
      }
      for (const f of fr) {
        svg("circle", { cx: X(f.t), cy: Ye(f.eR == null ? 180 : f.eR), r: 2.6, fill: f.fail ? C.fail : C.ok }, tl);
        if (f.warn) svg("line", { x1: X(f.t), x2: X(f.t), y1: bot[1] + 6, y2: bot[1] + 14, stroke: C.warn, "stroke-width": 2 }, tl);
      }
      svg("text", { x: x0, y: top[0] - 10 }, tl).textContent = "태양 위상각 (흰 선, 0~180°) · 실패 지도 예측 실패율 (주황 점선, 0~100%)";
      svg("text", { x: x0, y: bot[0] - 10 }, tl).textContent = "실제 회전 오차 (초록 = 맞음, 빨강 = 10° 넘게 틀림) · 노란 눈금 = 자가 경고 · 밝은 띠 = 지구 그림자";
      for (let m = 0; m <= T; m += 15) svg("text", { x: X(m), y: 266, "text-anchor": "middle" }, tl).textContent = `${m}분`;
      playhead = svg("line", { y1: top[0], y2: bot[1], stroke: "#fff", "stroke-width": 1.2 }, tl);
      tl.onclick = (ev) => {
        const r = tl.getBoundingClientRect(), t = ((ev.clientX - r.left) / r.width * Wt - x0) / (x1 - x0) * T;
        let best = 0; fr.forEach((f, i) => { if (Math.abs(f.t - t) < Math.abs(fr[best].t - t)) best = i; });
        go(best);
      };
      tl._X = X;
      slider.max = String(fr.length - 1);
      const res = P.result || {};
      let note = `빛 받는 ${fr.length}장 중 실제로 틀린 비율 ${pct(res.actual_fail_rate)} (실패 지도 예측 ${pct(res.predicted_fail_rate)}), 틀린 시간 합계 ${(res.actual_fail_min || 0).toFixed(1)}분, 지구 그림자 ${(res.eclipse_min || 0).toFixed(1)}분.`;
      if (res.fail_warned != null) note += ` 자가 경고가 틀린 장면의 ${pct(res.fail_warned)}를 잡았고, 경고가 없던 장면의 실패율은 ${pct(res.kept_fail_rate)}입니다.`;
      $("#orbit-note").textContent = note;
      go(Math.min(k, fr.length - 1));
    }
    function go(i) {
      k = i;
      const f = P.frames[k];
      slider.value = String(k);
      const [x, y] = opt(f.u, RO);
      marker.setAttribute("cx", x); marker.setAttribute("cy", y);
      const u = f.u * Math.PI / 180, tx = -Math.sin(u), ty = Math.cos(u), rx = Math.cos(u), ry = Math.sin(u);
      const off = { "vbar-": [-tx, -ty], "vbar+": [tx, ty], "rbar-": [-rx, -ry] }[P.hold] || [0, 0];
      chaser.setAttribute("cx", x + 16 * off[0]); chaser.setAttribute("cy", y - 16 * off[1]);
      chaser.style.display = off[0] || off[1] ? "" : "none";
      playhead.setAttribute("x1", tl._X(f.t)); playhead.setAttribute("x2", tl._X(f.t));
      canvas.dataset.token = P.run + k;
      drawFrame(canvas, f, P.kp_true, edges, false, canvas.dataset.token);
      $("#orbit-time").textContent = `${f.t.toFixed(1)} / ${(P.period_s / 60).toFixed(1)}분`;
      const res = f.eR == null ? tag("fail", "자세 계산 포기") : f.fail ? tag("fail", `틀림 ${deg(f.eR)}`) : tag("ok", `맞음 ${deg(f.eR)}`);
      $("#orbit-readout").innerHTML = `태양 위상각 <b>${deg(f.phase)}</b> · 실패 지도 예측 ${pct(f.p_map)} &nbsp;|&nbsp; 실제 ${res} &nbsp;|&nbsp; ${f.warn ? tag("warn", "자가 경고") : tag("quiet", "경고 없음")}`;
    }
    slider.addEventListener("input", () => go(+slider.value));
    document.addEventListener("zoom", () => go(k));
    $("#orbit-play").addEventListener("click", () => {
      if (timer) { clearInterval(timer); timer = null; $("#orbit-play").textContent = "▶ 재생"; return; }
      $("#orbit-play").textContent = "■ 멈춤";
      timer = setInterval(() => go((k + 1) % P.frames.length), 110);
    });
    setup();
  })();
})();
