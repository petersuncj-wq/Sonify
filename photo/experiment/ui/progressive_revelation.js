 'use strict';
/* Geometry-only reveal planning: no object labels or fabricated paths. */
function makeRevealPlan(sample){
 const phases=sample.progressive.phases,dur=sample.progressive.duration;
 const boundary=[0,phases[1]?.start??dur/6,phases[3]?.start??dur/2,phases[4]?.start??dur*2/3,phases[5]?.start??dur*5/6];
 const units=new Map(sample.units.map(u=>[u.id,u]));
 const rows=sample.contours.filter(p=>p.points.length>1).map(p=>{
  const u=units.get(p.id)||{},pts=p.points;
  const x=pts.reduce((s,q)=>s+q[0],0)/pts.length,y=pts.reduce((s,q)=>s+q[1],0)/pts.length;
  const length=pts.slice(1).reduce((sum,q,i)=>sum+Math.hypot((q[0]-pts[i][0])*sample.width,(q[1]-pts[i][1])*sample.height),0);
  const central=1-Math.min(1,Math.abs(x-.5)*1.5);
  return {id:p.id,points:pts,x,y,length,type:u.type||'detail',layer:u.layer||'background',voice:u.voice??4,score:length*(.55+central*.45)*(u.layer==='subject'?1.35:1)};
 });
 const subjects=rows.filter(r=>r.layer==='subject');
 const ranked=(subjects.length?subjects:rows.slice()).sort((a,b)=>b.score-a.score||a.id.localeCompare(b.id));
 const themeSources=new Set((sample.progressive.theme||[]).map(n=>n.source));
 const hero=new Set(ranked.slice(0,Math.max(8,Math.ceil(ranked.length*.045))).map(r=>r.id));
 for(const id of themeSources)hero.add(id);
 const middle=new Set(ranked.slice(0,Math.max(20,Math.ceil(ranked.length*.52))).map(r=>r.id));
 const lengths=rows.map(r=>r.length).sort((a,b)=>a-b),median=lengths[Math.floor(lengths.length*.55)]||0;
 const groups=new Map(),scroll=sample.width/sample.height>2.4;
 for(const row of rows){
  const stage=hero.has(row.id)?0:middle.has(row.id)?1:row.length>=median?2:3;
  // Spatial neighbours with the same geometric family form coherent growing patches.
  const cellX=Math.min(7,Math.floor(row.x*8)),cellY=Math.min(7,Math.floor(row.y*8));
  const key=`${stage}-${cellX}-${cellY}-${row.voice}`;
  if(!groups.has(key))groups.set(key,{stage,cx:cellX,cy:cellY,rows:[]});groups.get(key).rows.push(row);
 }
 const entries=[];
 for(let stage=0;stage<4;stage++){
  const pending=[...groups.values()].filter(g=>g.stage===stage),ordered=[];
  let previous=null;
  while(pending.length){
   pending.sort((a,b)=>{
    if(stage===0&&!scroll){const aa=a.rows.some(r=>themeSources.has(r.id)),bb=b.rows.some(r=>themeSources.has(r.id));if(aa!==bb)return Number(bb)-Number(aa);}
    if(scroll)return b.cx-a.cx||a.cy-b.cy;
    if(!previous)return Math.max(...b.rows.map(r=>r.score))-Math.max(...a.rows.map(r=>r.score));
    return Math.hypot(a.cx-previous.cx,a.cy-previous.cy)-Math.hypot(b.cx-previous.cx,b.cy-previous.cy)||a.cy-b.cy||a.cx-b.cx;
   });previous=pending.shift();ordered.push(previous);
  }
  const begin=boundary[stage]+(stage===0?.55:.1),end=boundary[stage+1]-.2;
  ordered.forEach((g,i)=>{
   g.rows.sort((a,b)=>b.score-a.score||a.id.localeCompare(b.id));
   const groupStart=begin+(end-begin-.65)*i/Math.max(1,ordered.length-1);
   g.rows.forEach((r,j)=>{
    const start=groupStart+.3*j/Math.max(1,g.rows.length-1),finish=Math.min(end,start+.35+Math.min(.45,r.length/700));
    entries.push({...r,revealStage:stage,revealGroup:`${stage}-${g.cx}-${g.cy}-${r.voice}`,start,end:Math.max(start+.06,finish)});
   });
  });
 }
 return {entries:entries.sort((a,b)=>a.start-b.start||a.id.localeCompare(b.id)),boundary,duration:dur,scroll,groups:groups.size};
}
let revealPlan=null,revealData=null,revealLayer=null,revealContext=null,revealDone=0,revealLast=-1,revealSorted=[],revealFocus=false;
let revealPhoto=null,revealPhotoKey='';
const revealNames=['显著轮廓','主体结构','空间层次','完整细节'];
const revealEnglish=['PRIMARY CONTOUR','CORE STRUCTURE','SPATIAL LAYERS','IDENTITY & DETAIL'];
const revealInk=['#e8c883','#8fc4bc','#a8bc90','#c5b6d1'];
function prepareRevelation(){
 $('#reveal-intro').hidden=mode!=='progressive';$('#reveal-info').hidden=mode!=='progressive';
 if(mode!=='progressive'){setRevealFocus(false);return;}
 if(revealData!==data){revealData=data;revealPlan=makeRevealPlan(data);}
 revealLayer=document.createElement('canvas');revealLayer.width=W;revealLayer.height=H;revealContext=revealLayer.getContext('2d');
 revealDone=0;revealLast=-1;revealSorted=revealPlan.entries.slice().sort((a,b)=>a.end-b.end);
 const photoKey=data.id+'-'+(data.original_photo?.url||'');
 if(photoKey!==revealPhotoKey){revealPhotoKey=photoKey;revealPhoto=null;if(data.original_photo){const sample=data,img=new Image();img.onload=()=>{if(data===sample&&mode==='progressive')draw();};img.src=data.original_photo.url+'?v='+REVISION;revealPhoto=img;}}
 if(!data.progressive_presets?.[progressivePreset])progressivePreset='nature';
 $('#reveal-style').value=progressivePreset;$('#reveal-style').disabled=!data.progressive_presets;
 const hasColor=!!data.color_dna?.available&&!!data.progressive_colors?.[progressivePreset]?.off;
 if($('#season-open')){$('#season-open').disabled=!data.living_color?.states?.length;$('#season-open').title=$('#season-open').disabled?'需要彩色原图及已生成的四时音乐':'';}
 if($('#color-proof-open'))$('#color-proof-open').disabled=!hasColor;
 if(!hasColor)progressiveColor='auto';
 const strength=['off','soft','mid','auto','vivid'].indexOf(progressiveColor)*25;
 $('#color-strength').value=Math.max(0,strength);$('#color-strength-value').textContent=Math.max(0,strength)+'%';$('#color-strength').disabled=!hasColor;
 const roles={warm:'暖色 → 中音和声',cool:'冷色 → 高音回应',dark:'暗部 → 低音支撑'};
 $('#color-palette').innerHTML=hasColor?(data.color_dna.regions||[]).map(r=>`<span data-color-role="${r.role}" title="暗部可与冷暖色层重叠；主色按面积、色度与画面位置估计"><i style="background:${r.hex}"></i>${r.hierarchy==='primary'?'主色 · ':''}${roles[r.role]} ${Math.round(r.coverage*100)}%</span>`).join(''):'';
 $('#reveal-color').value=progressiveColor;$('#reveal-color').disabled=!hasColor;
 $('#reveal-color-summary').textContent=hasColor?colorMusicExplanation(musicObj()):'COLOR DNA · '+(data.color_dna?'色彩信息不足，保持几何编曲':'未提供已核实的彩色原图，保持几何编曲');
 $('#grammar-details').open=false;document.body.classList.remove('reveal-details');
 $('#reveal-stages').innerHTML=revealNames.map((name,i)=>`<button data-reveal-time="${revealPlan.boundary[i]}" aria-pressed="${i===0}"><small>0${i+1}</small>${name}<i></i></button>`).join('');
 $('#reveal-caption').textContent=revealPlan.scroll?'宽幅作品 · 从右向左展开':'从整体轮廓到细部纹理 · 基于几何显著性与相邻关系展开';
 $('#reveal-explore').hidden=true;
}
function revealFit(){const ar=data.width/data.height;let w=W-100,h=w/ar;if(h>H-110){h=H-110;w=h*ar;}return {ox:(W-w)/2,oy:(H-h)/2,w,h};}
function paintReveal(c,row,progress=1,glow=false){
 const f=revealFit(),pts=progress<1?traceFraction(row.points,progress):row.points;if(pts.length<2)return;
 c.strokeStyle=glow?'#fff1bf':revealInk[row.revealStage];c.lineWidth=glow?2.1:1.15;c.globalAlpha=glow?1:.88;c.lineCap='round';c.lineJoin='round';
 c.shadowColor=revealInk[row.revealStage];c.shadowBlur=glow?9:0;c.beginPath();pts.forEach((q,i)=>i?c.lineTo(f.ox+q[0]*f.w,f.oy+q[1]*f.h):c.moveTo(f.ox+q[0]*f.w,f.oy+q[1]*f.h));c.stroke();c.shadowBlur=0;c.globalAlpha=1;
 if(glow){const q=pts.at(-1);c.fillStyle='#fff0bb';c.beginPath();c.arc(f.ox+q[0]*f.w,f.oy+q[1]*f.h,2.1,0,Math.PI*2);c.fill();}
}
function drawRevelation(t){
 if(!revealPlan||revealData!==data)prepareRevelation();
 const plan=revealPlan,complete=t>=plan.boundary[4],reduced=matchMedia('(prefers-reduced-motion:reduce)').matches;
 if(t<revealLast){revealContext.clearRect(0,0,W,H);revealDone=0;}
 while(revealDone<revealSorted.length&&revealSorted[revealDone].end<=t){paintReveal(revealContext,revealSorted[revealDone]);revealDone++;}
 revealLast=t;
 ctx.fillStyle='#081715';ctx.fillRect(0,0,W,H);
 if(t>0){const glow=ctx.createRadialGradient(W/2,H/2,20,W/2,H/2,W*.6);glow.addColorStop(0,'#20352b');glow.addColorStop(1,'#081715');ctx.fillStyle=glow;ctx.fillRect(0,0,W,H);}
 ctx.drawImage(revealLayer,0,0);
 for(const row of plan.entries){if(row.start>t)break;if(row.end<=t)continue;
  const progress=reduced?1:(t-row.start)/(row.end-row.start);paintReveal(ctx,row,progress,true);
 }
 // Source-note accents never reveal geometry ahead of its own scheduled birth.
 const sound=musicObj().notes.filter(n=>active[n.voice]!==false&&t>=n.start&&t<n.start+n.duration);
 const sounding=new Set(sound.map(n=>n.source));
 for(const row of plan.entries)if(sounding.has(row.id)&&row.end<t)paintReveal(ctx,row,1,true);
 const stage=Math.max(0,Math.min(3,plan.boundary.findIndex((b,i)=>i>0&&t<b)-1));
 const index=complete?3:stage;
 $('#reveal-stages').querySelectorAll('button').forEach((b,i)=>{b.setAttribute('aria-pressed',String(i===index));b.classList.toggle('revealed',t>=plan.boundary[i+1]);b.style.setProperty('--progress',`${Math.max(0,Math.min(1,(t-plan.boundary[i])/(plan.boundary[i+1]-plan.boundary[i])))*100}%`);});
 const emotion=musicObj().emotions?.find(e=>t>=e.start&&t<e.end);
 const musicEvent={anticipation:'氛围铺底 · 轮廓主题初现',emergence:'主轮廓 → 主题旋律',expansion:'层次扩展 → 低音与和声',revelation:'完整揭示 → 全声部高潮',resolution:'色彩回归 → 终止收束'};
 const coverage=Math.round(100*revealDone/Math.max(1,plan.entries.length));
 $('#reveal-caption').textContent=complete?'完整显现 · 每一条线，汇成同一个世界':`0${index+1} · ${revealEnglish[index]} — ${revealNames[index]} · ${coverage}% 已显现${emotion?' · '+emotion.label+'（'+(musicEvent[emotion.id]||'')+'）':''}`;
 const photo=data.original_photo;
 if(photo&&revealPhoto?.complete&&revealPhoto.naturalWidth&&t>photo.reveal_start){
  const amount=Math.min(1,(t-photo.reveal_start)/(photo.reveal_end-photo.reveal_start)),f=revealFit();
  let w=f.w,h=w*revealPhoto.naturalHeight/revealPhoto.naturalWidth;if(h>f.h){h=f.h;w=h*revealPhoto.naturalWidth/revealPhoto.naturalHeight;}
  ctx.globalAlpha=amount;ctx.drawImage(revealPhoto,f.ox+(f.w-w)/2,f.oy+(f.h-h)/2,w,h);ctx.globalAlpha=1;
  if(amount===1)$('#reveal-caption').textContent=(photo.relationship==='colorized_from_lineart'?'色彩回归 · 主题归一':'原始场景回归 · 主题归一');
 }
 if(complete){
  const u=Math.min(1,(t-plan.boundary[4])/.7);ctx.fillStyle=`rgba(244,231,190,${.09*Math.sin(u*Math.PI)})`;ctx.fillRect(0,0,W,H);
  ctx.fillStyle='#e9dcaf';ctx.textAlign='center';ctx.font='16px Georgia';ctx.fillText('FROM GEOMETRY → MUSIC',W/2,H-22);ctx.textAlign='left';
 }
 drawRevealNotes(t);
 $('#clock').textContent=fmt(t)+' / '+fmt(duration());$('#seek').value=t;
 $('#reveal-explore').hidden=t<plan.duration-.01;
 if(playing&&t>=duration()){halt();offset=duration();$('#status').textContent='完整作品已显现。';}
}
function setRevealFocus(on){revealFocus=on&&mode==='progressive';document.body.classList.toggle('reveal-focus',revealFocus);$('#reveal-focus').textContent=revealFocus?'退出展演 · Esc':'放大展演';$('#reveal-focus').setAttribute('aria-pressed',String(revealFocus));}
$('#reveal-start').onclick=()=>{halt(true);selected=null;draw();play();};
$('#reveal-focus').onclick=()=>setRevealFocus(!revealFocus);
$('#reveal-stages').onclick=e=>{const b=e.target.closest('[data-reveal-time]');if(b)seek(Number(b.dataset.revealTime));};
$('#reveal-explore').onclick=()=>{if(revealFocus)setRevealFocus(false);$('#grammar-details').open=!$('#grammar-details').open;document.body.classList.toggle('reveal-details',$('#grammar-details').open);if($('#grammar-details').open)$('#grammar-details').scrollIntoView({behavior:'smooth',block:'start'});};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&revealFocus)setRevealFocus(false);});

