// node demo/record.mjs <timeline.json> <out dir>
// 웹 데모(site/index.html)를 시스템 Chrome(헤드리스)으로 열고, timeline.json의 장면별 동작을 정해진 시각에 실행하며 녹화한다.
// 결과: <out>/screen.webm, <out>/lead.txt (녹화 시작부터 첫 장면까지의 초 → make.py가 잘라낸다)
import { chromium } from 'playwright';
import { mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const [tlPath, outDir] = process.argv.slice(2);
const TL = JSON.parse(readFileSync(tlPath, 'utf8'));
mkdirSync(outDir, { recursive: true });
const W = TL.width, H = TL.height;

const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--hide-scrollbars'] });
const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1, recordVideo: { dir: outDir, size: { width: W, height: H } } });
const tRec = Date.now();
const page = await ctx.newPage();
await page.goto('file://' + resolve(TL.page) + '#sweep');
await page.waitForLoadState('load');
await page.waitForTimeout(1200);

// 헤드리스에는 마우스 포인터가 안 보이므로 가짜 포인터와 클릭 물결을 그린다
await page.addStyleTag({ content: `
  #__cur{position:fixed;left:0;top:0;width:28px;height:28px;z-index:2147483647;pointer-events:none;transition:transform .6s cubic-bezier(.3,.7,.2,1);filter:drop-shadow(0 2px 3px rgba(0,0,0,.6))}
  .__rip{position:fixed;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;border:3px solid #6aa8ff;z-index:2147483646;pointer-events:none;animation:__rip .6s ease-out forwards}
  @keyframes __rip{to{transform:scale(3.2);opacity:0}}` });
await page.evaluate(([w, h]) => {
  const c = document.createElement('div'); c.id = '__cur';
  c.innerHTML = '<svg viewBox="0 0 24 24" width="28" height="28"><path d="M5 2.5l14.5 8.6-6.6 1.5-3.6 6.4z" fill="#fff" stroke="#111" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
  c.style.transform = `translate(${w * 0.6}px,${h * 0.6}px)`;
}, [W, H]);

async function pointAt(sel) {
  const box = await page.locator(sel).first().boundingBox();
  if (!box) return null;
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  await page.evaluate(([x, y]) => { document.getElementById('__cur').style.transform = `translate(${x - 4}px,${y - 3}px)`; }, [x, y]);
  await page.waitForTimeout(650);
  return [x, y];
}
async function run(a) {
  if (a.do === 'tab') a = { do: 'click', sel: `.tabs button[data-tab="${a.name}"]` };
  if (a.do === 'click') {
    await page.locator(a.sel).first().scrollIntoViewIfNeeded();
    const p = await pointAt(a.sel);
    if (p) await page.evaluate(([x, y]) => { const r = document.createElement('div'); r.className = '__rip'; r.style.left = x + 'px'; r.style.top = y + 'px'; document.body.appendChild(r); setTimeout(() => r.remove(), 700); }, p);
    await page.locator(a.sel).first().click();
  } else if (a.do === 'point') {
    await pointAt(a.sel);
  } else if (a.do === 'scroll') {
    await page.evaluate(([s, block]) => document.querySelector(s)?.scrollIntoView({ behavior: 'smooth', block: block || 'start' }), [a.sel, a.block]);
  } else if (a.do === 'top') {
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  } else if (a.do === 'js') {
    await page.evaluate(a.js);
  }
}

const t0 = Date.now();
const lead = (t0 - tRec) / 1000;
for (const sc of TL.scenes) {
  for (const a of sc.actions || []) {
    const wait = (sc.start + a.at) * 1000 - (Date.now() - t0);
    if (wait > 0) await page.waitForTimeout(wait);
    try { await run(a); } catch (e) { console.log(`  ! ${sc.id}: ${a.do} ${a.sel || ''} ${String(e).slice(0, 120)}`); }
  }
  console.log(`[scene] ${sc.id} @${sc.start.toFixed(1)}s (${sc.dur.toFixed(1)}s)`);
}
const rest = TL.total * 1000 - (Date.now() - t0);
if (rest > 0) await page.waitForTimeout(rest);
await page.close();
await ctx.close();
await browser.close();
const webm = readdirSync(outDir).filter((f) => f.endsWith('.webm') && f !== 'screen.webm');
renameSync(join(outDir, webm[0]), join(outDir, 'screen.webm'));
writeFileSync(join(outDir, 'lead.txt'), String(lead));
console.log(`-> ${join(outDir, 'screen.webm')} (lead ${lead.toFixed(2)}s)`);
