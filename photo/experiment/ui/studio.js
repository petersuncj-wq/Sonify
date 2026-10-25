'use strict';
/* Sonify · Geometry Studio v0.5
 * Blueprint: the whole building is performed as one 5-instrument piece,
 *            revealed by a full-width left-to-right scan cursor.
 * Soul:      the full extracted geometry is classified into 5 tracks
 *            (curve / vertical / horizontal / loop / background) and every
 *            unit participates; sounded paths light up on the score.
 * Progressive: the same, introduced one class at a time.
 */
const $ = s => document.querySelector(s);
const canvas = $('#art'), ctx = canvas.getContext('2d');
let W = 900, H = 1050;

let data = null, mode = 'blueprint', selected = null, showLines = true;
let active = [true, true, true, true, true];
let ac, buffers = [], nodes = [], gains = [];
let playing = false, offset = 0, started = 0, token = 0, loading = false;

const bg = document.createElement('canvas'); bg.width = W; bg.height = H;
const bgx = bg.getContext('2d');
let idToPoints = new Map();
let soloVoice = null;
let beforeSolo = null;
let soulView = 'piano';
let progressivePreset='nature',progressiveColor='auto';
const progressiveAudioPrefix=()=> 'progressive'+(progressivePreset!=='nature'&&data.progressive_presets?.[progressivePreset]?'-'+progressivePreset:'')+(progressiveColor!=='auto'&&data.progressive_colors?.[progressivePreset]?.[progressiveColor]?'-color-'+progressiveColor:'');
let soulEdition='demo', spatialEnabled=true, panners=[], masterBus=null;
let soulUserVersion=null,soulUseUser=false;
const soulMusic=()=>soulUseUser&&soulUserVersion?soulUserVersion.music:soulEdition==='demo' && data.soul_demo ? data.soul_demo : data.soul;
const soulAudioPrefix=()=>soulUseUser&&soulUserVersion?soulUserVersion.audio_prefix:soulEdition==='demo' && data.soul_demo ? 'soul-demo' : 'soul';
let selectedStructure = null;
let notePinned=false;
let demo = null, demoTimer = null;
let sampleLoadToken=0,sampleLoading=false;
const REVISION = 'color52';
const audioCache = new Map();
/* ---- H2: on-demand Progressive rendering -------------------------------- */
/*
 * The initial build renders only the default Progressive combination
 * (`nature` / `auto`); every other combination is rendered by the server
 * when the visitor actually asks for it.  This keeps an upload's audio
 * footprint at roughly one fifth of the old fan-out.
 *
 * `progressiveRendered` mirrors the manifest's `rendered_variants` list.
 */
let progressiveRendered = new Set();
const progressiveKey = (preset, strength) => `${preset} ${strength}`;
const markRendered = (preset, strength) => progressiveRendered.add(progressiveKey(preset, strength));
const isRendered = (preset, strength) => progressiveRendered.has(progressiveKey(preset, strength));

function syncRenderedVariants(){
  progressiveRendered = new Set();
  const list = (data && data.rendered_variants) || [];
  for (const entry of list) {
    if (Array.isArray(entry) && entry.length >= 2) markRendered(entry[0], entry[1]);
  }
  // A workspace built before the on-demand renderer existed has every
  // combination rendered.
  if (!list.length && data && data.progressive_colors) {
    for (const [preset, versions] of Object.entries(data.progressive_colors))
      for (const strength of Object.keys(versions)) markRendered(preset, strength);
  }
}

/* The job id is needed to ask the server for a render.  It is embedded in
 * the manifest as `intake_job` for uploaded works. */
const jobId = () => (data && (data.intake_job || data.job_id)) || null;

async function requestProgressiveRender(preset, strength){
  const id = jobId();
  if (!id) return false;               // a standalone sample: nothing to ask
  if (isRendered(preset, strength)) return true;
  const url = `/api/jobs/${id}/progressive?preset=${encodeURIComponent(preset)}&strength=${encodeURIComponent(strength)}`;
  const response = await fetch(url);
  if (!response.ok) return false;
  markRendered(preset, strength);
  return true;
}

/* ---- catalog / helpers ------------------------------------------------- */
const catalog = () => (data && mode === 'soul' ? soulMusic().voice_catalog : data && mode==='progressive' ? musicObj().voice_catalog : data && data.voice_catalog) || [];
const colorOf = v => {
  if (mode === 'blueprint' && data && data.blueprint) {
    const b = (data.blueprint.voices || []).find(x => x.voice === v);
    if (b) return b.color;
  }
  return (catalog()[v] || {}).color || '#888';
};
const bpVoice = v => ((data.blueprint && data.blueprint.voices) || []).find(x => x.voice === v) || {};
const instrumentOf = v => (catalog()[v] || {}).instrument || '';
const nameOf = v => (catalog()[v] || {}).name_zh || '';
const musicObj = () => (mode === 'blueprint' ? data.blueprint : mode==='soul' ? soulMusic() : (data.progressive_colors?.[progressivePreset]?.[progressiveColor]||data.progressive_presets?.[progressivePreset]||data.progressive));
const duration = () => musicObj().duration;
const isSpatial = () => mode === 'blueprint';
const fmt = t => `${Math.floor(t / 60)}:${String(Math.floor(Math.max(0, t) % 60)).padStart(2, '0')}`;

/* Fit the source into the canvas; normalised coords -> pixels. */
let fit = { ox: 0, oy: 110, w: 880, h: 860 };
function computeFit() {
  const bw = W-20, bh = H-190, ar = data.width / data.height;
  let w = bw, h = w / ar;
  if (h > bh) { h = bh; w = h * ar; }
  fit = { ox: (W - w) / 2, oy: 118 + (bh - h) / 2, w, h };
}
const xy = q => [fit.ox + q[0] * fit.w, fit.oy + q[1] * fit.h];
const scanSpan = () => (mode === 'blueprint' ? 12.0 : duration());
const scanX = t => fit.ox + Math.max(0, Math.min(1, t / scanSpan())) * fit.w;

