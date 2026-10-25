"""Publish only reviewed colour UI; stamp hashes for refreshed Progressive music."""
from pathlib import Path
import shutil,json,hashlib
ROOT=Path(__file__).parent

# H3 (correctness): the expected Progressive version used to be a literal
# here.  It now comes from the engine module, so the assertion can never
# drift away from what the engine actually produces.
import sys
sys.path.insert(0, str(ROOT))
from progressive_arrangement import VERSION as PROGRESSIVE_VERSION

def publish():
 hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['color_dna.py','progressive_arrangement.py','progressive_features.py']}
 targets=[ROOT/'dist']
 for folder in (ROOT.parent/'intake/runtime').iterdir():
  path=folder/'workspace/studio/sample5.json'
  if not path.exists():continue
  p=json.loads(path.read_text(encoding='utf8'))
  if p['progressive']['version']!=PROGRESSIVE_VERSION:raise ValueError('Refresh music first: '+folder.name)
  p['progressive_engine_hashes']=hashes
  if p.get('living_color',{}).get('version')=='four-seasons-1.1':p['living_color']['transition']='2-second visual transitions; auto cues 8/16/24 seconds; timeline scrubbing seeks actual audio offset immediately'
  path.write_text(json.dumps(p,ensure_ascii=False,separators=(',',':')),encoding='utf8')
  targets.append(folder/'workspace')
 for t in targets:
  for name in ['studio.html','studio.css','studio.js','soul_experience.js','soul_interaction.js','soul_hero.js','progressive_revelation.js','living_color.js','role_editor.js']:shutil.copyfile(ROOT/'ui'/name,t/name)
 shutil.copyfile(ROOT/'ui/color-evidence.html',ROOT/'dist/color-evidence.html')
 print('Published colour UI to',len(targets),'destinations')
if __name__=='__main__':publish()
