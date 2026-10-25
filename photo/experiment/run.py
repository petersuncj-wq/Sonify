"""Reproducible line-art -> path graph -> musical events experiment."""
from pathlib import Path
import sys, json, math, hashlib, zipfile, wave, struct
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import cv2
import numpy as np
from PIL import Image, ImageOps
from geometry import trace, extract
from midi_io import write_midi

SOURCE = ROOT.parent / '线稿示例图'
OUT = ROOT / 'dist'
OUT.mkdir(exist_ok=True)
SCALE = [48,50,52,55,57,60,62,64,67,69,72,74,76,79]

# `trace()` and `extract()` now live in `geometry.py` (shared by every
# producer).  They are imported at the top of this module and re-exported
# here for backwards compatibility with `import run as lab` call sites.

def sample(p,n):
    a=np.array(p['points']); d=np.r_[0,np.cumsum(np.linalg.norm(np.diff(a,axis=0),axis=1))]
    return np.array([np.interp(np.linspace(0,d[-1],n),d,a[:,i]) for i in range(2)]).T

def compose(paths,groups,disabled=None):
    notes=[]
    def add(p,pitch,start,duration,rule,voice,point=None):
        notes.append(dict(id=f'n{len(notes):03d}',source=p['id'],source_point=point,pitch=int(pitch),start=round(float(start),3),duration=round(float(duration),3),rule=rule,voice=voice))
    if disabled!='contour':
        chosen=[p for p in paths if p['kind']=='curve'][:3]
        for k,p in enumerate(chosen):
            points=sample(p,8); center=float(points[:,1].mean());span=max(float(np.ptp(points[:,1])),.12)
            for j,(x,y) in enumerate(points):
                degree=(1-center)*(len(SCALE)-1)+(center-y)/span*6
                pitch=SCALE[int(np.clip(round(degree),0,len(SCALE)-1))]
                add(p,pitch,k*4+j*.5,.43,'contour',0,[round(float(x),5),round(float(y),5)])
                notes[-1]['calculation']=dict(center=center,span=span,degree=degree,scale_index=int(np.clip(round(degree),0,len(SCALE)-1)),sample_index=j)
    if disabled!='support':
        for k,p in enumerate([p for p in paths if p['kind']=='horizontal'][:3]):add(p,48+(k%2)*7,k*4,3.6,'support',1)
    if disabled!='repeat':
        byid={p['id']:p for p in paths}
        for g in groups[:1]:
            for j,pid in enumerate(g[:8]):
                for k in range(2):add(byid[pid],60+(j%2)*7,k*6+j*.5,.22,'repeat',2)
    return notes

def export(notes,path):
    write_midi(notes, path.with_suffix('.mid'), tempo_bpm=120)
    rate=22050;audio=np.zeros(rate*14,dtype=np.float64)
    for n in notes:
        count=int((n['duration']+.12)*rate);t=np.arange(count)/rate;freq=440*2**((n['pitch']-69)/12)
        env=np.minimum(t/.025,1)*np.exp(-t/(.5 if n['voice']!=1 else 2))*np.minimum(np.maximum((n['duration']+.12-t)/.12,0),1)
        tone=(np.sin(2*np.pi*freq*t)+.15*np.sin(4*np.pi*freq*t))*env*.08
        a=int(n['start']*rate);b=min(a+count,len(audio));audio[a:b]+=tone[:b-a]
    audio=np.tanh(audio)
    with wave.open(str(path.with_suffix('.wav')),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes((audio*32767).astype('<i2').tobytes())

def main():
    results=[]
    for index,file in enumerate(sorted(SOURCE.glob('*'))):
        if file.suffix.lower() not in ['.jpg','.png'] or file.name=='原图.jpg':continue
        slug=f'sample{len(results)}';image=Image.open(file).convert('RGB');image.thumbnail((640,840));image.save(OUT/f'{slug}.jpg')
        gray=cv2.cvtColor(np.array(image),cv2.COLOR_RGB2GRAY)
        exclusions=[]
        if file.name in ['线稿1.jpg','线稿2.jpg']:
            # Explicitly declared manual exclusion for embedded video captions.
            h,w=gray.shape;box=(int(w*.15),int(h*.74),int(w*.83),int(h*.84));gray[box[1]:box[3],box[0]:box[2]]=255;exclusions.append('人工屏蔽字幕区域 y=74%–84%（也可能排除少量建筑线条）')
        mask,skel,paths,groups,metrics=extract(gray)
        Image.fromarray(255-mask).save(OUT/f'{slug}-binary.png');Image.fromarray(255-skel).save(OUT/f'{slug}-skeleton.png')
        variants={}
        for key,disabled in [('all',None),('no-contour','contour'),('no-support','support'),('no-repeat','repeat')]:
            ns=compose(paths,groups,disabled);export(ns,OUT/f'{slug}-{key}');variants[key]=ns
        result=dict(id=slug,name=file.name,sha256=hashlib.sha256(file.read_bytes()).hexdigest(),paths=paths,groups=groups,metrics=metrics,variants=variants,exclusions=exclusions,width=image.width,height=image.height)
        (OUT/f'{slug}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');results.append(result)
    refs=[]
    for file in SOURCE.glob('*.docx'):
        with zipfile.ZipFile(file) as z:
            for entry in z.namelist():
                if entry.startswith('word/media/'):
                    try:
                        import io
                        im=Image.open(io.BytesIO(z.read(entry))).convert('RGB');im.thumbnail((800,800));name=f'reference{len(refs)}.jpg';im.save(OUT/name);refs.append(dict(file=name,source=file.name,pairing='未确认，不参与配对保真度评价'))
                    except Exception:pass
    payload=dict(samples=results,references=refs,version='0.1',limitations=['不识别屋顶/窗户语义；分类是几何候选','重复组按方向、长度和位置启发式识别，尚未验证等间距','没有自动深度估计、原图对齐或标准五线谱','音乐为固定五声音阶规则与简单合成音色，不是 AI 编曲'])
    (OUT/'data.js').write_text('window.EXPERIMENT='+json.dumps(payload,ensure_ascii=False)+';',encoding='utf-8')
    print(json.dumps([dict(name=r['name'],**r['metrics'],groups=len(r['groups']),notes=len(r['variants']['all'])) for r in results],ensure_ascii=False,indent=2))
    return payload

if __name__=='__main__':main()