/* ---- playback (Web Audio, per-track gain) ------------------------------ */
function stems() {
  if (mode === 'blueprint') return [data.blueprint.audio];
  const m = mode === 'progressive' ? progressiveAudioPrefix() : soulAudioPrefix();
  return [0, 1, 2, 3, 4].map(v => `studio/${data.id}-${m}-${v}.wav`);
}
function trackCount() { return mode === 'blueprint' ? 1 : 5; }
function gainFor(i) { return mode === 'blueprint' ? .9 : mode === 'soul' ? [.38, .18, .25, .14, .12][i] : (musicObj().mix_gains?.[i]??.25)*(musicObj().mix_master_gain??1); }
function time() {
  return playing ? Math.min(duration(), offset + Math.max(0, ac.currentTime - started)) : offset;
}
function halt(reset) {
  token++;
  nodes.forEach(n => { try { n.stop(); } catch (e) {} });
  nodes = [];
  if (playing) offset = time();
  playing = false; loading = false;
  if (reset) offset = 0;
  $('#play').textContent = '播放作品';
  if(typeof updateRoleTracks==='function')updateRoleTracks();
}
async function play() {
  if (!data || sampleLoading) return;
  if (playing) { halt(); return; }
  if (loading) { halt(); return; }
  // H2: the selected Progressive combination may not have been rendered
  // yet.  Ask the server for it before trying to load the audio.
  if (mode === 'progressive') {
    const ready = await ensureProgressiveAudio();
    if (!ready) return;
  }
  selectedStructure=null;notePinned=false;
  if (offset >= duration()) offset = 0;
  const id = ++token; loading = true;
  $('#play').textContent = '取消加载';
  $('#status').textContent = '读取本地乐器音轨…';
  try {
    ac = ac || new (window.AudioContext || window.webkitAudioContext)();
    await ac.resume();
    const files = stems();
    const bs = await Promise.all(files.map(loadAudio));
    if (id !== token) return;
    buffers = bs; started = ac.currentTime + .08; gains = [];panners=[];
    if(!masterBus){masterBus=ac.createDynamicsCompressor();masterBus.threshold.value=-12;masterBus.knee.value=18;masterBus.ratio.value=2;masterBus.attack.value=.025;masterBus.release.value=.3;masterBus.connect(ac.destination);}
    nodes = bs.map((b, i) => {
      const n = ac.createBufferSource(), g = ac.createGain();
      n.buffer = b;
      if(mode==='soul'||(mode==='progressive'&&musicObj().mix_gains)){g.channelCount=1;g.channelCountMode='explicit';}
      g.gain.value = (active[i] !== false) ? gainFor(i) : 0;
      const pan=ac.createStereoPanner();
      pan.pan.value=mode==='soul'&&spatialEnabled ? [-.12,.32,-.08,-.3,.42][i] : mode==='progressive'?(musicObj().spatial_pan?.[i]??0):0;
      n.connect(g).connect(pan).connect(mode==='soul'?masterBus:ac.destination);panners.push(pan);
      gains.push(g); n.start(started, offset); return n;
    });
    playing = true; loading = false;
    if(mode==='soul'&&!listeningDialog.open)$('#soul-timeline').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth',block:'start'});
    $('#play').textContent = '暂停';
    $('#status').textContent = mode === 'blueprint'
      ? '整座建筑：' + data.blueprint.notes.toLocaleString() + ' 个音符，5 种乐器同时演奏。'
      : mode === 'soul' ? '几何动机 → 乐句 → 四乐章 · 真实乐器分轨播放' : '真实 GM 乐器 · 分轨播放 · 最多 6 音并发';
  } catch (e) {
    if (id === token) { halt(); $('#status').textContent = '播放失败：' + e.message; }
  }
}
function seek(t) { const r = playing; if(r)selectedStructure=null; halt(); offset = t; if (r) play(); draw(); }

/* ---- geometry drawing -------------------------------------------------- */
function pathTo(c, pts, ox, oy) {
  c.beginPath();
  for (let i = 0; i < pts.length; i++) {
    const [x, y] = xy(pts[i]);
    if (i) c.lineTo(x, y); else c.moveTo(x, y);
  }
}
function strokeUnit(c, pts, color, lw, alpha) {
  c.globalAlpha = alpha; c.strokeStyle = color; c.lineWidth = lw;
  c.lineJoin = 'round'; c.lineCap = 'round';
  pathTo(c, pts); c.stroke(); c.globalAlpha = 1;
}
function head(c, x, y, color, size) {
  c.save(); c.translate(x, y); c.rotate(-0.35); c.fillStyle = color;
  c.beginPath(); c.ellipse(0, 0, size * 1.5, size, 0, 0, Math.PI * 2); c.fill(); c.restore();
}

/* Static layer: rebuilt when mode / sample / line toggle changes. */
function buildStatic() {
  bgx.clearRect(0, 0, W, H);
  const light = mode !== 'progressive';
  bgx.fillStyle = light ? '#f4f1e6' : '#132624';
  bgx.fillRect(0, 0, W, H);

  // Header text
  bgx.fillStyle = light ? '#7a6a3f' : '#d9c78b';
  bgx.font = '11px "Segoe UI", sans-serif';
  bgx.fillText('SONIFY · ' + (mode === 'blueprint' ? 'BLUEPRINT DISPLAY' : mode === 'soul' ? 'SOUL SYMPHONY' : 'PROGRESSIVE REVELATION'), 40, 46);
  bgx.fillStyle = light ? '#34554e' : '#8fb0a4';
  bgx.font = 'italic 22px Georgia';
  bgx.fillText((data.name || '').replace(/\.(png|jpg)$/i, '') + ' · ' +
    (mode === 'blueprint' ? '整座建筑一次演奏' : mode === 'soul' ? '结构成为旋律' : '逐层显现'), 40, 74);

  if (mode === 'blueprint') {
    // faint staff lines for a "score" feel
    bgx.strokeStyle = light ? '#d8d3bf' : '#2a4642'; bgx.lineWidth = .6;
    for (let y = fit.oy; y < fit.oy + fit.h; y += 46) {
      bgx.beginPath(); bgx.moveTo(fit.ox, y); bgx.lineTo(fit.ox + fit.w, y); bgx.stroke();
    }
    // every drawn skeleton sample as a note head, coloured by instrument band
    for (const n of data.art) {
      const [x, y] = xy([n.x, n.y]);
      head(bgx, x, y, colorOf(n.band), 1.5);
    }
  } else {
    // full-coverage geometry: every classified unit, coloured by its track
    if (showLines) {
      for (const u of data.units) {
        const p = idToPoints.get(u.id);
        if (p) strokeUnit(bgx, p,
          mode === 'soul' ? '#5b6f66' : colorOf(u.voice),
          mode === 'soul' ? 1.1 : .8,
          mode === 'soul' ? .30 : (u.layer === 'subject' ? .5 : .28));
      }
    } else {
      for (const p of data.contours) strokeUnit(bgx, p.points, light ? '#9aa39a' : '#3c5a54', 1, .5);
    }
  }
  // figure border
  bgx.strokeStyle = light ? '#c9c2ad' : '#31504b'; bgx.lineWidth = 1;
  bgx.strokeRect(fit.ox, fit.oy, fit.w, fit.h);
}

