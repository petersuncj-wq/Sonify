"""Original-image colour statistics and bounded expressive controls (not emotion inference)."""
from pathlib import Path
import numpy as np
from PIL import Image
STRENGTHS={'off':0.,'soft':.35,'auto':.75,'vivid':1.}
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
 return dict(hue=round(hue,4),version='color-dna-1.0',available=available,warmth=round(warm,4) if available else 0.,luminance=round(float(lum.mean()),4),saturation=round(float(s.mean()),4),contrast=round(float(np.quantile(lum,.95)-np.quantile(lum,.05)),4),chromatic_evidence=round(evidence,4),provenance=provenance,reason='' if available else '色彩信息不足，保持几何编曲')
def expression(color,strength='auto'):
 amount=STRENGTHS.get(strength,.75) if color and color.get('available') else 0.
 c=color or {};warm=c.get('warmth',0);light=c.get('luminance',.5);sat=c.get('saturation',.3);contrast=c.get('contrast',.4)
 return dict(setting=strength,amount=amount,register_shift=round((light-.4)*5*amount),legato=1+(.45-sat)*.35*amount,accent=contrast*13*amount,harmony_blend=min(.9,abs(warm)*.75*amount),harmony_degree=9 if warm>=0 else 2,harmony_label=('温暖六度' if warm>.2 else '悬浮九度' if warm<-.2 else '清透和声') if amount else '原有和声',richness=sat*amount)
def labels(c):
 if not c or not c.get('available'):return ['色彩信息不足']
 h=c.get('hue',0);family='金橙 / 暖红' if h<.17 or h>.92 else '青绿' if h<.5 else '蓝紫'
 return [family,('暖色倾向' if c['warmth']>.2 else '冷色倾向' if c['warmth']<-.2 else '冷暖均衡'),('明亮' if c['luminance']>.5 else '深沉' if c['luminance']<.22 else '柔和明暗'),('鲜明色彩' if c['saturation']>.45 else '克制色彩'),('强对比' if c['contrast']>.55 else '柔和对比')]
