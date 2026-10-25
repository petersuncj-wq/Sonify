"""Geometry-driven, deterministic 36-second arrangement with four genuine styles."""
from copy import deepcopy
import hashlib,math
import progressive_features as pf
from color_dna import expression,labels as color_labels

# H3 (correctness): the version string was duplicated as a literal in this
# module, in `publish_color_ui.py` and in the reference snapshots.  Bumping
# the engine without updating the assertion in `publish_color_ui.py` broke
# the colour-UI publish step with "Refresh music first".
#
# The single source of truth now lives here.
VERSION = 'progressive-color-2.0'

PRESETS={
 'nature':dict(name='东方自然',programs=[73,10,42,88,48]),
 'chamber':dict(name='西洋小型交响',programs=[40,0,42,48,49]),
 'piano':dict(name='独奏钢琴',programs=[0,0,0,0,0]),
 'strings':dict(name='弦乐叙事',programs=[40,41,42,48,49]),
}
CHORDS={'I':(0,[0,4,7]),'vi':(9,[9,0,4]),'IV':(5,[5,9,0]),'V':(7,[7,11,2]),'ii':(2,[2,5,9])}
EMOTIONS=[('anticipation','悬念',0,6),('emergence','初生',6,14),('expansion','展开',14,24),('revelation','显现',24,32),('resolution','归一',32,36)]

def nearest(p,pcs,lo=36,hi=88):
 return min((n for n in range(lo,hi+1) if n%12 in pcs),key=lambda n:(abs(n-p),n))

def contour_theme(source,units,dna,preset):
 by_source={}
 for n in source:
  if n['voice']==0:by_source.setdefault(n['source'],n)
 candidates=[u for u in (units or []) if u['id'] in by_source and len(u.get('points',[]))>1]
 if not candidates:
  lead=[n for n in source if n['voice']==0] or source
  return [deepcopy(lead[i%len(lead)]) for i in range(dna['theme_count'])]
 path=max(candidates,key=lambda u:u['length']*(.7+.3*u.get('centrality',.5)))
 points=path['points'];distance=[0.]
 for a,b in zip(points,points[1:]):distance.append(distance[-1]+math.hypot(b[0]-a[0],b[1]-a[1]))
 lo=min(q[1] for q in points);hi=max(q[1] for q in points);mid=(hi+lo)/2
 pcs=[0,2,4,7,9] if preset=='nature' else [0,2,4,5,7,9,11]
 ladder=[n for n in range(60,87) if (n-dna['key_pc'])%12 in pcs]
 out=[]
 for i in range(dna['theme_count']):
  target=distance[-1]*i/max(1,dna['theme_count']-1);j=min(range(len(points)),key=lambda j:abs(distance[j]-target));point=points[j]
  raw=len(ladder)*.48+(mid-point[1])/max(.035,hi-lo)*min(4.5,len(ladder)*.4)+(0.5-mid)*3
  n=deepcopy(by_source[path['id']]);n.update(source_point=list(point),pitch=ladder[max(0,min(len(ladder)-1,round(raw)))])
  n['calculation']=dict(n.get('calculation',{}),contour_point=j,contour_degree=round(raw,4),mapping='real contour height -> scale degree')
  out.append(n)
 return out

