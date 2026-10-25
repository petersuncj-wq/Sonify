'use strict';
const $ = selector => document.querySelector(selector);
let addressKey = '', queueKey = '';
async function json(url, options) {
  const response = await fetch(url, options); const data = await response.json();
  if (!response.ok) throw new Error(data.error || '服务连接失败'); return data;
}
function drawQueue(jobs) {
  const key = JSON.stringify(jobs.map(j => [j.id,j.updated_at,j.status,j.music_status,j.community]));
  if (key === queueKey) return; queueKey = key;
  $('#count').textContent = jobs.length;
  if ($('#received-preview')) {
    const preview=$('#received-preview');preview.replaceChildren();
    for(const job of jobs.slice(0,5)){const image=document.createElement('img');image.src=job.original;image.alt='';image.loading='lazy';preview.append(image);}
    if(!jobs.length){const empty=document.createElement('p');empty.className='hint';empty.textContent='等待第一张照片，点击进入图片列表';preview.append(empty);}
    return;
  }
  const container = $('#queue'); const scrollTop=container.scrollTop; container.replaceChildren();
  if (!jobs.length) { const p = document.createElement('p'); p.className='queue-empty'; p.textContent='等待第一张图片。观众上传后，这里会自动出现。'; container.append(p); }
  for (const job of jobs) {
    const card = document.createElement('article'); card.className='queue-item';
    const img = document.createElement('img'); img.src=job.original; img.alt='收到的图片'; img.loading='lazy';
    const info = document.createElement('div');
    const title = document.createElement('strong'); title.textContent=job.title || `${job.submission === 'phone' ? '手机' : '电脑'} · ${job.id.slice(0,6).toUpperCase()}`;
    const state = document.createElement('p'); state.textContent=(job.provider==='local'?(job.fallback_from?'OpenCV 备用 · ':'历史 OpenCV · '):'豆包 · ')+(job.error || job.music_error || job.stage);
    const date = document.createElement('small'); date.textContent=new Date(job.created_at*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});
    info.append(title,state,date); card.append(img,info);
    if (job.workspace && job.music_status === 'completed') {
      const link = document.createElement('a'); link.href='/experience?view=journey&job='+job.id; link.target='_blank'; link.rel='noopener'; link.className='open-piece'; link.textContent='观看生成旅程 ↗'; card.append(link);
    } else if(job.provider==='seedream'&&job.status==='failed'&&job.artistic_status==='failed'&&!job.artistic){const link=document.createElement('a');link.href='/experience?job='+job.id;link.target='_blank';link.rel='noopener';link.className='open-piece';link.textContent='豆包未出稿 · 查看重试方案';card.append(link); } else { const label = document.createElement('span'); label.className='queue-state'; label.textContent=job.status === 'failed' || job.music_status === 'failed' ? '未完成' : job.status === 'completed' ? '结构已就绪' : '处理中'; card.append(label); }
    const actions=document.createElement('div'); actions.className='queue-actions';
    while(card.children.length>2) actions.append(card.children[2]);
    actions.append(Community.publishButton(job,()=>{queueKey='';refreshNow();}));
    card.append(actions); container.append(card);
  }
}
async function refreshNow() {
  try {
    const data = await json(document.body.classList.contains('received-page')?'/api/received':'/api/host');
    $('#connection').textContent='接待服务在线';
    if(document.body.classList.contains('received-page')){drawQueue(data.jobs);return;}
    const share=data.share;
    $('#share-error').textContent= !share.enabled ? '请用“启动现场接待”脚本开启手机上传。' : !share.url ? '未找到 Wi-Fi 地址，请连接网络后重新启动。' : '';
    $('#qr').hidden = !share.url; $('#phone-link').hidden = !share.url;
    const key=JSON.stringify([share.addresses,share.address]);
    if (key !== addressKey && share.url) {
      addressKey=key; $('#address').replaceChildren();
      const verifiedAddress = share.address || '';
      const addresses=[...share.addresses].sort((a,b)=>Number(b===verifiedAddress)-Number(a===verifiedAddress));
      for (const address of addresses) { const option=document.createElement('option'); option.value=address; option.textContent=address===verifiedAddress ? `${address} — ★ 当前选择 · 待现场扫码确认` : (share.address_labels?.[address] || `${address} — 本机网络地址`); option.selected=address===share.address; option.style.color=address===verifiedAddress?'#b42318':'#283b35'; option.style.fontWeight=address===verifiedAddress?'700':'400'; $('#address').append(option); }
      $('#address').style.color=share.address===verifiedAddress?'#b42318':'';
      $('#address').style.fontWeight=share.address===verifiedAddress?'700':'';
      $('#verified-address').textContent=addresses.includes(verifiedAddress)?`当前选择：${verifiedAddress} · 请用现场手机扫码确认`:'请先验证当前网络的扫码地址';
      $('#qr').src='/api/share/qr.png?t='+Date.now();
      const preview=new URL(share.url); preview.hostname='127.0.0.1'; $('#phone-link').href=preview.href;
    }
    drawQueue(data.jobs);
  } catch (error) { $('#connection').textContent='连接中断，正在重连…'; }

}
$('#address')?.addEventListener('change',async () => {
  try { await json('/api/share/address',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({address:$('#address').value})}); }
  catch(error) { $('#share-error').textContent=error.message; }
});
$('#fullscreen')?.addEventListener('click', async () => {
  try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); }
  catch(error) { $('#connection').textContent='可使用浏览器全屏功能扩大展示区域'; }
});
refreshNow();
setInterval(refreshNow,2000);