function drawCursor(x, t) {
  const g = ctx.createLinearGradient(x - 26, 0, x + 3, 0);
  g.addColorStop(0, 'rgba(224,179,87,0)');
  g.addColorStop(1, 'rgba(224,179,87,.35)');
  ctx.fillStyle = g; ctx.fillRect(x - 26, fit.oy - 8, 29, fit.h + 16);
  ctx.strokeStyle = '#e0b357'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(x, fit.oy - 8); ctx.lineTo(x, fit.oy + fit.h + 8); ctx.stroke();
  ctx.fillStyle = '#e0b357';
  ctx.beginPath(); ctx.arc(x, fit.oy - 8, 4, 0, Math.PI * 2); ctx.fill();
}

function draw() {
  if (!data) return;
  if(mode==='progressive'){drawRevelation(time());return;}
  ctx.clearRect(0, 0, W, H);
  ctx.drawImage(bg, 0, 0);
  const t = time();
  const light = mode !== 'progressive';

  if (mode === 'blueprint') {
    // highlight the samples the cursor is sounding right now
    for (const n of data.art) {
      if (Math.abs(t - n.start) < 0.55) {
        const [x, y] = xy([n.x, n.y]);
        head(ctx, x, y, colorOf(n.band), 3.4);
      }
    }
    drawCursor(scanX(t), t);
  } else {
    const m = musicObj();
    if (mode === 'soul') {
      const structs = m.structures || [];
      const sounding = new Set();
      for (const n of m.notes) {
        if (active[n.voice] !== false && t >= n.start && t < n.start + n.duration) sounding.add(n.structure);
      }
      const focus = selectedStructure ? new Set([selectedStructure]) : sounding;
      ctx.save();
      for (const s of structs) {
        if (!focus.has(s.id)) continue;
        ctx.shadowColor = s.color; ctx.shadowBlur = 9;
        for (const id of s.geometry_ids) {
          const p = idToPoints.get(id);
          if (p) strokeUnit(ctx, p, s.color, 2.4, .95);
        }
      }
      ctx.restore();
      drawSoulTimeline(t);
      drawSourceCompanion(t);
    }
    const sound = m.notes.filter(n => active[n.voice] !== false &&
      t >= n.start && t < n.start + n.duration);
    {
      const seen = new Set();
      for (const n of sound) {
        if (seen.has(n.source)) continue; seen.add(n.source);
        const p = idToPoints.get(n.source);
        if (p) strokeUnit(ctx, p, colorOf(n.voice), 3, .95);
      }
    }
    // selected event path
    if (!playing && selected != null && m.notes[selected]) {
      const p = idToPoints.get(m.notes[selected].source);
      if (p) strokeUnit(ctx, p, '#d76b43', 2.6, 1);
    }
    if (mode !== 'soul') drawCursor(scanX(t), t);
  }

  // HUD footer
  ctx.fillStyle = light ? '#6b8175' : '#90aaa0';
  ctx.font = '11px "Segoe UI", sans-serif';
  const hint = mode === 'blueprint'
    ? `${data.blueprint.symbols.toLocaleString()} 骨架采样 · ${data.blueprint.notes.toLocaleString()} 实际音符 · 5 种乐器 · 从左到右扫描`
    : mode === 'soul' ? '空间结构始终可见 · 彩色区域对应当前乐句 · 亮线对应当前音符' : `${m_count()} 音符 · ${data.units.length.toLocaleString()} 几何单元参与 · 硬性并发上限 6`;
  ctx.fillText(hint, fit.ox, fit.oy + fit.h + 26);

  $('#clock').textContent = fmt(t) + ' / ' + fmt(duration());
  $('#seek').value = t;
  if (mode === 'progressive' || mode === 'soul') {
    $('#chapters').querySelectorAll('button').forEach((b, i) =>
      b.classList.toggle('active', t >= musicObj().phases[i].start && t < musicObj().phases[i].end));
  }
  if(typeof updateRoleTracks==='function'&&mode==='soul')updateRoleTracks();
  if (playing && t >= duration()) { halt(); offset=duration(); $('#status').textContent = '作品播放完成。'; }
}
function m_count() { return (musicObj().notes || []).length.toLocaleString(); }