$('#reveal-style').onchange=e=>{const resume=playing||loading;halt(true);progressivePreset=e.target.value;configure();ensureProgressiveAudio();if(resume)play();};

function drawRevealNotes(t){
 const c=$('#reveal-notes'),g=c.getContext('2d'),m=musicObj(),w=c.width,h=c.height;
 g.clearRect(0,0,w,h);g.fillStyle='#102622';g.fillRect(0,0,w,h);
 const colors=['#e8c883','#8fc4bc','#a8bc90','#c5b6d1','#c68d77'];
 for(const boundary of [0,6,18,24,30,36]){g.strokeStyle='#29443b';g.beginPath();g.moveTo(boundary/36*w,0);g.lineTo(boundary/36*w,h);g.stroke();}
 for(const n of m.notes){const on=t>=n.start&&t<n.start+n.duration;g.globalAlpha=on?1:.58;g.fillStyle=colors[n.voice];g.shadowBlur=on?9:0;g.shadowColor=colors[n.voice];g.fillRect(n.start/36*w,h-9-(n.pitch-36)/52*(h-18),Math.max(3,n.duration/36*w),on?6:4);}
 g.globalAlpha=1;g.shadowBlur=0;g.fillStyle='#fff0b9';g.fillRect(t/36*w,0,2,h);
 const dna=m.arrangement_params||{},sounding=m.notes.filter(n=>t>=n.start&&t<n.start+n.duration),lead=sounding.find(n=>n.voice===0);
 const colorRoles=new Set((m.arrangement_params?.color_expression?.amount?sounding:[]).map(n=>n.arrangement_role==='color_cool_response'?'cool':n.arrangement_role==='color_warm_response'?'warm':n.voice===2?'dark':null));
 $('#color-palette').querySelectorAll('[data-color-role]').forEach(el=>el.classList.toggle('sounding',playing&&colorRoles.has(el.dataset.colorRole)));
 $('#reveal-music-event').textContent=(lead?'轮廓主题 · '+(lead.arrangement_role==='theme_reprise'?'主题回归':lead.arrangement_role==='theme_development'?'主题发展':'几何旋律'):'层次呼吸 · 和声与空间')+'　'+(m.preset_name||'')+' · '+(dna.theme_count||4)+' 音主题 · '+sounding.length+(playing?' 个音正在发声':' 个当前音符');
}
$('#reveal-notes').onclick=e=>{const r=e.currentTarget.getBoundingClientRect();seek(Math.max(0,Math.min(35.8,(e.clientX-r.left)/r.width*36)));};

