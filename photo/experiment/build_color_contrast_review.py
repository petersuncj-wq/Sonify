"""Same-geometry / same-style three-way Color DNA acceptance artifacts."""
from pathlib import Path
import sys,json,wave,shutil,hashlib
ROOT=Path(__file__).parent;sys.path.insert(0,str(ROOT/'vendor'))
import numpy as np
from color_dna import analyze
from progressive_arrangement import arrange
# L3: the archived reference snapshots now live in `_archive/` so that
# they cannot be mistaken for production modules (and so that they are
# excluded from the engine hash allow-list).
sys.path.insert(0, str(ROOT / '_archive'))
from progressive_arrangement_v10_reference import arrange as old_arrange
from color_dna_v10_reference import analyze as old_analyze
from progressive_arrangement_v14_reference import arrange as layered_arrange
from color_dna_v12_reference import analyze as layered_analyze
import studio_grammar as sg,render_soundfont as rsf
from build_progressive_arrangement import mix_stems,read,write
OUT=ROOT/'dist/color-contrast';OUT.mkdir(exist_ok=True)
def features(a,rate):
 x=a.mean(axis=1);frames=np.lib.stride_tricks.sliding_window_view(x,2048)[::512]*np.hanning(2048);mag=np.abs(np.fft.rfft(frames,axis=1));freq=np.fft.rfftfreq(2048,1/rate);mass=mag.sum(1);valid=mass>1e-6
 centroid=(mag@freq)/np.maximum(mass,1e-9);roll=freq[(np.cumsum(mag,axis=1)>=mass[:,None]*.85).argmax(1)]
 bandwidth=np.sqrt(((freq[None,:]-centroid[:,None])**2*mag).sum(1)/np.maximum(mass,1e-9))
 bins=np.rint(69+12*np.log2(np.maximum(freq,1e-9)/440)).astype(int)%12;keep=(freq>32)&(freq<6000);chroma=np.array([mag[:,keep&(bins==i)].sum() for i in range(12)]);chroma/=max(chroma.sum(),1e-9)
 envelope=np.sqrt(np.mean(x[:len(x)//2205*2205].reshape(-1,2205)**2,axis=1))
 return dict(chroma=chroma.tolist(),rms_envelope=envelope.tolist(),bandwidth_hz=round(float(bandwidth[valid].mean()),2),rms=round(float(np.sqrt(np.mean(a*a))),6),centroid_hz=round(float(centroid[valid].mean()),2),rolloff85_hz=round(float(roll[valid].mean()),2),peak=round(float(np.abs(a).max()),4))
def build():
 p=json.loads((ROOT/'dist/studio/sample5.json').read_text(encoding='utf8'));units,_=sg.classify_units(p['contours'],p['width'],p['height']);photo=ROOT/'assets/color0721/image1.jpeg';color=analyze(photo,'0721 supplied original image');shutil.copyfile(photo,OUT/'original.jpg')
 variants={'off':arrange(p['soul'],'nature',units,color,'off'),'old_auto':old_arrange(p['soul'],'nature',units,old_analyze(photo),'auto'),'layered':layered_arrange(p['soul'],'nature',units,layered_analyze(photo),'auto'),'enhanced':arrange(p['soul'],'nature',units,color,'auto')}
 sf=rsf.find_soundfont();pool=rsf._SoundFontPool.get(sf,rate=22050,gain=1.2);audios={}
 for key,m in variants.items():
  for v in range(5):rsf.render_wav([n for n in m['notes'] if n['voice']==v],OUT/f'{key}-{v}.wav',sf_path=sf,total_seconds=37,rate=22050,pool=pool,normalize=False)
  audios[key]=mix_stems(key,m,OUT)[0]
 pool.close();target=min(.1,*[.9*np.sqrt(np.mean(a*a))/max(.001,np.abs(a).max()) for a in audios.values()]);report=dict(source_sha256=hashlib.sha256(photo.read_bytes()).hexdigest(),color=color,rms_target=float(target),fft=dict(window=2048,hop=512,rolloff=.85,method='mean of magnitude-weighted non-silent STFT frames'),variants={})
 baseline=variants['off'];lead=lambda m:[(n['pitch'],n['start'],n['duration'],n['source']) for n in m['notes'] if n['voice']==0]
 for key,m in variants.items():
  a=audios[key];a*=target/max(1e-9,np.sqrt(np.mean(a*a)));write(OUT/f'{key}-matched.wav',a,22050)
  stats=features(a,22050);midi=np.zeros(12)
  for n in m['notes']:midi[n['pitch']%12]+=n['duration']*n['velocity']
  midi/=max(midi.sum(),1e-9);stats['midi_chroma']=midi.tolist()
  stats.update(notes=len(m['notes']),lead_identity_preserved=lead(m)==lead(baseline),onsets_per_second=round(len(set(n['start'] for n in m['notes']))/36,3),voices={str(v):dict(notes=sum(n['voice']==v for n in m['notes']),median_pitch=float(np.median([n['pitch'] for n in m['notes'] if n['voice']==v])) if any(n['voice']==v for n in m['notes']) else None,programs=sorted(set(n['program'] for n in m['notes'] if n['voice']==v))) for v in range(5)})
  report['variants'][key]=stats;(OUT/f'{key}.json').write_text(json.dumps(m,ensure_ascii=False),encoding='utf8')
 reference=report['variants']['off']
 for stats in report['variants'].values():
  a=np.array(stats['chroma']);b=np.array(reference['chroma']);stats['midi_chroma_l1_from_off']=round(float(np.abs(np.array(stats['midi_chroma'])-np.array(reference['midi_chroma'])).sum()),6);stats['chroma_l1_from_off']=round(float(np.abs(a-b).sum()),6);stats['chroma_cosine_from_off']=round(float(a@b/(np.linalg.norm(a)*np.linalg.norm(b))),6);stats['rms_envelope_corr_from_off']=round(float(np.corrcoef(stats['rms_envelope'],reference['rms_envelope'])[0,1]),6)
 (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps({k:{x:v for x,v in value.items() if x not in ('chroma','rms_envelope','voices')} for k,value in report['variants'].items()},ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':build()
