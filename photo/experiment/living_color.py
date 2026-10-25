"""Four labelled colour interpretations of one original; geometry is never redetected."""
from pathlib import Path
import json
import numpy as np
from PIL import Image,ImageEnhance
from color_dna import analyze
from progressive_arrangement import arrange,PRESETS
from seasonal_rules import SEASON_RULES

SEASONS=SEASON_RULES

# M9 (robustness): the stem prefix used to be written out inline in two
# places with *different* strings — the generator used
# `f'{slug}-season-v11-{id}-{preset}'` while the cleanup path looked for
# `f"{id}-season-{state_id}-{preset}-{voice}.wav"` (missing both the
# `v11` marker and the slug).  When `mix_stems()` raised, the five
# intermediate stems survived on disk: 80 leftover 37-second stereo WAVs
# per failed upload, which is exactly what fills up the disk on an
# exhibition machine.
#
# A single helper now produces the prefix, and the stems are removed in a
# `finally` block so they are cleaned up even when rendering fails.
def _stem_prefix(slug,state_id,preset):
 """The one and only stem prefix for a seasonal mix."""
 return f'{slug}-season-v11-{state_id}-{preset}'

def _identity_prefix(slug,preset):
 """The one and only prefix for an identity-theme preview."""
 return f'{slug}-identity-{preset}.wav'

def interpretations(original):
 image=Image.open(original).convert('RGB');image.thumbnail((1000,1000))
 for rule in SEASONS:
  id,label,brightness,saturation,tint,blend=(rule[k] for k in ('id','label','brightness','saturation','tint','blend'))
  frame=ImageEnhance.Brightness(ImageEnhance.Color(image).enhance(saturation)).enhance(brightness)
  frame=Image.blend(frame,Image.new('RGB',frame.size,tuple(tint)),blend)
  yield id,label,frame

def build(payload,units,original,assets,pool,sf):
 from build_progressive_arrangement import mix_stems
 import render_soundfont as rsf
 states=[];slug=payload['id'];assets=Path(assets)
 for id,label,image in interpretations(original):
  rule=next(r for r in SEASONS if r['id']==id)
  photo=f'{slug}-season-v11-{id}.jpg';image.save(assets/photo,quality=92)
  color=analyze(image,'colour interpretation of the same original; no scene generation')
  music={}
  for preset in PRESETS:
   m=arrange(payload['soul'],preset,units,color,'auto',season=rule,identity_mode=True);prefix=_stem_prefix(slug,id,preset)
   try:
    for v in range(5):rsf.render_wav([n for n in m['notes'] if n['voice']==v],assets/f'{prefix}-{v}.wav',sf_path=sf,total_seconds=37,rate=22050,pool=pool,normalize=False)
    audio,rate=mix_stems(prefix,m,assets)
   finally:
    # M9: the intermediate stems are disposable (Living mode plays the
    # mixed file), so they are removed whether or not the mix succeeded.
    for v in range(5):(assets/f'{prefix}-{v}.wav').unlink(missing_ok=True)
   # Comparable level without stripping the shared 36-second dynamic narrative.
   rms=float(np.sqrt(np.mean(audio*audio)));gain=min(.10/max(1e-8,rms),.85/max(.001,float(np.abs(audio).max())))
   from build_progressive_arrangement import write
   write(assets/f'{prefix}-mix.wav',audio*gain,rate)
   m['living_rms']=round(rms*gain,6);m['audio']=f'studio/{prefix}-mix.wav';music[preset]=m
  states.append(dict(id=id,label=label,rule=rule,image='studio/'+photo,color=color,music=music))
 identities={}
 for preset in PRESETS:
  m=arrange(payload['soul'],preset,units,payload.get('color_dna'),'off',identity_mode=True)
  prefix=_identity_prefix(slug,preset);theme_notes=[n for n in m['notes'] if n['arrangement_role']=='original_theme']
  rsf.render_wav(theme_notes,assets/prefix,sf_path=sf,total_seconds=8,rate=22050,pool=pool,normalize=True)
  identities[preset]=dict(theme=m['theme'],notes=theme_notes,key_pc=m['key_pc'],audio='studio/'+prefix,relative_intervals=[b['pitch']-a['pitch'] for a,b in zip(m['theme'],m['theme'][1:])],starts=[n['start'] for n in theme_notes])
 payload['living_color']=dict(version='four-seasons-1.1',kind='colour_interpretation_with_atmosphere',identity=identities,geometry_fixed=True,states=states,transition='image and atmosphere interpolate; music changes at 2-second bar boundaries with a short fade through silence',sync_bpm=120)
 normalize_levels(payload,assets)
 return payload['living_color']

def normalize_levels(payload,assets):
 from build_progressive_arrangement import read,write
 for preset in PRESETS:
  rows=[]
  for state in payload['living_color']['states']:
   m=state['music'][preset];path=Path(assets)/Path(m['audio']).name;a,rate=read(path);rms=float(np.sqrt(np.mean(a*a)));rows.append((m,path,a,rate,rms))
  target=min([.1]+[row[-1] for row in rows])
  for m,path,a,rate,rms in rows:
   write(path,a*(target/max(1e-9,rms)),rate);m['living_rms']=round(target,6)

def refresh_all():
 import sys;sys.path.insert(0,str(Path(__file__).parent/'vendor'))
 import render_soundfont as rsf,studio_grammar as sg
 root=Path(__file__).parent;sf=rsf.find_soundfont();pool=rsf._SoundFontPool.get(sf,rate=22050,gain=1.2)
 files=[p/'workspace/studio/sample5.json' for p in (root.parent/'intake/runtime').iterdir() if (p/'workspace/studio/sample5.json').exists()]
 files.sort(key=lambda p:'8fb4b11' not in str(p));demo=root/'dist/studio/sample5.json';files.append(demo)
 for path in files:
  p=json.loads(path.read_text(encoding='utf8'))
  if not p.get('color_dna',{}).get('available'):continue
  original=path.parents[2]/'original.png' if path!=demo else path.parent/'sample5-original.jpg'
  if not original.exists():continue
  units,_=sg.classify_units(p['contours'],p['width'],p['height']);build(p,units,original,path.parent,pool,sf)
  pending=path.with_suffix('.living.json');pending.write_text(json.dumps(p,ensure_ascii=False,separators=(',',':')),encoding='utf8');pending.replace(path)
  print('FOUR SEASONS',path.parents[2].name,flush=True)
 pool.close()

if __name__=='__main__':
 import sys
 if '--normalize-only' not in sys.argv:refresh_all()
 else:
  root=Path(__file__).parent
  for path in list((root.parent/'intake/runtime').glob('*/workspace/studio/sample5.json'))+[root/'dist/studio/sample5.json']:
   p=json.loads(path.read_text(encoding='utf8'))
   if not p.get('living_color'):continue
   normalize_levels(p,path.parent);pending=path.with_suffix('.living.json');pending.write_text(json.dumps(p,ensure_ascii=False,separators=(',',':')),encoding='utf8');pending.replace(path)
   for state in p['living_color']['states']:
    for preset in PRESETS:
     # M9: use the shared prefix helper so the cleanup path can no
     # longer drift away from the naming used at render time.
     for voice in range(5):
      stem=path.parent/f'{_stem_prefix(p["id"],state["id"],preset)}-{voice}.wav'
      if stem.exists():stem.unlink()
  print('Living levels matched within each style')
