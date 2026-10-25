"""Original-image colour statistics and bounded expressive controls (not emotion inference)."""
from pathlib import Path
import numpy as np
from PIL import Image
STRENGTHS={'off':0.,'soft':.25,'mid':.5,'auto':.75,'vivid':1.}

# H3 (correctness): the version string used to be duplicated as a literal
# in this module, in `photo/intake/upgrade_workspaces.py` and in
# `publish_color_ui.py`.  When the engine bumped the version to 1.2 the
# workspace upgrader kept comparing against 1.0, so *every* workspace was
# considered stale and got rebuilt from scratch on every run.
#
# The single source of truth now lives here; every other module imports it.
VERSION = 'color-dna-1.2'
def lab_statistics(rgb,linear):
 # sRGB/D65 -> CIELAB. CIE defines measurement, not these product colour roles.
 xyz=linear@np.array([[.4124564,.2126729,.0193339],[.3575761,.7151522,.1191920],[.1804375,.0721750,.9503041]])
 xyz/=np.array([.95047,1.,1.08883]);delta=6/29
 f=np.where(xyz>delta**3,np.cbrt(xyz),xyz/(3*delta**2)+4/29)
 L=116*f[:,:,1]-16;a=500*(f[:,:,0]-f[:,:,1]);b=200*(f[:,:,1]-f[:,:,2]);chroma=np.hypot(a,b)
 warm=(b>8)&(a>-8)&(chroma>12);cool=((b<-5)|((a<-8)&(b<10)))&(chroma>12)
 return dict(space='CIELAB',whitepoint='D65',L_mean=round(float(L.mean()),3),L_std=round(float(L.std()),3),chroma_mean=round(float(chroma.mean()),3),warm_fraction=round(float(warm.mean()),4),cool_fraction=round(float(cool.mean()),4),classification='Sonify heuristic thresholds, not a CIE emotion standard')

def analyze(image,provenance='original source'):
 im=Image.open(image) if isinstance(image,(str,Path)) else image
 im=im.convert('RGB');im.thumbnail((256,256));rgb=np.asarray(im,dtype=float)/255
 hsv=np.asarray(im.convert('HSV'),dtype=float)/255;s=hsv[:,:,1];v=hsv[:,:,2];h=hsv[:,:,0]*2*np.pi
 # Normalize by chromatic evidence, not total pixels: grey/white pixels cannot cancel hue.
 weights=s*v;mass=float(weights.sum());evidence=float(weights.mean())
 warm=float((np.cos(h-np.pi/6)*weights).sum()/mass) if mass>1e-8 else 0.
 linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
 lum=linear@np.array([.2126,.7152,.0722]);available=evidence>=.035 and float((s>.12).mean())>=.05
 hue=float(np.arctan2((np.sin(h)*weights).sum(),(np.cos(h)*weights).sum())%(2*np.pi))/(2*np.pi) if mass>1e-8 else 0.
 projection=np.cos(h-np.pi/6);masks={'warm':projection>.25,'cool':projection<-.25,'dark':lum<.09}
 yy,xx=np.indices(s.shape);center=1+.5*(1-np.minimum(1,np.hypot((xx/s.shape[1]-.5)*1.4,(yy/s.shape[0]-.5)*1.4)))
 regions=[]
 for role,mask in masks.items():
  chromatic=mask&(s>.12)&(v>.08) if role!='dark' else mask
  coverage=float(chromatic.mean());weight=(weights if role!='dark' else 1-lum)*chromatic*center
  rgb_mean=(rgb*weight[:,:,None]).sum((0,1))/max(float(weight.sum()),1e-8)
  centroid=[float((xx*weight).sum()/max(float(weight.sum()),1e-8))/s.shape[1],float((yy*weight).sum()/max(float(weight.sum()),1e-8))/s.shape[0]]
  # Anchor must be a real pixel in the mask, not an average floating in another colour.
  distance=(xx/s.shape[1]-centroid[0])**2+(yy/s.shape[0]-centroid[1])**2
  iy,ix=np.unravel_index(np.argmin(np.where(chromatic,distance,np.inf)),s.shape)
  regions.append(dict(sample_point=[round((ix+.5)/s.shape[1],4),round((iy+.5)/s.shape[0],4)],sample_hex='#'+''.join(f'{int(x*255):02x}' for x in rgb[iy,ix]),centroid=[round(v,4) for v in centroid],role=role,coverage=round(coverage,4),prominence=round(float(weight.mean()),4),hex='#'+''.join(f'{int(np.clip(x*255,0,255)):02x}' for x in rgb_mean)))
 warm_share=float((weights*masks['warm']).sum()/max(mass,1e-8));cool_share=float((weights*masks['cool']).sum()/max(mass,1e-8))
 chromatic_regions=sorted([q for q in regions if q['role']!='dark'],key=lambda q:-q['prominence'])
 for q in regions:q['hierarchy']='primary' if q==chromatic_regions[0] else 'secondary' if q['role']!='dark' else 'foundation'
 return dict(lab=lab_statistics(rgb,linear),spatial_order=[r['role'] for r in sorted(regions,key=lambda r:r['centroid'][1]) if r['role']!='dark'],role_method='area × chromatic evidence × centrality; not semantic segmentation',regions=regions,warm_share=round(warm_share,4),cool_share=round(cool_share,4),temperature_contrast=round(2*min(warm_share,cool_share),4),dark_share=round(float((lum<.09).mean()),4),hue=round(hue,4),version=VERSION,available=available,warmth=round(warm,4) if available else 0.,luminance=round(float(lum.mean()),4),saturation=round(float(s.mean()),4),contrast=round(float(np.quantile(lum,.95)-np.quantile(lum,.05)),4),chromatic_evidence=round(evidence,4),provenance=provenance,reason='' if available else '色彩信息不足，保持几何编曲')