/* ---- trace panel ------------------------------------------------------- */
function trace() {
  const box = $('#trace');
  if (mode === 'blueprint') {
    if (!selected) { box.innerHTML = '<p class="hint">点击谱面中的任意音符，查看它来自哪条线。</p>'; return; }
    const n = selected;
    const bv = bpVoice(n.band);
    $('#overlay').innerHTML = `<circle cx="${n.x * 100}" cy="${n.y * 100}" r="2" fill="#d76b43"/>`;
    box.innerHTML =
      `<section><b>01 · 来源单元 ${n.path}</b>骨架采样坐标 (${n.x.toFixed(3)}, ${n.y.toFixed(3)})</section>` +
      `<section><b>02 · 映射规则</b>x → 扫描时间 ${n.start.toFixed(2)}s<br>原始 MIDI ${n.raw_pitch} → 五声音阶量化 MIDI ${n.pitch}<br>声部：${bv.label || ('band ' + n.band)}</section>` +
      `<section><b>03 · 声音事件</b>${n.audible ? '实际进入音频与 MIDI' : '仅保留图形；并发预算筛除声音'}<br>${bv.instrument || ''} · MIDI ${n.pitch} · ${n.duration.toFixed(2)}s 时值<br>${data.blueprint.notes.toLocaleString()} / ${data.blueprint.candidate_notes.toLocaleString()} 个候选音符进入作品</section>`;
    return;
  }
  const m = musicObj();
  if (selected == null || !m.notes[selected]) { box.innerHTML = '<p class="hint">点击图形谱或选择事件，追溯一个音符的来源与公式。</p>'; return; }
  const n = m.notes[selected];
  const c = n.calculation || {};
  const unit = data.units.find(u => u.id === n.source) || {};
  const cu = xy(n.source_point || [0, 0]);
  $('#overlay').innerHTML = `<polyline points="${(idToPoints.get(n.source) || []).map(q => (q[0] * 100) + ',' + (q[1] * 100)).join(' ')}" fill="none" stroke="#d76b43" stroke-width="1.2"/>` +
    `<circle cx="${(n.source_point ? n.source_point[0] : 0) * 100}" cy="${(n.source_point ? n.source_point[1] : 0) * 100}" r="1.8" fill="#d76b43"/>`;
  if(mode==='progressive'&&c.arrangement){
    const roles={original_theme:'几何主题原形',theme_development:'主题发展',theme_reprise:'主题重现',octave_theme:'主题低八度加倍',answer_to_theme:'呼应旋律',voice_led_harmony:'共同音保持与就近和声连接',root_support:'和弦根音支撑',fifth_connection:'五度连接',dominant_cadence:'属和弦终止准备',tonic_resolution:'主和弦解决'};
    box.innerHTML=`<section><b>01 · 来源单元 ${n.source}</b>${unit.type||n.type} · 采样坐标 ${(n.source_point||[]).map(x=>x.toFixed(3)).join(', ')}</section><section><b>02 · 几何素材 → 编曲</b>${roles[c.arrangement]||c.arrangement}<br>来源素材 MIDI ${c.source_pitch} → ${c.chord} 和声与音区处理 → 实际 MIDI ${n.pitch}<br>保留原始来源事件 ${n.parent_note_id}</section><section><b>03 · 实际声音</b>${instrumentOf(n.voice)} · ${n.start.toFixed(2)}s 起音 · ${n.duration.toFixed(2)}s 时值</section>`;return;
  }
  const formula = c.method === 'local_contour' || c.method === 'motif_contour'
    ? 'd = 13(1 − 中心高度) + 4(中心高度 − y) / max(0.12, 高度跨度)'
    : 'd = 13 × (1 − y)';
  const phrase = (m.phrases || []).find(p => p.id === n.phrase);
  const group = (m.groups || []).find(g => g.id === n.group);
  box.innerHTML =
    (phrase ? `<section><b>结构组 → 动机 → 乐句 → 乐章</b>${group.label} · ${group.sources.length} 条路径组成结构组；代表路径 ${n.source} 产生动机<br>${phrase.motif} → ${phrase.transform} → ${phrase.section} 乐章${phrase.chord ? ' · 和弦 ' + phrase.chord : ''}<br>第 ${c.bar} 小节，第 ${c.beat + 1} 拍；声部音区偏移 ${c.support_shift} 级，变奏偏移 ${c.variation_shift} 级<br>最终音阶索引 ${c.final_index} → MIDI ${n.pitch}<br>路径长度参与时值缩放 × ${c.length_factor}；结尾音作主音收束</section>` : '') +
    `<section><b>01 · 来源单元 ${n.source}</b>几何类型：${unit.type || n.type}（${unit.layer || n.layer}）<br>弧长采样坐标 (${(n.source_point || []).map(x => x.toFixed(3)).join(', ')})<br>路径长度 ${unit.length || '—'} px</section>` +
    `<section><b>02 · 映射规则</b><code>${formula}</code><br>d = ${(c.raw_degree != null ? c.raw_degree.toFixed(2) : '—')} → 音阶索引 ${c.scale_index != null ? c.scale_index : '—'}${c.support_shift ? '（声部音区偏移 ' + c.support_shift + ' 级）' : ''}<br>音阶：C · D · E · G · A</section>` +
    `<section><b>03 · 声音事件</b>MIDI ${n.pitch} · ${instrumentOf(n.voice)}（${nameOf(n.voice)}）<br>${n.start.toFixed(2)}s 起音 · ${n.duration.toFixed(2)}s 时值</section>`;
}

