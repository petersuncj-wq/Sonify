'use strict';
const $=s=>document.querySelector(s), storeKey='sonify-experience-v1';
let jobs=new Map(),selected=null,view='journey',mode='blueprint',frame=null,revision=0,frameTimer=null,focusObserver=null,uploadBusy=false,retryBusy=false,selectionVersion=0,lineartBridge=null;
const terminal=j=>['completed','failed'].includes(j.status);
async function api(url,options){const response=await fetch(url,options),data=await response.json();if(!response.ok)throw new Error(data.error||(data.errors||[]).map(x=>x.error).join(' ')||'连接失败，请稍后重试。');return data;}
function persist(){localStorage.setItem(storeKey,JSON.stringify({selected,view,mode,closed:document.body.classList.contains('library-closed')}));if(selected){const u=new URL(location.href);u.searchParams.set('job',selected);u.searchParams.delete('view');history.replaceState(null,'',u);}}
function clearFrame(){revision++;if(focusObserver)focusObserver.disconnect();focusObserver=null;document.body.classList.remove('frame-focus','journey-view');if(frameTimer)clearTimeout(frameTimer);frameTimer=null;if(frame){frame.src='about:blank';frame.remove();frame=null;}$('#frame-host').replaceChildren();$('#frame-host').hidden=true;}
function jobLabel(job){return job.title||`${job.submission==='phone'?'手机图片':'图片'} · ${job.id.slice(0,6).toUpperCase()}`;}
// M11: inline rename.  The whole row used to be a <button>, and a <button>
// may not contain an <input> (invalid HTML, and the click would bubble to
// the row's select handler).  The row is therefore a <div> that holds a
// separate select button and a separate rename button.
function makeRenameControl(job,info,title){
 const rename=document.createElement('button');
 rename.className='rename-button';rename.type='button';rename.textContent='✎';
 rename.setAttribute('aria-label','重命名作品');rename.title='重命名作品';
 rename.onclick=async(event)=>{
  event.stopPropagation();
  const input=document.createElement('input');
  input.className='rename-input';input.maxLength=60;input.value=job.title||'';
  input.setAttribute('aria-label','作品名');
  title.replaceWith(input);
  input.focus();input.select();
  let settled=false;
  const commit=async()=>{
   if(settled)return;settled=true;
   const next=input.value.trim();
   try{
    if(next&&next!==job.title){
     const updated=await api('/api/jobs/'+job.id+'/title',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:next})});
     jobs.set(updated.id,updated);
    }
   }catch(error){
    $('#upload-note').textContent=error.message||'重命名失败，请稍后再试。';
   }
   list();
  };
  input.onblur=commit;
  input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();input.blur();}else if(e.key==='Escape'){input.value=job.title||'';input.blur();}};
 };
 return rename;
}
function list(){const container=$('#items');container.replaceChildren();const rows=[...jobs.values()].sort((a,b)=>b.created_at-a.created_at);$('#total').textContent=rows.length;for(const job of rows){const row=document.createElement('div');row.className='item';row.setAttribute('aria-pressed',String(job.id===selected));const button=document.createElement('button');button.className='item-select';button.setAttribute('aria-pressed',String(job.id===selected));const image=new Image();image.src=job.artistic||job.original;image.alt='作品缩略图';image.loading='lazy';const info=document.createElement('span'),title=document.createElement('strong'),state=document.createElement('small');title.textContent=jobLabel(job);const providerLabel={'supplied':'本地精细线稿','local':job.fallback_from?'快速备用':'快速本地','seedream':'云端','comfy':'ComfyUI'}[job.provider]||job.provider;state.textContent=providerLabel+' · '+(job.error?'未完成，可重试':job.music_status==='completed'?'作品已就绪':job.stage);info.append(title,state);button.append(image,info);button.onclick=()=>choose(job.id);row.append(button,makeRenameControl(job,info,title));container.append(row);}}
function waiting(job){$('#waiting').hidden=false;$('#mode-nav').hidden=true;$('#replay').hidden=true;$('#waiting-images').replaceChildren();if(!job)return;$('.empty-symbol').hidden=true;$('#waiting-title').textContent=job.error?'这次生成未完成':job.music_status==='failed'?'线稿已准备好，音乐未完成':'你的图片，正在成为作品。';$('#waiting-state').textContent=job.error||job.music_error||job.stage;$('#fallback-local').hidden=!(job.provider==='seedream'&&job.status==='failed'&&job.artistic_status==='failed'&&!job.artistic);$('#retry').hidden=!(job.status==='failed'||job.music_status==='failed');$('#retry').disabled=retryBusy;$('#retry').textContent=job.music_status==='failed'&&job.structural?'只重试音乐（复用线稿）':'重新生成';for(const [url,label] of [[job.original,'你的原图'],[job.artistic||job.structural,'已生成的线稿']]){if(!url)continue;const fig=document.createElement('figure'),im=new Image(),caption=document.createElement('figcaption');im.src=url;im.alt=label;caption.textContent=label;fig.append(im,caption);$('#waiting-images').append(fig);}$('#view-note').textContent=terminal(job)?'原图与已成功的产物已保留，失败不影响其他作品。':'这里显示实际处理状态；线稿和音乐准备完成后，才播放生成旅程。';}
function selectMode(next){if(!['soul','blueprint','progressive'].includes(next))return;mode=next;if(frameTimer)clearTimeout(frameTimer);document.querySelectorAll('#mode-nav button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));persist();if(!frame)return;const ticket=revision;let tries=0;const apply=()=>{if(ticket!==revision||!frame)return;try{const doc=frame.contentDocument,play=doc?.querySelector('#play'),tab=doc?.querySelector(`button[data-mode="${next}"]`);if(tab&&play&&!play.disabled){tab.click();return;}}catch(e){}if(++tries<100)frameTimer=setTimeout(apply,150);else $('#view-note').textContent='作品载入较慢，可在作品内直接选择模式，或重新打开。';};apply();}
function mount(kind){const job=jobs.get(selected);if(!job||job.music_status!=='completed'||!job.workspace)return;clearFrame();$('#eyebrow').textContent='YOUR IMAGE · YOUR MUSIC';view=kind;document.body.classList.toggle('journey-view',kind==='journey');$('#waiting').hidden=true;$('#frame-host').hidden=false;$('#mode-nav').hidden=kind!=='perform';$('#replay').hidden=kind!=='perform';frame=document.createElement('iframe');frame.title=kind==='journey'?'图片成为音乐的生成旅程':'当前图片的三个音乐观看模式';frame.allow='autoplay; fullscreen';const ticket=revision;frame.onload=()=>{if(ticket!==revision||!frame)return;if(kind==='perform'){try{const doc=frame.contentDocument,style=doc.createElement('style');style.textContent=`body>header,main>.intro,main>nav[aria-label="作品模式"]{display:none!important}main{padding-top:10px!important}
`;doc.head.append(style);
const syncFocus=()=>{if(ticket===revision&&frame){const focused=doc.body.classList.contains('reveal-focus')||doc.body.classList.contains('soul-focus')||doc.body.classList.contains('blueprint-focus')||doc.body.classList.contains('color-proof-open')||!!doc.querySelector('#birth-guide[open]');document.body.classList.toggle('frame-focus',focused);if(!focused&&manualFullscreen){manualFullscreen=false;$('#exhibit-fullscreen').textContent='全屏展示';if(document.fullscreenElement)document.exitFullscreen().catch(()=>{});}}};
focusObserver=new MutationObserver(syncFocus);focusObserver.observe(doc.body,{attributes:true,attributeFilter:['class']});const birthGuide=doc.querySelector('#birth-guide');if(birthGuide)focusObserver.observe(birthGuide,{attributes:true,attributeFilter:['open']});syncFocus();for(const b of doc.querySelectorAll('button[data-mode]'))b.addEventListener('click',()=>{mode=b.dataset.mode;document.querySelectorAll('#mode-nav button').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.mode===mode)));persist();});}catch(e){}selectMode(mode);}};frame.src=kind==='journey'?`/journey?job=${job.id}&embed=1`:job.workspace;$('#frame-host').append(frame,leave);$('#view-note').textContent=kind==='journey'?'点击开始观看；这是已生成结果的解释动画，可暂停或跳过。':'当前展示只使用这张图片的独立作品。切换作品会停止旧声音。';persist();}
function choose(id,restore=false){if(!jobs.has(id))return;selectionVersion++;clearFrame();selected=id;const job=jobs.get(id);$('#heading').textContent=`让图片 ${id.slice(0,6).toUpperCase()}，成为音乐。`;$('#eyebrow').textContent=job.music_status==='completed'?'YOUR IMAGE · YOUR MUSIC':'READING YOUR IMAGE';$('#retry').hidden=true;$('#fallback-local').hidden=true;$('#resume-poll').hidden=true;list();if(job.music_status==='completed'&&job.workspace)mount(restore?view:'journey');else{view='waiting';waiting(job);persist();}}
window.addEventListener('message',event=>{if(event.origin!==location.origin||!frame||event.source!==frame.contentWindow)return;if(event.data?.type==='sonify-journey-complete'&&view==='journey'){mode='blueprint';mount('perform');}});
$('#library-toggle').onclick=()=>{document.body.classList.toggle('library-closed');$('#library-toggle').setAttribute('aria-expanded',String(!document.body.classList.contains('library-closed')));persist();};
$('#replay').onclick=()=>mount('journey');document.querySelectorAll('#mode-nav button').forEach(b=>b.onclick=()=>selectMode(b.dataset.mode));
function image64(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('无法读取图片'));reader.readAsDataURL(file);});}
$('#upload').onchange=()=>{$('#generate').disabled=!$('#upload').files.length||uploadBusy;};
$('#generate').onclick = async () => {
  if (uploadBusy) return;
  const files = [...$('#upload').files], provider = $('#engine').value;
  if (!files.length || files.length > 5 || files.some(f => !['image/jpeg','image/png'].includes(f.type) || f.size > 12*1024*1024)) {
    $('#upload-note').textContent = '请选择1–5张JPG/PNG，单张不超过12 MB。'; return;
  }
  if (provider === 'supplied' && files.length > 1) {
    $('#upload-note').textContent = '精细线稿请逐张处理；批量照片可选择快速结构提取。'; return;
  }
  uploadBusy = true;
  for (const id of ['generate','upload','engine']) $('#'+id).disabled = true;
  const version = selectionVersion;
  try {
    let accepted = [], errors = [];
    if (provider === 'supplied') {
      lineartBridge ||= new window.LineArtBridge();
      $('#upload-note').textContent = '选择要保留的轮廓，再点击应用。';
      const result = await lineartBridge.extract('data:'+files[0].type+';base64,'+await image64(files[0]));
      if (!result.success) { $('#upload-note').textContent = result.canceled ? '已取消，可以重新选择图片。' : '提取未完成，请重试。'; return; }
      accepted = [await api('/api/jobs', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image:result.original.split(',')[1],lineart:result.lineart.split(',')[1],method:result.method,provider})})];
    } else {
      const images = await Promise.all(files.map(async file => ({image:await image64(file)})));
      if (images.length === 1) accepted = [await api('/api/jobs', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...images[0],provider})})];
      else { const r = await api('/api/jobs/batch', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({images,provider})}); accepted = r.accepted.map(x=>x.job); errors = r.errors; }
    }
    for (const job of accepted) jobs.set(job.id, job);
    list(); if (accepted.length && version === selectionVersion) choose(accepted[0].id);
    $('#upload-note').textContent = errors.length ? errors.map(x=>`第${x.index+1}张：${x.error}`).join(' ') : `${accepted.length}张已提交，音乐准备好后即可播放。`;
  } catch (error) { $('#upload-note').textContent = error.message+' 请先检查作品列表，再决定是否重试。'; }
  finally { uploadBusy = false; for (const id of ['generate','upload','engine']) $('#'+id).disabled = false; }
};
$('#retry').onclick=async()=>{if(retryBusy||!selected)return;const old=jobs.get(selected),version=selectionVersion;retryBusy=true;$('#retry').disabled=true;try{if(old.music_status==='failed'&&old.structural){const job=await api('/api/jobs/'+old.id+'/retry-music',{method:'POST'});jobs.set(job.id,job);if(version===selectionVersion)choose(job.id);return;}if(old.provider==='supplied'){if(!lineartBridge)lineartBridge=new window.LineArtBridge();$('#waiting-state').textContent='正在重新提取线稿';const response=await fetch(old.original);if(!response.ok)throw new Error('原图暂时无法读取');const blob=await response.blob();const dataURL=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(blob);});const result=await lineartBridge.extract(dataURL);if(!result.success){$('#waiting-state').textContent=result.canceled?'已取消重新提取':'线稿提取失败';return;}const image=result.original.split(',')[1],lineart=result.lineart.split(',')[1];const job=await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image,lineart,provider:'supplied',method:result.method})});jobs.set(job.id,job);list();if(version===selectionVersion)choose(job.id);return;}const response=await fetch(old.original);if(!response.ok)throw new Error('原图暂时无法读取');const image=await image64(await response.blob());const job=await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image,provider:old.provider})});jobs.set(job.id,job);list();if(version===selectionVersion)choose(job.id);}catch(error){$('#waiting-state').textContent=error.message;}finally{retryBusy=false;$('#retry').disabled=false;}};
$('#fallback-local').onclick=async()=>{if(retryBusy||!selected)return;retryBusy=true;const button=$('#fallback-local');button.disabled=true;const version=selectionVersion;try{const job=await api('/api/jobs/'+selected+'/fallback-local',{method:'POST'});jobs.set(job.id,job);list();if(version===selectionVersion)choose(job.id);}catch(error){$('#waiting-state').textContent=error.message;}finally{retryBusy=false;button.disabled=false;}};
$('#resume-poll').onclick=()=>{refresh();};
let pollTimer=null,refreshing=false,restored=false;
async function refresh(){if(refreshing)return;refreshing=true;if(pollTimer)clearTimeout(pollTimer);try{const data=await api('/api/host');for(const job of data.jobs)jobs.set(job.id,job);$('#connection').textContent='作品列表已连接';$('#resume-poll').hidden=true;list();if(!restored){restored=true;let saved={};try{saved=JSON.parse(localStorage.getItem(storeKey)||'{}');}catch(e){}const queryParams=new URLSearchParams(location.search),query=queryParams.get('job'),id=query||saved.selected;const resume=id===saved.selected;mode='blueprint';view=queryParams.get('view')==='journey'?'journey':resume&&['journey','perform'].includes(saved.view)?saved.view:'journey';if(saved.closed){document.body.classList.add('library-closed');$('#library-toggle').setAttribute('aria-expanded','false');}if(id&&jobs.has(id))choose(id,true);}else if(selected&&jobs.has(selected)){const job=jobs.get(selected);if(view==='waiting'){if(job.music_status==='completed'&&job.workspace)mount('journey');else waiting(job);}}}catch(error){$('#connection').textContent='连接中断，正在重连；当前作品不会切换。';if(selected&&view==='waiting'){$('#waiting-state').textContent='处理状态暂时无法读取，网络恢复后会继续。';$('#resume-poll').hidden=false;}}finally{refreshing=false;pollTimer=setTimeout(refresh,1800);}}
window.addEventListener('pagehide',()=>{clearFrame();if(pollTimer)clearTimeout(pollTimer);});
(async()=>{try{const health=await api('/api/health');$('#engine option[value="supplied"]').disabled=false;$('#engine option[value="local"]').disabled=false;$('#engine option[value="seedream"]').disabled=!health.providers.seedream;$('#engine option[value="comfy"]').disabled=!health.providers.comfy;if(!health.providers.seedream)$('#engine option[value="seedream"]').textContent='豆包线稿 · 服务不可用';if(health.providers.comfy)$('#engine option[value="comfy"]').textContent='AI结构提纯 · 专用工作台';$('#engine').value='supplied';$('#upload-note').textContent=health.providers.seedream||health.providers.comfy?'本地生成完全免费离线，云端生成需服务配置。':'云端服务暂时不可用，本地生成可正常使用。';}catch(e){$('#engine').value='supplied';$('#upload-note').textContent='无法连接本机服务，请重新启动 Python 程序。';}refresh();})();

// Escape also works when keyboard focus is outside the embedded artwork.
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.body.classList.contains('frame-focus')){frame?.contentDocument?.querySelector('#reveal-focus')?.click();}});

let manualFullscreen=false;
function focusPiece(on){manualFullscreen=on;document.body.classList.toggle('frame-focus',on);frame?.contentWindow?.postMessage({type:'sonify-exhibit-focus',on},location.origin);$('#exhibit-fullscreen').textContent=on?'退出全屏 · Esc':'全屏展示';}
$('#exhibit-fullscreen').onclick=async()=>{if(!frame)return;const on=!document.body.classList.contains('frame-focus');focusPiece(on);try{if(on&&!document.fullscreenElement)await $('#frame-host').requestFullscreen();else if(!on&&document.fullscreenElement)await document.exitFullscreen();}catch{} };
const leave=document.createElement('button');leave.id='frame-exit';leave.textContent='退出全屏 · Esc';$('#frame-host').append(leave);
leave.onclick=async()=>{focusPiece(false);if(document.fullscreenElement)await document.exitFullscreen();};
document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement&&manualFullscreen)focusPiece(false);});
document.addEventListener('keydown',e=>{if(e.key==='Escape')focusPiece(false);});