def expression(color,strength='auto'):
 amount=STRENGTHS.get(strength,.75) if color and color.get('available') else 0.
 c=color or {};warm=c.get('warmth',0);light=c.get('luminance',.5);sat=c.get('saturation',.3);contrast=c.get('contrast',.4)
 L=c.get('lab',{}).get('L_mean',50)/100
 # Creative score, not weather recognition. Desaturated/dark/cool images lean inward.
 energy=max(0.,min(1.,.48*L+.37*sat+.15*(warm+1)/2))
 inward=energy<.43 or (warm<-.25 and L<.62)
 profile='reflective' if inward else 'radiant'
 return dict(profile=profile,profile_label=('沉静 · 小调留白' if inward else '明朗 · 大调流动') if amount>=.5 else '轻度色彩润色',energy=round(energy,4),mode='minor' if inward and amount>=.5 else 'major',key_shift=round((-3 if inward else 2)*amount),rhythm_spread=1+(.26 if inward else -.16)*amount,lightness=L,spatial_order=c.get('spatial_order',['warm','cool']),warm_share=c.get('warm_share',0),cool_share=c.get('cool_share',0),temperature_contrast=c.get('temperature_contrast',0),dark_share=c.get('dark_share',0),setting=strength,amount=amount,register_shift=round((-3 if inward else 3)*amount),legato=1+(.5 if inward else -.22)*amount,accent=contrast*13*amount,harmony_blend=min(.9,abs(warm)*.75*amount),harmony_degree=9 if warm>=0 else 2,harmony_label=(('小调 · 延长呼吸' if inward else '大调 · 清晰脉动') if amount>=.5 else '轻度色彩润色') if amount else '原有和声',richness=sat*amount)
def labels(c):
 if not c or not c.get('available'):return ['色彩信息不足']
 h=c.get('hue',0);family='金橙 / 暖红' if h<.17 or h>.92 else '青绿' if h<.5 else '蓝紫'
 return [family,('暖色倾向' if c['warmth']>.2 else '冷色倾向' if c['warmth']<-.2 else '冷暖均衡'),('明亮' if c['luminance']>.5 else '深沉' if c['luminance']<.22 else '柔和明暗'),('鲜明色彩' if c['saturation']>.45 else '克制色彩'),('强对比' if c['contrast']>.55 else '柔和对比')]