/* ---- configure / load -------------------------------------------------- */
function eventOptions() {
  if (mode === 'blueprint') return '';
  const m = musicObj();
  return m.notes.map((n, i) =>
    `<option value="${i}">${String(i + 1).padStart(2, '0')} · ${nameOf(n.voice)} / ${n.source} → ${n.pitch}</option>`).join('');
}
function voiceControls() {
  const el = $('#voices');
  if (mode === 'blueprint') {
    el.innerHTML = data.blueprint.voices.map(v =>
      `<button disabled style="border-left:3px solid ${v.color}">${v.label}<span>${v.instrument} · ${v.notes.toLocaleString()}</span></button>`).join('');
    return;
  }
  const counts = {};
  (musicObj().notes || []).forEach(n => { counts[n.voice] = (counts[n.voice] || 0) + 1; });
  el.innerHTML = catalog().map(c =>
    `<button data-voice="${c.voice}" aria-pressed="${active[c.voice] !== false}" style="border-left:3px solid ${c.color}">${c.name_zh}<span>${c.instrument} · ${(counts[c.voice] || 0)}</span></button>`).join('');
}
function configure() {
  W=mode==='soul'?900:1100;H=mode==='soul'?1050:Math.max(480,Math.min(1450,Math.round(mode==='progressive'?(W-100)*data.height/data.width+110:(W-50)*data.height/data.width+190)));
  canvas.width=W;canvas.height=H;bg.width=W;bg.height=H;
  document.body.classList.remove('blueprint-focus');
  selectedStructure=null;notePinned=false;
  document.body.dataset.mode = mode;
  $('#soul-panel').hidden = mode !== 'soul';
  $('#soul-timeline').hidden = mode !== 'soul';
  $('#grammar-details').open = mode !== 'soul';
  if (mode === 'soul') {soulView='piano';document.querySelectorAll('.viewtabs button').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.view==='piano')));buildSoulPanel();}
  $('#event').innerHTML = eventOptions();
  selected = mode === 'blueprint'
    ? (data.art.find(n => n.audible) || data.art[0] || null)
    : (musicObj().notes.length ? 0 : null);
  if (mode !== 'blueprint' && selected != null) $('#event').value = String(selected);
  $('#seek').max = duration();
  $('#midi').href = `studio/${data.id}-${mode==='soul'?soulAudioPrefix():mode==='progressive'?progressiveAudioPrefix():mode}.mid`;
  $('#mix-download').hidden=mode!=='soul';
  $('#mix-download').href=`studio/${data.id}-${mode==='soul'?soulAudioPrefix():mode}-mix.wav`;
  document.querySelectorAll('[data-edition]').forEach(b=>b.setAttribute('aria-pressed',String(!soulUseUser&&b.dataset.edition===soulEdition)));
  $('#soul-edition').hidden=mode!=='soul';
  if(mode==='soul')$('#piece-length').textContent=`${soulMusic().bars||32} 小节 · ${soulUseUser?'我的角色编排':soulEdition==='demo'?'比赛演示版':'完整版'} · 四个乐章`;
  $('#json').href = `studio/${data.id}.json`;
  $('#eyebrow').textContent = ({blueprint: 'BLUEPRINT DISPLAY', soul: 'SOUL SYMPHONY', progressive: 'PROGRESSIVE REVELATION'})[mode] + ' / ' + data.name;
  $('#title').textContent = mode === 'blueprint' ? '整座建筑，一次性被演奏。'
    : mode === 'soul' ? '结构成为旋律，层次成为和声。' : '从空白中，看见一个世界诞生。';
  const meta = data.unit_meta || { by_type: {} };
  $('#caption').textContent = mode === 'blueprint'
    ? `${data.blueprint.symbols.toLocaleString()} 个骨架采样构成图形谱；${data.blueprint.candidate_notes.toLocaleString()} 个候选中，${data.blueprint.notes.toLocaleString()} 个音符进入声音。五种乐器按 x 从左到右扫描；点击符头可查看是否实际发声。`
    : `覆盖 ${data.units.length.toLocaleString()} 个几何单元：曲线 ${(meta.by_type.curve || 0)}、竖线 ${(meta.by_type.v_line || 0)}、横线 ${(meta.by_type.h_line || 0)}、闭环 ${(meta.by_type.loop || 0)}、斜线 ${(meta.by_type.d_line || 0)}。每类几何对应一种乐器/音轨，主体（前景）为主旋律，背景为伴衬。`;
  if (mode === 'soul') $('#caption').textContent = `全图保留 ${soulMusic().groups.length} 个空间结构组；其中 ${new Set(soulMusic().phrases.map(p=>p.group)).size} 组的代表路径构成当前作品。同组线条随乐句高亮，点击图像可追溯具体音符。`;
  $('#status').textContent = '可直接在页面播放；MIDI 用于继续编曲。';
  $('#limitations').textContent = '当前为规则驱动原型：几何单元来自阈值分类，尚无物体语义分割；图形谱不是传统可直接视奏的排版。' +
    (data.exclusions && data.exclusions.length ? '此样本含原有排除区域：空白来自输入处理，未自动补画。' : '输入纹理与缺失线条会影响几何提取。');
  $('#chapters').innerHTML = (musicObj().phases || []).map(p => `<button data-time="${p.start}">${p.label} · ${fmt(p.start)}</button>`).join('');
  voiceControls();
  prepareRevelation();
  buildStatic();
  draw();
  trace();
}
/* H2: make sure the selected Progressive combination actually has audio.
 * The initial build only renders `nature` / `auto`; the other
 * combinations are rendered by the server on demand.  The visitor sees a
 * short "generating" note while that happens. */
let progressiveAudioTicket = 0;
async function ensureProgressiveAudio(){
  if (mode !== 'progressive' || !data) return true;
  const preset = progressivePreset, strength = progressiveColor;
  if (isRendered(preset, strength)) return true;
  const versions = data.progressive_colors?.[preset];
  if (!versions || !versions[strength]) return false;   // not offered for this work
  const ticket = ++progressiveAudioTicket;
  const status = $('#status');
  const previous = status ? status.textContent : '';
  if (status) status.textContent = '正在生成这个风格的音乐…';
  try {
    const ok = await requestProgressiveRender(preset, strength);
    if (ticket !== progressiveAudioTicket) return ok;   // superseded
    if (ok) {
      if (status) status.textContent = previous || '音乐已准备好，可以播放。';
    } else if (status) {
      status.textContent = '这个风格暂时无法生成，请稍后再试。';
    }
    return ok;
  } catch (e) {
    if (status) status.textContent = '这个风格暂时无法生成，请稍后再试。';
    return false;
  }
}
async function load() {
  closeBirthGuide();
  halt(true);
  const request=++sampleLoadToken;sampleLoading=true;
  $('#play').disabled=true;$('#born').disabled=true;
  const id = $('#sample').value;
  $('#status').textContent = '读取作品…';
  try {
    const r = await fetch(`studio/${id}.json?v=${REVISION}`);
    if (!r.ok) throw new Error('作品数据不可用');
    const nextData = await r.json();
    if(request!==sampleLoadToken)return;
    soulUserVersion=null;soulUseUser=false;data=nextData;
    syncRenderedVariants();
    idToPoints = new Map(data.contours.map(p => [p.id, p.points]));
    computeFit();
    document.querySelector('.source').style.aspectRatio = data.width + '/' + data.height;
    $('#source').src = `${id}.jpg`;
    configure();
    sampleLoading=false;$('#play').disabled=false;$('#born').disabled=false;
  } catch (e) { if(request===sampleLoadToken)$('#status').textContent = e.message; }
}