def arrange(soul,preset='nature',units=None,color_dna=None,color_strength='auto',season=None,identity_mode=False):
 source=soul['notes']
 if not source:raise ValueError('No geometric material')
 F=pf.compute(units,soul);dna=pf.musical_dna(F,preset);key=dna['key_pc'];style=deepcopy(PRESETS[preset])
 F['color']=color_dna
 color=expression(color_dna,color_strength);dna['color_expression']=color
 if season:
  color['register_shift']+=season['register'];color['legato']*=season['legato']
  dna['legato']*=season['legato'];dna['seasonal']=deepcopy(season)
 geometry_key=key;key=(key+color['key_shift'])%12
 reflective=color['profile']=='reflective'
 if color['amount']>=.5 and preset=='nature':style['programs']=[73,46,42,89,48] if reflective else [75,46,42,48,73]
 if color['amount']>=.5 and preset=='chamber':style['programs']=[71,0,42,48,73] if reflective else [40,46,42,48,73]
 dna['bass_entry']=max(2,dna['bass_entry']-2*round(color['dark_share']*8*color['amount']))
 theme=contour_theme(source,units,dna,preset)
 if identity_mode:
  from identity_motif import extract
  theme=extract(source,units,dna,preset) or theme
 base_steps=[0,2,4,7,9] if preset=='nature' else [0,2,4,5,7,9,11]
 steps=([0,3,5,7,10] if preset=='nature' else [0,2,3,5,7,8,10]) if color['mode']=='minor' else base_steps
 scale=[(p+key)%12 for p in steps]
 # Keep sampled contour degrees/source points; revoice their musical realization.
 def reinterpret(p):
  if not color['amount']:return p
  degree=base_steps.index((p-geometry_key)%12)
  return p+((key-geometry_key+6)%12-6)+steps[degree]-base_steps[degree]+color['register_shift']
 for i,n in enumerate(theme):
  lo,hi=(max(60,theme[i-1]['pitch']-5),min(87,theme[i-1]['pitch']+5)) if i else (60,87)
  n['pitch']=nearest(reinterpret(n['pitch']),scale,lo,hi)
  n['calculation']['color_register_shift']=color['register_shift']
  n['calculation']['phrase_step_limit']=5
 pools={v:[n for n in source if n['voice']==v] or source for v in range(5)}
 patterns={'flow':['I','vi','IV','V'],'vertical':['I','IV','ii','V'],'angular':['vi','IV','I','V']}
 progression=(patterns[dna['profile']]*5)[:18];progression[0]=progression[12]=progression[17]='I';progression[16]='V'
 if color['amount']>=.5:progression=((['I','IV','vi','V'] if reflective else ['I','IV','I','V'])*5)[:18];progression[12]=progression[17]='I';progression[16]='V'
 if preset=='chamber':progression[7]=progression[11]='ii';progression[15]='V'
 if preset=='strings':progression=[progression[(b//2)*2] for b in range(18)];progression[12]=progression[17]='I';progression[16]='V'
 notes=[]
 def emit(v,pitch,start,duration,velocity,origin,role,chord,index=None):
  if v not in dna['voices']:return
  if season and role in ('original_theme','theme_reprise','theme_development','octave_theme','season_ascending_ornament'):
   duration=min(duration,max(.04,(math.floor(start/4)+1)*4-.08-start))
  velocity+=color['accent']*(1 if index is not None and index%3==0 else -.35)
  if v in (1,4):duration*=color['legato']
  n=deepcopy(origin);n.update(id=hashlib.sha256(f'{preset}-{v}-{pitch}-{start}-{origin["source"]}-{len(notes)}'.encode()).hexdigest()[:16],voice=v,voice_id=v,program=style['programs'][v],pitch=int(pitch),start=round(start,6),duration=round(max(.04,min(duration,35.8-start)),6),velocity=max(25,min(105,int(velocity+dna.get('color_velocity',0)))),arrangement_role=role,parent_note_id=origin['id'],theme_index=index,role=role,note_role=role,phrase=f'reveal-{int(start//2)}-{v}',section=next(e[0] for e in EMOTIONS if e[2]<=start<e[3]))
  n['calculation']=dict(origin.get('calculation',{}),arrangement=role,chord=chord,key_pc=key,preset=preset,source_pitch=origin['pitch'])
  if start<35.8:notes.append(n)
 prev=[55+key,64+key+color['register_shift']]
 for bar,chord in enumerate(progression):
  t=bar*2;root,pcs=CHORDS[chord]
  if color['mode']=='minor':root,pcs={'I':(0,[0,3,7]),'vi':(8,[8,0,3]),'IV':(5,[5,8,0]),'V':(7,[7,11,2]),'ii':(2,[2,5,8])}[chord]
  root=(root+key)%12;pcs=[(p+key)%12 for p in pcs]
  phase=next(e[0] for e in EMOTIONS if e[2]<=t<e[3]);intensity={'anticipation':0,'emergence':8,'expansion':18,'revelation':28,'resolution':7}[phase]
  harmony_pcs=[root,(root+7)%12] if preset=='nature' else pcs
  voicing=[]
  for old in prev:
   voicing.append(min([p for p in range(50,74) if p%12 in harmony_pcs and p not in voicing],key=lambda p:abs(p-old)))
  if color['amount'] and bar not in (16,17):
   # Warm and cool remain separate. Alternate an upper ninth and a warm sixth,
   # rather than averaging opposite colours into a neutral chord.
   cool=(bar%2==1 and color['cool_share']>.1) or color['cool_share']>color['warm_share']*1.5
   degree=2 if cool else 9
   tint=nearest(60+(key+degree)%12,scale,48,84)%12
   register=65+round((color['cool_share'] if cool else color['warm_share'])*7*color['amount'])
   target=nearest(register,[tint],55,82)
   voicing[-1]=nearest(voicing[-1]+(target-voicing[-1])*color['amount'],scale,50,82)
  prev=voicing
  for j,pitch in enumerate(voicing):
   # Piano uses broken voicings, strings sustain; nature leaves open fifths.
   delay=j*.22 if preset=='piano' else 0
   emit(3,pitch,t+delay,1.7 if preset=='piano' else 1.99,30+intensity,pools[3][bar%len(pools[3])],'broken_harmony' if preset=='piano' else 'voice_led_harmony',chord)
  if t>=dna['bass_entry']:
   bass=nearest((40 if dna['profile']=='vertical' else 45)-round(color['dark_share']*5*color['amount']),[root],36,55)
   emit(2,bass,t,1.85,48+intensity,pools[2][bar%len(pools[2])],'root_support',chord)
  # A whole contour phrase spans two bars, and returns unchanged in pitch at 24s.
  if bar in (season['phrase_bars'] if season else (0,4,7,10,12,14)):
   for i,origin in enumerate(theme):
    horizontal=[abs(theme[k+1]['source_point'][0]-theme[k]['source_point'][0])+.05 for k in range(len(theme)-1)]
    if identity_mode:horizontal=[n.get('calculation',{}).get('rhythm_weight',1) for n in theme[:-1]]
    weights=horizontal or [1];prefix=sum(weights[:i]);fraction=.86*prefix/sum(weights)
    if preset=='chamber':fraction=i/len(theme)*.92
    elif preset=='piano':fraction=i/len(theme)*.9
    spread=color['rhythm_spread'] if color['amount'] else 1
    onset=t+(1.4+fraction*min(2.4,2.2*spread) if bar==0 else .15+fraction*min(4.,3.5*spread))
    gap=(3.5/max(4,len(theme)))*dna['legato']*(color['legato'] if color['amount'] else 1);pitch=origin['pitch']
    if bar not in (0,12):pitch=nearest(pitch+(2 if bar>=10 else 0),pcs,60,87)
    emit(0,pitch,onset,min(1.1,gap),62+intensity,origin,'original_theme' if bar==0 else 'theme_reprise' if bar==12 else 'theme_development',chord,i)
    if season and season['ornaments'] and i==1 and bar in (4,6,12):
     emit(1 if preset not in ('piano','strings') else 3,nearest(pitch+2,scale,60,87),max(t,onset-.16),.12,43+intensity//2,origin,'season_ascending_ornament',chord,i)
    if bar>=12 and preset in ('nature','chamber','strings'):
     emit(4,pitch-12,onset,min(1.35,gap),49+intensity//2,origin,'octave_theme',chord,i)
  response_bars=(3,4,5,6,7,8,9,10,11,12,13,14,15) if color['amount']>=.5 and color['temperature_contrast']>.25 else (5,6,8,9,11,13,15)
  if season:response_bars=(6,10,14) if season['density']<.6 else (3,4,5,6,7,8,9,10,11,12,13,14,15) if season['density']>1 else (5,8,11,14)
  if t>=dna['response_entry'] and bar in response_bars:
   pulse=dna['pulse'];pulse=pulse[:2] if preset=='nature' and F['density']<.65 else pulse
   if preset=='strings':pulse=[1,3]
   if color['amount']>=.5:pulse=[1,3] if reflective else [.5,1.5,2.5,3.5]
   if season:pulse=season['pulse']
   for i,beat in enumerate(pulse):
    v=4 if preset=='strings' else 3 if preset=='piano' else 1
    origin=pools[1][(bar+i)%len(pools[1])];reference=theme[(len(theme)-1-i)%len(theme)]['pitch']-12
    pitch=nearest(reference+(i%2)*2,pcs,50,78)
    cool_color=False
    if color['amount']:
     cool_color=(i%2==(0 if color['spatial_order'][0]=='cool' else 1) and color['cool_share']>.08) or color['warm_share']<.1
     v=(3 if preset=='piano' else 4) if cool_color else (3 if preset in ('piano','strings') else 1)
     target=pitch+round((12+(color['lightness']-.5)*6)*color['amount']) if cool_color else pitch
     pitch=nearest(target,scale,64 if cool_color else 50,87 if cool_color else 72)
    emit(v,pitch,t+beat*.5,.6 if preset=='strings' else .22 if preset=='chamber' else .36,42+intensity,origin,('color_cool_response' if cool_color else 'color_warm_response') if color['amount'] else 'imitative_answer' if preset=='chamber' else 'repeated_pattern',chord,i)
  if bar==16:
   if color['mode']=='minor':
    lead_tone=nearest(72+key,[key],65,87)-1
    emit(0,lead_tone,t,.9,72,theme[-2],'dominant_cadence',chord)
   else:
    emit(0,nearest(74+key,pcs,65,87),t,.9,72,theme[-2],'dominant_cadence',chord)
  if bar==17:
   tonic=nearest(72+key,[key],65,87)
   emit(0,tonic,t,1.7,65,theme[-1],'tonic_resolution',chord)
   emit(4,tonic-12,t,1.7,48,theme[-1],'tonic_resolution',chord)
 # Keep theme/bass first when dense response and sustained harmony overlap.
 priority={0:0,2:1,3:2,4:3,1:4};accepted=[]
 for n in sorted(notes,key=lambda n:(priority[n['voice']],n['start'],n['pitch'])):
  events=[(n['start'],1),(n['start']+n['duration'],-1)]
  for old in accepted:
   if old['start']<n['start']+n['duration'] and old['start']+old['duration']>n['start']:
    events.extend([(max(n['start'],old['start']),1),(min(n['start']+n['duration'],old['start']+old['duration']),-1)])
  count=peak=0
  for _,d in sorted(events):count+=d;peak=max(peak,count)
  if peak<=6:accepted.append(n)
 mix=[.42,.24,.27,.23,.2]
 if color['amount']:
  warm_voice=3 if preset in ('piano','strings') else 1;cold_voice=3 if preset=='piano' else 4
  mix[warm_voice]=mix[warm_voice]*(1-color['amount'])+(.16+.32*color['warm_share'])*color['amount']
  if cold_voice!=warm_voice:mix[cold_voice]=mix[cold_voice]*(1-color['amount'])+(.12+.32*color['cool_share'])*color['amount']
  mix[2]*=1+color['dark_share']*.8*color['amount']
 catalog=deepcopy(soul['voice_catalog'])
 labels=['主旋律','呼应动机','低音支撑','和声织体','弦乐层次']
 instruments={'nature':['长笛','音乐盒','大提琴','氛围 Pad','弦乐'],'chamber':['小提琴','钢琴','大提琴','弦乐','弦乐'],'piano':['钢琴']*5,'strings':['小提琴','中提琴','大提琴','弦乐','弦乐']}
 if color['amount']:
  labels[1]='暖色呼应';labels[4]='冷色辉光'
  if color['amount']>=.5:
   if preset=='nature':instruments[preset]=['长笛' if reflective else '排箫','竖琴','大提琴','暖色 Pad' if reflective else '弦乐','弦乐' if reflective else '长笛']
   elif preset=='chamber':instruments[preset]=['单簧管' if reflective else '小提琴','钢琴' if reflective else '竖琴','大提琴','弦乐','长笛']
 for v,c in enumerate(catalog):c.update(name_zh=labels[v],program=style['programs'][v],instrument=instruments[preset][v])
 return dict(notes=sorted(accepted,key=lambda n:(n['start'],n['voice'],n['pitch'])),duration=36.,tempo=120,phases=[dict(start=i*6,end=(i+1)*6,label=f'Chapter {i+1}',roles=['melody','column','support','loop','accompany']) for i in range(6)],voice_catalog=catalog,color_dna=color_dna,color_labels=color_labels(color_dna),color_strength=color_strength,version=VERSION,preset=preset,preset_name=style['name'],emotions=[dict(id=i,label=l,start=a,end=b) for i,l,a,b in EMOTIONS],mix_gains=mix,spatial_pan=[-.12,.28,-.12,-.28,.35],theme=[dict(source=n['source'],pitch=n['pitch'],source_point=n['source_point']) for n in theme],features=F,arrangement_params=dna,key_pc=key,scale_pcs=scale,geometry_key_pc=geometry_key,source_method='arc-spaced vertices of principal source contour')