// Major-source selection is intentionally phrase-level, rather than an invisible tiny-pixel hit.
canvas.addEventListener('click',e=>{
 if(mode!=='progressive'||!revealPlan)return;
 const r=canvas.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*W,y=(e.clientY-r.top)/r.height*H,f=revealFit();
 const m=musicObj(),ids=new Set((m.theme||[]).map(n=>n.source));let hit=null,best=32;
 for(const row of revealPlan.entries){if(!ids.has(row.id))continue;
  for(let i=1;i<row.points.length;i++){const a=row.points[i-1],b=row.points[i],ax=f.ox+a[0]*f.w,ay=f.oy+a[1]*f.h,dx=(b[0]-a[0])*f.w,dy=(b[1]-a[1])*f.h,u=Math.max(0,Math.min(1,((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy||1))),d=Math.hypot(x-ax-u*dx,y-ay-u*dy);if(d<best){best=d;hit=row.id;}}
 }
 if(hit){const n=m.notes.find(n=>n.voice===0&&n.source===hit);if(n){seek(n.start);$('#status').textContent='已定位主轮廓主题，点击播放可听对应乐句。';}}
});

$('#reveal-color').onchange=e=>{const resume=playing||loading;halt();progressiveColor=e.target.value;configure();ensureProgressiveAudio();if(resume)play();};

const colorControl=document.createElement('label');colorControl.className='color-strength-control';colorControl.innerHTML='色彩影响 <output id="color-strength-value">75%</output><input id="color-strength" type="range" min="0" max="100" step="25" value="75" aria-label="色彩影响程度百分比" title="0、25、50、75、100% 五档，松开后应用">';$('#reveal-color').parentElement.after(colorControl);
$('#color-strength').oninput=e=>{$('#color-strength-value').textContent=e.target.value+'%';const level=['off','soft','mid','auto','vivid'][Number(e.target.value)/25],target=data.progressive_colors?.[progressivePreset]?.[level];if(target)$('#reveal-color-summary').textContent='松手后应用 → '+colorMusicExplanation(target);};
$('#color-strength').onchange=e=>{const versions=data.progressive_colors?.[progressivePreset]||{},level=['off','soft','mid','auto','vivid'][Number(e.target.value)/25];if(!versions[level]){e.target.value=['off','soft','mid','auto','vivid'].indexOf(progressiveColor)*25;$('#color-strength-value').textContent=e.target.value+'%';$('#status').textContent='此旧作品尚未生成该色彩强度，请更新作品音乐。';return;}const resume=playing||loading;halt();progressiveColor=level;configure();ensureProgressiveAudio();if(resume)play();};
const palettePanel=document.createElement('div');palettePanel.id='color-palette';$('#reveal-color-summary').after(palettePanel);

const evidenceLink=document.createElement('a');evidenceLink.href=location.pathname.includes('/works/')?'/showcase/color-evidence.html':'color-evidence.html';evidenceLink.target='_blank';evidenceLink.rel='noopener';evidenceLink.textContent='色彩 A/B 与量化验收 ↗';evidenceLink.className='color-evidence-link';evidenceLink.title='暗部可与冷暖色层重叠；面积统计不要求相加为100%';$('#color-palette').after(evidenceLink);

// The colour proof uses the selected work's real statistics and rendered stems.
const colorProofButton=document.createElement('button');colorProofButton.id='color-proof-open';colorProofButton.textContent='看见色彩如何改变音乐 ↗';evidenceLink.before(colorProofButton);
const colorProof=document.createElement('dialog');colorProof.id='color-proof';colorProof.innerHTML=`<header><div><small>COLOR DNA · 从原图到真实声音</small><h2>颜色，也有自己的音乐语法。</h2></div><button id="color-proof-close" aria-label="关闭色彩映射">关闭 · Esc</button></header><nav id="color-proof-tabs"></nav><div class="color-proof-chain"><section><small>01 · 原图取色</small><div id="color-proof-photo"><img alt="当前作品的彩色原图"><i></i></div><p id="color-proof-origin"></p></section><b class="color-proof-arrow">→</b><section><small>02 · 可复核的创作规则</small><h3 id="color-proof-title"></h3><div id="color-proof-facts"></div><p id="color-proof-rule"></p></section><b class="color-proof-arrow">→</b><section><small>03 · 实际进入作品的音符</small><h3 id="color-proof-voice"></h3><div id="color-proof-score"></div><p id="color-proof-midi"></p><audio id="color-proof-audio" controls preload="metadata"></audio><div id="color-proof-ab"><button data-color-ab="off">听：仅几何</button><button data-color-ab="current">听：当前色彩</button></div><p id="color-proof-caption"></p></section></div><footer>几何决定轮廓动机；色彩重新诠释调式、中心音、音区与呼吸。这里是透明的创作约定，不是天气识别或色彩心理学定律。冷暖区域与暗部允许重叠。</footer>`;document.body.append(colorProof);
let colorProofRole='overall',colorProofEnd=36,colorProofTicket=0,colorProofBlob=null;
const colorProofAudio=$('#color-proof-audio');
let proofContext,proofGain;
function ensureProofAudio(){
 if(!proofContext){proofContext=new (window.AudioContext||window.webkitAudioContext)();proofGain=proofContext.createGain();proofContext.createMediaElementSource(colorProofAudio).connect(proofGain);proofGain.connect(proofContext.destination);}
 proofContext.resume();
}
const colorPitchNames=['C','C♯','D','E♭','E','F','F♯','G','A♭','A','B♭','B'];
function colorMusicExplanation(m){
 const e=m.arrangement_params?.color_expression||{},baseline=data.progressive_colors?.[progressivePreset]?.off;
 const key=music=>colorPitchNames[music.key_pc]+(music.arrangement_params?.color_expression?.mode==='minor'?' 小调':' 大调');
 if(!e.amount)return `听见几何 · ${key(m)} · 色彩尚未参与编曲`;
 const instruments=m.voice_catalog.filter((v,i)=>m.notes.some(n=>n.voice===i)).map(v=>v.instrument).filter((v,i,a)=>a.indexOf(v)===i).join(' / ');
 return `色彩 ${Math.round(e.amount*100)}% · ${baseline?key(baseline)+' → ':''}${key(m)} · 主题音区 ${Math.min(...m.theme.map(n=>n.pitch))}–${Math.max(...m.theme.map(n=>n.pitch))} · 短句间隔 ×${e.rhythm_spread.toFixed(2)} · ${instruments}。保留几何取样；五档松手后切换，音乐风格保持「${m.preset_name}」。`;
}
function renderColorProof(ab='current',autoplay=false){
 const m=ab==='off'?data.progressive_colors?.[progressivePreset]?.off:musicObj(),c=data.color_dna;
 if(!m||!c?.available||!data.original_photo){$('#status').textContent='需要彩色原图和已生成的色彩版本。';return false;}
 const ex=m.arrangement_params?.color_expression||{},amount=ex.amount||0,region=c.regions?.find(r=>r.role===colorProofRole),roles={overall:'整体情绪',warm:'暖色层',cool:'冷色层',dark:'暗部支撑'};
 $('#color-proof-tabs').innerHTML=Object.entries(roles).map(([id,label])=>`<button data-proof-role="${id}" aria-pressed="${id===colorProofRole}">${label}</button>`).join('');
 const photo=$('#color-proof-photo img');photo.src=data.original_photo.url;
 const pin=$('#color-proof-photo i');pin.hidden=!region||!region.coverage;const point=region?.sample_point||region?.centroid;
 if(point){pin.style.left=point[0]*100+'%';pin.style.top=point[1]*100+'%';pin.style.setProperty('--sample',region.sample_hex||region.hex);}
 $('#color-proof-origin').textContent=region?`${region.hierarchy==='primary'?'主色':region.hierarchy==='foundation'?'明暗基础':'辅色'} · 面积 ${Math.round(region.coverage*100)}% · 取色 ${region.sample_hex||region.hex}`:'使用当前作品的原始彩照；整体明度、饱和度与冷暖共同决定表达。';
 $('#color-proof-title').textContent=amount?ex.profile_label:'仅几何 · 色彩影响 0%';
 const fact=(label,value)=>`<div><span>${label}</span><strong>${value}</strong></div>`;
 $('#color-proof-facts').innerHTML=fact('明度 L*',c.lab?.L_mean??'—')+fact('饱和度',Math.round(c.saturation*100)+'%')+fact('表达能量 E',ex.energy??'—')+fact('中心音 / 调式',colorPitchNames[m.key_pc]+' / '+(ex.mode==='minor'?'小调':'大调'));
 $('#color-proof-rule').textContent=!amount?'色彩规则已关闭。此版本保留原始几何编曲。':colorProofRole==='overall'?`E = 0.48×L*/100 + 0.37×饱和度 + 0.15×(暖度+1)/2。E < 0.43，或暖度 < −0.25 且 L* < 62 → 沉静；其余 → 明朗。强度 ≥50% 时选择调式。当前移调 ${ex.key_shift>0?'+':''}${ex.key_shift} 半音，主题呼吸 ×${ex.rhythm_spread.toFixed(2)}。`:colorProofRole==='warm'?'暖色占比 → 中音区呼应与声部音量；同一几何动机在和声内重新发声。':colorProofRole==='cool'?'冷色占比 → 较高音区回应与声部音量；冷暖按原图上下关系交替。':'暗部占比 → 低音进入时刻、音区与支撑音量；并不把黑色固定解释为悲伤。';
 let selectedNotes=m.notes.filter(n=>colorProofRole==='overall'?n.voice===0:colorProofRole==='dark'?n.voice===2:n.arrangement_role===`color_${colorProofRole}_response`);
 const first=selectedNotes[0],start=first?Math.max(0,first.start-.15):0;
 if(region){
  $('#color-proof-facts').innerHTML+=fact(region.role==='dark'?'暗部面积':'色彩质量占比',Math.round((region.role==='dark'?c.dark_share:c[region.role+'_share'])*100)+'%');
  if(first)$('#color-proof-facts').innerHTML+=fact('实际分轨增益',m.mix_gains[first.voice].toFixed(3))+fact('首个事件',first.start.toFixed(2)+' s');
 }
 selectedNotes=selectedNotes.filter(n=>n.start<start+4.8).slice(0,8);colorProofEnd=Math.min(36,start+5.2);
 const voice=colorProofRole==='overall'?null:first?.voice,cat=m.voice_catalog.find(v=>(v.id??v.voice_id)===voice)||m.voice_catalog[voice];
 $('#color-proof-voice').textContent=voice===null?'主旋律 · 完整混音对照':selectedNotes.length?`${cat?.name_zh||roles[colorProofRole]} · ${cat?.instrument||'实际声部'}`:'当前编排没有该层事件';
 const min=Math.min(...selectedNotes.map(n=>n.pitch),48),max=Math.max(...selectedNotes.map(n=>n.pitch),84);
 $('#color-proof-score').innerHTML=selectedNotes.map(n=>`<i data-note-start="${n.start}" data-note-end="${n.start+n.duration}" style="left:${(n.start-start)/5.2*100}%;top:${15+(max-n.pitch)/Math.max(12,max-min)*60}%;width:${Math.max(4,n.duration/5.2*100)}%"><span>${n.pitch}</span></i>`).join('');
 $('#color-proof-midi').textContent=selectedNotes.length?'实际 MIDI：'+selectedNotes.map(n=>n.pitch).join(' · '):'该版本没有此类音符，请选择整体情绪或其他色层。';
 if(!selectedNotes.length){colorProofTicket++;colorProofAudio.pause();colorProofAudio.hidden=true;$('#color-proof-ab').hidden=true;$('#color-proof-caption').textContent='该色层没有进入当前编排，不播放替代音频。可选择其他色层或整体情绪。';return true;}
 const prefix=ab==='off'?'progressive'+(progressivePreset==='nature'?'':'-'+progressivePreset)+'-color-off':progressiveAudioPrefix();
 colorProofAudio.pause();ensureProofAudio();const ticket=++colorProofTicket;
 // Blob URLs support exact seeking even on the current server without HTTP Range.
 fetch(`studio/${data.id}-${prefix}-${voice===null?'mix':voice}.wav?v=${REVISION}`).then(r=>{if(!r.ok)throw Error('audio unavailable');return r.blob();}).then(async blob=>{
  const decoded=await proofContext.decodeAudioData(await blob.arrayBuffer());let peak=0,sum=0,count=0;
  for(let channel=0;channel<decoded.numberOfChannels;channel++){const samples=decoded.getChannelData(channel);for(let i=Math.floor(start*decoded.sampleRate);i<Math.min(samples.length,Math.ceil((start+5.2)*decoded.sampleRate));i++){peak=Math.max(peak,Math.abs(samples[i]));sum+=samples[i]*samples[i];count++;}}
  const auditionGain=voice===null?1:Math.min(80,.12/Math.max(.00001,Math.sqrt(sum/Math.max(1,count))),.85/Math.max(.00001,peak));
  if(ticket!==colorProofTicket)return;if(colorProofBlob)URL.revokeObjectURL(colorProofBlob);colorProofBlob=URL.createObjectURL(blob);
  proofGain.gain.setValueAtTime(auditionGain,proofContext.currentTime);
  if(voice!==null)$('#color-proof-caption').textContent+=` 独奏试听已补偿 ${auditionGain.toFixed(1)}×；作品内混音不变。`;
  colorProofAudio.onloadedmetadata=()=>{if(ticket!==colorProofTicket)return;colorProofAudio.currentTime=start;if(autoplay&&selectedNotes.length)colorProofAudio.play().catch(()=>{});};
  colorProofAudio.src=colorProofBlob;
 }).catch(()=>{if(ticket===colorProofTicket)$('#color-proof-caption').textContent='音轨暂时未能加载，请重新选择此色层。';});
 $('#color-proof-caption').textContent=selectedNotes.length?`播放 ${start.toFixed(1)}–${colorProofEnd.toFixed(1)} 秒的真实${voice===null?'混音':'分轨'}；数字和亮起音符来自同一份音乐数据。`:'该层未参与当前版本，播放已停用。';
 colorProofAudio.hidden=!selectedNotes.length;$('#color-proof-ab').hidden=colorProofRole!=='overall';
 return true;
}
colorProofAudio.ontimeupdate=()=>{const t=colorProofAudio.currentTime;$('#color-proof-score').querySelectorAll('i').forEach(n=>n.classList.toggle('sounding',!colorProofAudio.paused&&t>=+n.dataset.noteStart&&t<+n.dataset.noteEnd));if(t>=colorProofEnd)colorProofAudio.pause();};
colorProofButton.onclick=()=>{halt();colorProofRole='overall';if(renderColorProof()){document.body.classList.add('color-proof-open');colorProof.showModal();colorProof.classList.add('tracing');}};
$('#color-proof-close').onclick=()=>colorProof.close();colorProof.onclose=()=>{colorProofTicket++;colorProofAudio.pause();if(colorProofBlob){URL.revokeObjectURL(colorProofBlob);colorProofBlob=null;}colorProof.classList.remove('tracing');document.body.classList.remove('color-proof-open');};
$('#color-proof-tabs').onclick=e=>{const b=e.target.closest('[data-proof-role]');if(b){colorProofRole=b.dataset.proofRole;renderColorProof('current',true);}};
$('#color-proof-ab').onclick=e=>{const b=e.target.closest('[data-color-ab]');if(b)renderColorProof(b.dataset.colorAb,true);};