/* ---- interaction ------------------------------------------------------- */
canvas.onclick = e => {
  if (!data || mode==='soul'||mode==='progressive') return;
  const box = canvas.getBoundingClientRect();
  const scale = Math.min(box.width / W, box.height / H);
  const x = (e.clientX - box.left - (box.width - W * scale) / 2) / scale;
  const y = (e.clientY - box.top - (box.height - H * scale) / 2) / scale;
  let best = Infinity, pick = null;
  if (mode === 'blueprint') {
    for (const n of data.art) {
      const [px, py] = xy([n.x, n.y]);
      const d = (px - x) * (px - x) + (py - y) * (py - y);
      if (d < best) { best = d; pick = n; }
    }
    selected = pick;
  } else {
    const m = musicObj();
    m.notes.forEach((n, i) => {
      const [px, py] = xy(n.source_point || [0, 0]);
      const d = (px - x) * (px - x) + (py - y) * (py - y);
      if (d < best) { best = d; selected = i; }
    });
    $('#event').value = String(selected);
    if (m.notes[selected]) selectedStructure = m.notes[selected].structure;
    if(mode==='soul'&&m.notes[selected]){halt();offset=m.notes[selected].start;notePinned=true;}
  }
  trace(); draw();
};

$('#play').onclick = play;
$('#stop').onclick = () => { halt(true); selectedStructure=null;notePinned=false;draw(); };
$('#seek').oninput = e => seek(Number(e.target.value));
$('#sample').onchange = load;
$('#event').onchange = e => { selected = Number(e.target.value); if(mode==='soul'){halt();selectedStructure=musicObj().notes[selected].structure;offset=musicObj().notes[selected].start;notePinned=true;} trace(); draw(); };
$('#lines').onclick = () => { showLines = !showLines; $('#lines').setAttribute('aria-pressed', showLines); $('#lines').textContent = '几何连线 ' + (showLines ? '✓' : '○'); buildStatic(); draw(); };
$('#chapters').onclick = e => { if (e.target.dataset.time !== undefined) seek(Number(e.target.dataset.time)); };
$('#voices').onclick = e => {
  const b = e.target.closest('button'); if (!b || b.disabled || !b.dataset.voice) return;
  const i = Number(b.dataset.voice);
  active[i] = active[i] === false;
  b.setAttribute('aria-pressed', active[i]);
  if (gains[i] && ac) gains[i].gain.setTargetAtTime(active[i] ? gainFor(i) : 0, ac.currentTime, .015);
  draw();
};
document.querySelectorAll('[role=tab]').forEach((b, i, bs) => {
  b.onclick = () => {
    closeBirthGuide();
    halt(true); mode = b.dataset.mode;
    bs.forEach(x => x.setAttribute('aria-selected', x === b));
    active = [true, true, true, true, true];
    soloVoice = null;
    beforeSolo = null;
    if (data) configure();
  };
});
document.querySelectorAll('.viewtabs button').forEach(b => {
  b.onclick = () => {
    soulView = b.dataset.view;
    document.querySelectorAll('.viewtabs button').forEach(x => x.setAttribute('aria-selected', x === b));
    draw();
  };
});

function buildSoulPanel() {
  $('#soul-story').textContent = '从原图的空间结构中提取动机，让主旋律、节奏、和声与背景彼此回应。';
  $('#soul-region').textContent = soulMusic().region_method;
  $('#structure-list').innerHTML = (soulMusic().structures || []).map(s =>
    `<button class="struct" data-struct="${s.id}" aria-pressed="${selectedStructure === s.id}" style="--c:${s.color}"><span class="dot"></span><b>${s.label}</b><em>${s.role}</em></button>`).join('');
  $('#soul-voices').innerHTML = catalog().map(v => `<div class="ensemble-row" data-row="${v.voice}" style="--voice:${v.color}"><div><strong>${v.name_zh}</strong><small>${v.instrument}</small><i></i></div><button data-solo="${v.voice}" aria-pressed="${soloVoice === v.voice}">独奏</button><button data-mute="${v.voice}" aria-pressed="${active[v.voice] === false}">静音</button></div>`).join('');
  if(typeof buildListeningChoices==='function')buildListeningChoices();
  if(typeof initRoleEditor==='function')initRoleEditor();
}
function runDemo() { startBirthGuide(); }
function drawSoulTimeline(t) {
  const pc=$('#piano'), width=Math.max(480,Math.min(1200,Math.round(pc.getBoundingClientRect().width*1.6)));
  if(pc.width!==width)pc.width=width;
  const phase=soulMusic().phases.find(p=>t>=p.start&&t<p.end)||soulMusic().phases.at(-1);
  $('#section-now').textContent=phase.label;$('#soul-story').textContent=phase.description;
  if (soulView === 'motif') return drawMotifView(t);
  if (soulView === 'staff') return drawStaffView(t);
  return drawPianoRoll(t);
}
const _LETTER = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6];
function _step(p) { const pc = ((p % 12) + 12) % 12; return (Math.floor(p / 12) - 1) * 7 + _LETTER[pc]; }
/* Staff: a treble staff for the melody (voice 0) and a bass staff for the bass
   (voice 2), engraved from the real note pitches/durations. */
