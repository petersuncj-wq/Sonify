"""36-second geometric motif arrangement. Source identity is retained on all events."""
from copy import deepcopy
import hashlib

PRESETS={
 'nature':dict(name='东方自然',programs=[73,0,42,88,48]),
 'chamber':dict(name='室内古典',programs=[40,0,42,48,49]),
}
CHORDS={'C':(0,[0,4,7]),'Am':(9,[9,0,4]),'F':(5,[5,9,0]),'G':(7,[7,11,2]),'Dm':(2,[2,5,9])}
PROGRESSION=['C','C','Am','F','C','G','Am','F','Dm','G','F','G','C','Am','F','G','G','C']
EMOTIONS=[('anticipation','悬念',0,6),('emergence','初生',6,14),('expansion','展开',14,24),('revelation','显现',24,32),('resolution','归一',32,36)]

def nearest(p,pcs,lo=36,hi=84):
 return min((n for n in range(lo,hi+1) if n%12 in pcs),key=lambda n:(abs(n-p),n))

def arrange(soul,preset='nature',units=None):
 import progressive_features as pf
 F=pf.compute(units,soul);P=pf.params(F)
 style=PRESETS[preset];source=soul['notes'];lead=[n for n in source if n['voice']==0]
 if not lead:lead=source
 if not source:raise ValueError('No geometric source events')
 theme=[deepcopy(lead[i%len(lead)]) for i in range(4)]
 pools={v:[n for n in source if n['voice']==v] or lead for v in range(5)}
 notes=[]
 def emit(v,pitch,start,duration,velocity,origin,role,chord,theme_index=None):
  n=deepcopy(origin);n.update(id=hashlib.sha256(f'{preset}-{v}-{pitch}-{start}-{origin["source"]}-{len(notes)}'.encode()).hexdigest()[:16],voice=v,program=style['programs'][v],pitch=int(pitch),start=round(start,6),duration=round(min(duration,35.8-start),6),velocity=int(velocity),arrangement_role=role,parent_note_id=origin['id'],theme_index=theme_index)
  n.update(voice_id=v,role=role,note_role=role,section=next(e[0] for e in EMOTIONS if e[2]<=start<e[3]),section_id=next(e[0] for e in EMOTIONS if e[2]<=start<e[3]),phrase=f'reveal-{int(start//2)}-{v}')
  n['calculation']=dict(origin.get('calculation',{}),arrangement=role,chord=chord,preset=preset,source_pitch=origin['pitch'])
  if n['duration']>0:notes.append(n)
 prev_voicing=[55,64]
 for bar,chord in enumerate(PROGRESSION):
  t=bar*2;root,pcs=CHORDS[chord]
  phase=next(e[0] for e in EMOTIONS if e[2]<=t<e[3])
  intensity={'anticipation':0,'emergence':8,'expansion':18,'revelation':30,'resolution':10}[phase]
  # Common tones sustain across bar lines; moving tones lead by the shortest distance.
  voicing=[]
  for old in prev_voicing:
   choices=[p for p in range(52,70) if p%12 in pcs and p not in voicing]
   voicing.append(min(choices,key=lambda p:abs(p-old)))
  if bar==16:voicing=[55,59,65]   # G7 (leading tone + 7th) -> dominant tension
  if bar==17:voicing=[55,64]      # C(G,E) + bass C + string C = tonic, keeps budget
  prev_voicing=voicing[:2]
  if 3 in P['voices']:
   for pitch in voicing:
    emit(3,pitch,t,1.99 if bar<17 else 1.8,34+intensity,pools[3][bar%len(pools[3])],'voice_led_harmony',chord)
  if bar>=3:
   bass=nearest(43, [root],36,50)
   emit(2,bass,t,1.85 if bar<17 else 1.8,49+intensity,pools[2][bar%len(pools[2])],'root_support',chord)
   if 7<=bar<16:
    emit(2,nearest(bass+7,[(root+7)%12],36,55),t+1.5,.35,44+intensity,pools[2][bar%len(pools[2])],'fifth_connection',chord)
    notes[-2]['duration']=1.45
  if bar in (0,2):
   # The first motif spans two bars; the same contour returns at 24 seconds.
   for i,(beat,dur) in enumerate(zip([.35,1.8,3.3,5.5],[1.2,1.2,1.8,2.0])):
    emit(0,theme[i]['pitch'],t+beat*.5,dur*.5,60+bar*2,theme[i],'original_theme',chord,i)
  elif 3<=bar<16 and (bar%2==1 or bar>=12):
   for i,(beat,dur) in enumerate(zip([0,.75,1.5,2.75],[.6,.6,1.0,.9])):
    origin=theme[i]
    # bars 12 keeps the exact opening theme (reprise contract); later bars rise
    # by the image's verticality so the melody builds toward the final reveal.
    off={9:2,10:2,11:3,13:2,14:4,15:6}.get(bar,0)+P['register']
    pitch=origin['pitch'] if bar==12 else nearest(origin['pitch']+off,pcs,65,84)
    dur2=dur*.5*P['legato']
    emit(0,pitch,t+beat*.5,dur2,66+intensity,origin,'theme_reprise' if bar>=12 else 'theme_development',chord,i)
    if bar>=12 and 4 in P['voices']:
     emit(4,pitch-12,t+beat*.5,dur2,48+intensity//2,origin,'octave_theme',chord,i)
  elif bar==16:
   for i,pitch in enumerate([76,74]):emit(0,nearest(pitch+P['climax_lift'],pcs,70,84),t+i*.7,.6,74-i*6,theme[i],'dominant_cadence',chord,i)
   if 1 in P['voices']:emit(1,nearest(theme[0]['pitch']+12,pcs,74,84),t,.3,60+intensity,pools[1][0],'climax_accent',chord)
  elif bar==17:
   emit(0,72,t,1.7,68,theme[-1],'tonic_resolution',chord,3)
   if 4 in P['voices']:
    emit(4,60,t,1.75,54,theme[-1],'tonic_resolution',chord,3)
    emit(4,84,t,.9,46,theme[-1],'tonic_linger',chord,3)
  if 1 in P['voices'] and bar in (4,6,8,10):
   for i,beat in enumerate([.5,1.75,3]):
    src=pools[1][(bar+i)%len(pools[1])]
    pitch=nearest(theme[3-i]['pitch']-12,pcs,55,74)
    emit(1,pitch,t+beat*.5,.32,54+intensity,src,'answer_to_theme',chord,i)
  if 1 in P['voices'] and 13<=bar<=15:
   # rising rhythmic accents increase density toward the revelation climax
   for i,beat in enumerate([.25,1.75]):
    src=pools[1][(bar+i)%len(pools[1])]
    pitch=nearest(theme[3]['pitch']+12+i*2,pcs,72,84)
    emit(1,pitch,t+beat*.5,.26,56+intensity,src,'climax_accent',chord,i)
 # Tie common harmony pitches into continuous pads, preserving their real source parent.
 merged=[]
 for n in sorted(notes,key=lambda n:(n['voice'],n['pitch'],n['start'])):
  last=next((x for x in reversed(merged) if x['voice']==n['voice'] and x['pitch']==n['pitch']),None)
  if n['voice']==3 and last and abs(last['start']+last['duration']-n['start'])<.035:
   last['duration']=round(n['start']+n['duration']-last['start'],6)
  else:merged.append(n)
 catalog=deepcopy(soul['voice_catalog'])
 for v,c in enumerate(catalog):c.update(name_zh=['主旋律','呼应旋律','低音支撑','和声铺底','弦乐主题'][v],program=style['programs'][v],instrument=['长笛' if preset=='nature' else '小提琴','钢琴','大提琴','柔和铺底','弦乐主题'][v])
 return dict(notes=sorted(merged,key=lambda n:(n['start'],n['voice'],n['pitch'])),duration=36.,tempo=120,phases=[dict(start=i*6,end=(i+1)*6,label=f'Chapter {i+1}',roles=['melody','loop']+(['column','support'] if i>=1 else [])+(['accompany'] if i>=4 else [])) for i in range(6)],voice_catalog=catalog,version='progressive-arranged-1.1',preset=preset,preset_name=style['name'],emotions=[dict(id=i,label=l,start=a,end=b) for i,l,a,b in EMOTIONS],mix_gains=[.42,.25,.26,.23,.2],spatial_pan=[-.12,.28,-.12,-.28,.35],theme=[dict(source=n['source'],pitch=n['pitch'],source_point=n['source_point']) for n in theme],features=F,arrangement_params=P)