function drawStaffView(t) {
  const m = soulMusic(), pc = $('#piano'), c = pc.getContext('2d');
  const W = pc.width, H = pc.height;
  c.fillStyle = '#0f2220'; c.fillRect(0, 0, W, H);
  const gut = 74, pad = 12, tw = W - gut - pad * 2, dur = m.duration, beat = 60 / 92, bar = beat * 4;
  const X = tt => gut + (tt / dur) * tw;
  const gap = 11, stepPx = gap / 2, yT = 74, yB = 312, topT = 38, topB = 26;
  const yOf = (p, top, y0) => y0 + (top - _step(p)) * stepPx;
  m.phases.forEach((ph, i) => {
    c.fillStyle = (t >= ph.start && t < ph.end) ? '#ffffff10' : '#ffffff04';
    c.fillRect(X(ph.start), 0, X(ph.end) - X(ph.start), H);
    c.fillStyle = '#9fb8ad'; c.font = '11px "Segoe UI"'; c.fillText(ph.label, X(ph.start) + 6, 15);
  });
  c.strokeStyle = '#ffffff10'; c.lineWidth = 1;
  for (let b = 0; b <= (m.bars || 32); b++) { const bx = X(b * bar); c.beginPath(); c.moveTo(bx, 0); c.lineTo(bx, H); c.stroke(); }
  function staff(yTop, clef) {
    c.strokeStyle = '#8fb0a4';
    for (let k = 0; k < 5; k++) { const y = yTop + k * gap; c.beginPath(); c.moveTo(gut - 22, y); c.lineTo(W - pad, y); c.stroke(); }
    c.fillStyle = '#d9c78b'; c.font = '26px "Segoe UI Symbol",serif'; c.fillText(clef, gut - 56, yTop + gap * 3 + 8);
  }
  staff(yT, '\u{1D11E}'); staff(yB, '\u{1D122}');
  function voiceNotes(v, top, y0) {
    for (const n of m.notes) {
      if (n.voice !== v) continue;
      const x = X(n.start), y = yOf(n.pitch, top, y0), step = _step(n.pitch);
      const color = colorOf(v);
      const sounding=playing&&t>=n.start&&t<n.start+n.duration;
      c.shadowColor=color;c.shadowBlur=sounding?12:0;
      c.globalAlpha = active[v] === false ? .15 : (sounding?1:.7); c.strokeStyle = color; c.fillStyle = color;
      // ledger lines above / below the staff
      if (step > top) for (let s = top + 2; s <= step; s += 2) { const ly = y0 + (top - s) * stepPx; c.beginPath(); c.moveTo(x - 6, ly); c.lineTo(x + 6, ly); c.stroke(); }
      if (step < top - 8) for (let s = top - 10; s >= step; s -= 2) { const ly = y0 + (top - s) * stepPx; c.beginPath(); c.moveTo(x - 6, ly); c.lineTo(x + 6, ly); c.stroke(); }
      const filled = n.duration < 2 * beat * 0.9;
      c.save(); c.translate(x, y); c.rotate(-0.34); c.beginPath(); c.ellipse(0, 0, 4.4, 3.1, 0, 0, Math.PI * 2);
      if (filled) c.fill(); else { c.lineWidth = 1.4; c.stroke(); }
      c.restore();
      const up = y > y0 + gap * 2;
      c.beginPath(); c.moveTo(x + (up ? 3.6 : -3.6), y); c.lineTo(x + (up ? 3.6 : -3.6), up ? y - 17 : y + 17); c.lineWidth = 1.3; c.stroke();
    }
    c.globalAlpha = 1; c.shadowBlur=0;
  }
  voiceNotes(0, topT, yT);
  voiceNotes(1, topT, yT);
  voiceNotes(2, topB, yB);
  voiceNotes(3, topB, yB);
  voiceNotes(4, topB, yB);
  c.fillStyle="#9fb8ad";c.font="12px Segoe UI";c.fillText("旋律 / 回应",8,40);c.fillText("低音 / 和声 / 氛围",8,280);c.fillText('4/4',28,65);c.fillText('4/4',28,300);
  const px = X(t); c.strokeStyle = '#e0b357'; c.lineWidth = 2;
  c.beginPath(); c.moveTo(px, 0); c.lineTo(px, H); c.stroke();
  const ph = m.phases.find(p => t >= p.start && t < p.end) || m.phases[m.phases.length - 1];
  $('#section-now').textContent = ph.label;
  $('#soul-story').textContent = ph.description;
}
/* Real multi-voice MIDI Piano Roll: pitch axis, bar lines, section bands,
   durations, playhead and per-note selection — rendered from the actual note
   data, not a waveform. */
function drawPianoRoll(t) {
  const m = soulMusic(), pc = $('#piano'), c = pc.getContext('2d');
  const W = pc.width, H = pc.height;
  c.clearRect(0, 0, W, H);
  const gut = 46, pad = 8, tw = W - gut - pad * 2;
  const notes = m.notes, dur = m.duration;
  if (!notes.length) return;
  const ps = notes.map(n => n.pitch);
  const lo = Math.min(...ps) - 1, hi = Math.max(...ps) + 1;
  const Y = p => H - 18 - ((p - lo) / (hi - lo)) * (H - 34);
  const X = tt => gut + pad + tt / dur * tw;
  // section bands + labels
  m.phases.forEach((ph, i) => {
    c.fillStyle = (t >= ph.start && t < ph.end) ? '#ffffff14' : (i % 2 ? '#ffffff06' : '#ffffff02');
    c.fillRect(X(ph.start), 0, X(ph.end) - X(ph.start), H);
    c.fillStyle = '#9fb8ad'; c.font = '19px "Segoe UI"';
    c.fillText(ph.label, X(ph.start) + 8, 16);
  });
  // bar lines
  const bar = (60 / 92) * 4;
  c.strokeStyle = '#ffffff12'; c.lineWidth = 1;
  for (let b = 0; b <= (m.bars || 32); b++) { const bx = X(b * bar); c.beginPath(); c.moveTo(bx, 0); c.lineTo(bx, H); c.stroke(); }
  // octave grid + C labels
  for (let p = Math.ceil(lo / 12) * 12; p <= hi; p += 12) {
    const yy = Y(p);
    c.strokeStyle = '#ffffff10'; c.beginPath(); c.moveTo(gut, yy); c.lineTo(W - pad, yy); c.stroke();
    c.fillStyle = '#7f9c92'; c.font = '16px monospace'; c.fillText('C' + (p / 12 - 1), 6, yy + 3);
  }
  // notes
  const focus = selectedStructure ? new Set([selectedStructure]) : null;
  const hero=heroPhraseAt(t);
  for (const n of notes) {
    const inFocus = mappingSelection ? mappingSelection.notes.includes(n) : (!focus || focus.has(n.structure));
    const sounding = (playing || !!auditionNode) && t >= n.start && t < n.start + n.duration;
    c.globalAlpha = active[n.voice] === false ? .1 : (inFocus ? (sounding || focus ? 1 : .78) : .12);
    c.shadowColor = colorOf(n.voice); c.shadowBlur = sounding ? 20 : 0;
    if(hero&&hero.notes.includes(n)&&!sounding)c.globalAlpha=Math.max(c.globalAlpha,n.start<=t?.95:.5);
    c.fillStyle = colorOf(n.voice);
    c.fillRect(X(n.start), Y(n.pitch) - (sounding?5:3.5), Math.max(3, n.duration / dur * tw), sounding?10:7);
  }
  c.globalAlpha = 1; c.shadowBlur = 0;
  if (!playing && selected != null && notes[selected]) {
    const n = notes[selected];
    c.strokeStyle = '#ffe9b0'; c.lineWidth = 2;
    c.strokeRect(X(n.start) - 1.5, Y(n.pitch) - 5.5, Math.max(4, n.duration / dur * tw) + 3, 11);
  }
  const px = X(t);
  c.strokeStyle = '#e0b357'; c.lineWidth = 2;
  c.beginPath(); c.moveTo(px, 0); c.lineTo(px, H); c.stroke();
  const ph = m.phases.find(p => t >= p.start && t < p.end) || m.phases[m.phases.length - 1];
  $('#section-now').textContent = ph.label;
  $('#soul-story').textContent = ph.description;
  document.querySelectorAll('.ensemble-row').forEach(row => row.classList.toggle('sounding',
    active[+row.dataset.row] !== false && m.notes.some(n => n.voice === +row.dataset.row && t >= n.start && t < n.start + n.duration)));
}
/* Motif Development: which geometry motif appears in which section, and how it
   is transformed (original / retrograde / sequence / development). */
function drawMotifView(t) { drawMotifJourney(t); }
$('#piano').onclick = e => {
  const pc = e.currentTarget, r = pc.getBoundingClientRect();
  const W = pc.width, H = pc.height;
  const x = (e.clientX - r.left) / r.width * W, y = (e.clientY - r.top) / r.height * H;
  if (soulView === 'motif') {
    const phases=soulMusic().phases; const col=Math.max(0,Math.min(phases.length-1,Math.floor(x/W*phases.length)));
    seek(phases[col].start); return;
  }
  const m = soulMusic(), gut = 46, pad = 8, tw = W - gut - pad * 2;
  const ps = m.notes.map(n => n.pitch); const lo = Math.min(...ps) - 1, hi = Math.max(...ps) + 1;
  const noteAt = i => ({ Y: H - 18 - ((m.notes[i].pitch - lo) / (hi - lo)) * (H - 34) });
  let best = Infinity, pick = null;
  m.notes.forEach((n, i) => {
    const nx = soulView==='staff' ? 74 + n.start/m.duration*(W-98) : gut + pad + n.start / m.duration * tw;

    const ny = soulView==='staff' ? (n.voice<=1 ? 74+(38-_step(n.pitch))*5.5 : 312+(26-_step(n.pitch))*5.5) : H - 18 - ((n.pitch - lo) / (hi - lo)) * (H - 34);
    if (x < nx - 4 || x > nx + n.duration / m.duration * tw + 4) return;
    const d = Math.abs(ny - y);
    if (d < best) { best = d; pick = i; }
  });
  if (pick != null && best < 10) { auditionMapping(pick); return; }
  seek(Math.max(0, Math.min(duration(), (x - gut - pad) / tw * duration())));
};
$('#soul-voices').onclick=e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.solo!==undefined){
    const v=+b.dataset.solo;
    if(soloVoice===v){soloVoice=null;active=beforeSolo||active.map(()=>true);beforeSolo=null;}
    else{if(soloVoice===null)beforeSolo=active.slice();soloVoice=v;active=active.map((_,i)=>i===v);}
  }else if(b.dataset.mute!==undefined){
    if(soloVoice!==null){active=beforeSolo||active.map(()=>true);beforeSolo=null;soloVoice=null;}
    const v=+b.dataset.mute;active[v]=!active[v];
  }
  gains.forEach((g,i)=>g.gain.setTargetAtTime(active[i]?gainFor(i):0,ac.currentTime,.015));
  buildSoulPanel();voiceControls();draw();
};
$('#structure-list').onclick = e => {
  const b = e.target.closest('button.struct'); if (!b) return;
  const id = b.dataset.struct;
  selectedStructure = (selectedStructure === id) ? null : id;
  notePinned=false;
  buildSoulPanel(); draw();
};
$('#born').onclick = runDemo;
function frame() { if (demo) renderBirthGuide(); if (playing) draw(); requestAnimationFrame(frame); }

fetch('studio/manifest.json?v=' + REVISION).then(r => r.json()).then(rows => {
  $('#sample').innerHTML = rows.map(r => `<option value="${r.id}">${r.name}</option>`).join('');
  $('#sample').value = 'sample5';
  load();
}).catch(e => { $('#status').textContent = '加载失败：' + e.message; });
frame();

const blueprintFocusButton=document.createElement('button');blueprintFocusButton.id='blueprint-focus';blueprintFocusButton.textContent='全屏展示';document.querySelector('.work-title').append(blueprintFocusButton);
function setBlueprintFocus(on){document.body.classList.toggle('blueprint-focus',on&&mode==='blueprint');blueprintFocusButton.textContent=document.body.classList.contains('blueprint-focus')?'退出全屏 · Esc':'全屏展示';}
blueprintFocusButton.onclick=()=>setBlueprintFocus(!document.body.classList.contains('blueprint-focus'));
window.addEventListener('message',e=>{if(e.origin!==location.origin||e.source!==parent||e.data?.type!=='sonify-exhibit-focus')return;const on=!!e.data.on;if(mode==='soul')setSoulFocus(on);else if(mode==='progressive')setRevealFocus(on);else setBlueprintFocus(on);});
document.addEventListener('keydown',e=>{if(e.key==='Escape')setBlueprintFocus(false);});

function fitExhibitionCanvas(){
 if(!document.body.classList.contains('blueprint-focus')&&!document.body.classList.contains('reveal-focus')){canvas.style.width='';canvas.style.height='';return;}
 const stage=canvas.parentElement,w=Math.min(stage.clientWidth,stage.clientHeight*W/H);canvas.style.width=Math.max(1,w)+'px';canvas.style.height=Math.max(1,w*H/W)+'px';
}
new ResizeObserver(fitExhibitionCanvas).observe(canvas.parentElement);
new MutationObserver(()=>requestAnimationFrame(fitExhibitionCanvas)).observe(document.body,{attributes:true,attributeFilter:['class','data-mode']});
