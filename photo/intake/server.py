"""Independent Photo intake with a loopback host console and paired LAN upload."""
from pathlib import Path
import base64
import copy
import io
import json
import os
import sys
import threading
import subprocess
import time
import uuid
import socket
import secrets
import ipaddress
from http.cookies import SimpleCookie
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, urlencode, parse_qs, unquote
from urllib.request import Request, urlopen, build_opener, ProxyHandler
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent
EXPERIMENT = ROOT.parent / 'experiment'
sys.path.insert(0, str(EXPERIMENT / 'vendor'))
sys.path.insert(0, str(ROOT / 'vendor'))
from PIL import Image, ImageOps, UnidentifiedImageError
import numpy as np
import cv2
import seedream
from community import Community
from titles import sanitize_title, TitleError

MAX_BYTES = 12 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 24_000_000


class RateLimiter:
    """Simple sliding-window rate limiter (H6, security).

    The paid Seedream API can be triggered by *any* request that reaches
    `POST /api/jobs` (or `/api/jobs/batch`).  Without a limit, a single
    client — or an accidental retry loop — can burn the whole daily quota
    in seconds.

    The limiter counts requests per client key inside a rolling window and
    rejects the ones above the budget.  It is intentionally dependency
    free and degrades gracefully: if anything goes wrong the request is
    *allowed* (availability beats protection here, and the queue
    semaphore in `Pipeline.create()` is the hard backstop).
    """

    def __init__(self, limit: int = 12, window: float = 60.0):
        self.limit = max(1, int(limit))
        self.window = float(window)
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key, now=None):
        """True when the request may proceed."""
        try:
            now = time.monotonic() if now is None else now
            with self._lock:
                hits = [t for t in self._hits.get(key, []) if now - t < self.window]
                if len(hits) >= self.limit:
                    self._hits[key] = hits
                    return False
                hits.append(now)
                self._hits[key] = hits
                # Opportunistic cleanup so the dict cannot grow forever.
                if len(self._hits) > 4096:
                    for stale in [k for k, v in self._hits.items()
                                  if not v or now - v[-1] >= self.window]:
                        self._hits.pop(stale, None)
                return True
        except Exception:
            return True


class Pipeline:
    def __init__(self, runtime=None, config=None):
        self.runtime = Path(runtime or ROOT / 'runtime')
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.config = config if config is not None else self.load_config()
        self.pool = ThreadPoolExecutor(max_workers=5)
        self.lock = threading.Lock()
        self.music_lock = threading.Lock()
        self.jobs = {}
        self.slots = threading.BoundedSemaphore(8)
        # H2: in-flight on-demand Progressive renders, keyed by
        # "<job>:<preset>:<strength>".  A lock is created lazily so that
        # two browsers asking for the same variant wait for one render
        # instead of starting two.
        self.pending_variants = {}
        self.share = None
        self.community = Community(self.runtime)
        for file in self.runtime.glob('*/job.json'):
            try:
                job = json.loads(file.read_text(encoding='utf-8'))
                if job['status'] not in ('completed', 'failed'):
                    job.update(status='failed', stage='服务重启，请重新提交', error='任务因服务重启中断。')
                if job.get('artistic_status') in ('queued', 'processing'):
                    job.update(artistic_status='failed', artistic_error='艺术生成因服务重启中断。')
                if job.get('music_status') == 'processing':
                    job.update(music_status='failed')
                file.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
                self.jobs[job['id']] = job
            except (ValueError, KeyError, OSError):
                pass

    @staticmethod
    def load_config():
        path = ROOT / 'config.local.json'
        return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}

    def soul_style(self):
        """The harmony style used for new Soul compositions (M8).

        `config.local.json` may set `"soul_style": "east"` (default) or
        `"west"` (functional major-key harmony).  An unknown value is
        ignored rather than failing the upload, and the reason is logged.
        """
        value = str(self.config.get('soul_style', 'east') or 'east').strip().lower()
        if value not in ('east', 'west'):
            print(f'[intake] unknown soul_style {value!r}; falling back to "east"', flush=True)
            return 'east'
        return value

    def availability(self):
        c = self.config
        return {'local': True, 'supplied': True,
                'comfy': bool(c.get('comfy_url') and c.get('comfy_workflow') and c.get('comfy_input_node') and c.get('comfy_output_node')),
                'artistic': bool(c.get('ark_model') and os.environ.get('ARK_API_KEY')),
                'seedream': bool(seedream.key(ROOT))}

    def snapshot(self, jid):
        with self.lock:
            return copy.deepcopy(self.jobs[jid])

    def update(self, jid, **values):
        """Merge `values` into the job record and persist it.

        H5 (robustness): the original implementation let an `OSError` from
        the disk write escape.  Because `update()` is called from the
        pipeline's own error handler, a transient disk problem (full disk,
        file locked by an antivirus scanner, network share hiccup) could
        turn a *recoverable* failure into an unhandled exception — and the
        job then stayed in `processing` forever.

        The in-memory record is always updated first (so the API keeps
        working), and a failing write is logged and retried once.  The
        write is atomic: the JSON is written to a temporary file and then
        replaced, so a crash mid-write cannot leave a truncated job file.
        """
        with self.lock:
            self.jobs[jid].update(values, updated_at=time.time())
            target = self.runtime / jid / 'job.json'
            payload = json.dumps(self.jobs[jid], ensure_ascii=False, indent=2)
        for attempt in (0, 1):
            try:
                tmp = target.with_suffix('.json.tmp')
                tmp.write_text(payload, encoding='utf-8')
                tmp.replace(target)
                return
            except OSError:
                # A transient disk error is worth one retry; after that the
                # job keeps running from the in-memory record.
                if attempt:
                    print(f'[intake] warning: could not persist {target}', flush=True)
                else:
                    time.sleep(0.2)

    @staticmethod
    def decode(raw):
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError('请选择不超过 12 MB 的 JPG 或 PNG 图片。')
        try:
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in ('PNG', 'JPEG'):
                    raise ValueError('只支持 JPG 和 PNG 图片。')
                im.load()
                im = ImageOps.exif_transpose(im)
                if 'A' in im.getbands():
                    rgba = im.convert('RGBA')
                    bg = Image.new('RGBA', im.size, 'white')
                    im = Image.alpha_composite(bg, rgba)
                im = im.convert('RGB')
                im.thumbnail((2048, 2048))
                return im
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ValueError('图片损坏或像素过大，请换一张图片。') from None

    def create(self, raw, provider, artistic=False, guest_owner=None, supplied_lineart=None, supplied_method='traditional'):
        if provider not in ('local', 'comfy', 'seedream', 'supplied'):
            raise ValueError('未知的结构处理方式。')
        if provider == 'supplied' and guest_owner:
            raise ValueError('手机上传不支持自定义线稿。')
        if supplied_method not in ('traditional', 'slimsam'):
            raise ValueError('supplied_method 必须为 traditional 或 slimsam。')
        ready = self.availability()
        if provider != 'supplied' and (not ready[provider] or (artistic and provider != 'seedream' and not ready['artistic'])):
            raise ValueError('豆包或所选模型服务尚未配置，请联系现场工作人员检查服务。')
        im = self.decode(raw)
        lineart_im = None
        if provider == 'supplied':
            if not supplied_lineart:
                raise ValueError('supplied provider 需要 supplied_lineart 参数。')
            lineart_im = self.decode(supplied_lineart)
            # 允许长宽比差异小于1%时按原图尺寸重采样
            orig_ratio = im.width / im.height
            line_ratio = lineart_im.width / lineart_im.height
            ratio_diff = abs(orig_ratio - line_ratio) / orig_ratio
            if ratio_diff < 0.01:
                if lineart_im.size != im.size:
                    lineart_im = lineart_im.resize(im.size, Image.Resampling.LANCZOS)
            elif lineart_im.size != im.size:
                raise ValueError('线稿尺寸或长宽比与原图不符。')
        if not self.slots.acquire(blocking=False):
            raise ValueError('任务队列已满，请稍后再试。')
        # H5 (robustness): from here on the semaphore is held.  Every exit
        # path must release it again, otherwise a single failure (disk full,
        # invalid PNG, pool rejection) permanently burns one of the eight
        # queue slots and the service eventually stops accepting uploads.
        try:
            jid = uuid.uuid4().hex
            folder = self.runtime / jid
            folder.mkdir()
            im.save(folder / 'original.png')
            if lineart_im:
                lineart_im.save(folder / 'artistic.png')
            job = dict(id=jid, status='queued', stage='等待处理', created_at=time.time(), provider=provider,
                       supplied_method=supplied_method if provider == 'supplied' else None,
                       artistic_requested=bool(artistic or provider == 'supplied'),
                       artistic_status='completed' if provider == 'supplied' else ('queued' if artistic else 'disabled'),
                       original=f'/media/{jid}/original.png',
                       structural=f'/media/{jid}/structural.png' if provider == 'supplied' else None,
                       artistic=f'/media/{jid}/artistic.png' if provider == 'supplied' else None,
                       geometry=None, handoff=None, error=None, music_status='not_started',
                       title='')
            if provider == 'seedream':
                job.update(artistic_requested=True,artistic_status='queued',model=self.config.get('ark_model') or seedream.DEFAULT_MODEL)
            if guest_owner:
                job.update(guest_owner=guest_owner, submission='phone')
            with self.lock:
                self.jobs[jid] = job
            self.update(jid)
        except Exception:
            self.slots.release()
            raise
        # `run()` owns the semaphore from here on and releases it in its
        # own `finally:` block.
        self.pool.submit(self.run, jid)
        return self.snapshot(jid)

    def rename(self, jid, title):
        """Attach a human-readable name to one job and persist it.

        The title is validated against a strict character whitelist: it may
        contain letters, digits, CJK, spaces and a small set of harmless
        punctuation marks, but no control characters, no bidirectional
        override characters (which could spoof the list rendering) and no
        markup characters.
        """
        job = self.snapshot(jid)
        if not job:
            raise KeyError(jid)
        clean = sanitize_title(title)
        self.update(jid, title=clean)
        return self.snapshot(jid)

    def request(self, url, payload=None, headers=None):
        body = json.dumps(payload).encode() if payload is not None else None
        h = {'Content-Type': 'application/json', **(headers or {})}
        open_request = build_opener(ProxyHandler({})).open if url.startswith('https://ark.cn-beijing.volces.com') else urlopen
        with open_request(Request(url, data=body, headers=h), timeout=min(240, self.config.get('timeout_seconds', 180))) as r:
            data = r.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024:
            raise ValueError('服务返回的文件过大。')
        return data

    def fallback_local(self, jid):
        job = self.snapshot(jid)
        if job.get('provider') != 'seedream' or job.get('status') != 'failed' or job.get('artistic_status') != 'failed' or job.get('artistic'):
            raise ValueError('只有豆包未能返回线稿的失败任务可以尝试 OpenCV。')
        result = self.create((self.runtime / jid / 'original.png').read_bytes(), 'local', guest_owner=job.get('guest_owner'))
        self.update(result['id'], fallback_from=jid)
        return self.snapshot(result['id'])

    def retry_music(self, jid):
        job=self.snapshot(jid)
        folder=self.runtime/jid
        if job.get('music_status')!='failed' or not (folder/'skeleton.png').exists():
            raise ValueError('该任务没有可复用的音乐生成输入。')
        if not self.slots.acquire(blocking=False):
            raise ValueError('队列已满，请稍后再试。')
        self.update(jid,status='processing',music_status='processing',music_error=None,error=None,stage='等待重新生成音乐')
        def rebuild():
            try:
                with self.music_lock:
                    self.update(jid,stage='正在复用线稿生成音乐')
                    result=subprocess.run([sys.executable,str(ROOT/'bridge.py'),str(folder),self.soul_style()],capture_output=True,timeout=900,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if result.returncode:
                    (folder/'bridge.log').write_bytes(result.stdout+result.stderr)
                    raise ValueError('音乐重新生成未完成，线稿仍已保留。')
                self.update(jid,status='completed',music_status='completed',workspace=f'/works/{jid}/studio.html',stage='作品准备完成')
            except Exception:
                self.update(jid,status='completed',music_status='failed',music_error='音乐重新生成未完成，线稿仍已保留。',stage='结构准备完成')
            finally:
                try:
                    manifest=folder/'handoff.json'
                    if manifest.exists():
                        data=json.loads(manifest.read_text(encoding='utf-8'));final=self.snapshot(jid)
                        data.update(music_status=final['music_status'],workspace=final.get('workspace'))
                        manifest.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
                finally:
                    self.slots.release()
        self.pool.submit(rebuild)
        return self.snapshot(jid)

    def render_progressive(self, jid, preset, strength):
        """H2: render one Progressive variant on demand.

        The initial build only renders the default combination
        (`nature` / `auto`).  When a visitor picks another style or
        colour strength in the studio UI, the browser asks for it here and
        the server renders just that combination.

        The request is idempotent: an already rendered combination is
        reported back immediately.  Concurrent requests for the *same*
        combination share one render (the second one finds the files in
        place), and requests for *different* combinations are serialised
        through `music_lock`, because the SoundFont pool and the temporary
        stem files are shared resources.
        """
        job = self.snapshot(jid)
        folder = self.runtime / jid
        manifest = folder / 'workspace' / 'studio' / 'sample5.json'
        if not manifest.is_file():
            raise ValueError('该作品还没有生成音乐，无法切换风格。')
        payload = json.loads(manifest.read_text(encoding='utf-8'))
        colors = payload.get('progressive_colors') or {}
        if preset not in colors:
            raise ValueError('未知的音乐风格。')
        available = colors[preset]
        if strength not in available:
            raise ValueError('该作品没有这个色彩强度。')
        rendered = [tuple(x) for x in payload.get('rendered_variants', [])]
        if (preset, strength) in rendered:
            return dict(preset=preset, strength=strength, cached=True)
        # Guard against two browsers requesting the same variant at once.
        key = f'{jid}:{preset}:{strength}'
        with self.lock:
            pending = self.pending_variants.get(key)
            if pending is None:
                pending = self.lock_for_variant(key)
        try:
            with self.music_lock:
                # Re-check: another request may have finished meanwhile.
                if manifest.is_file():
                    payload = json.loads(manifest.read_text(encoding='utf-8'))
                    if (preset, strength) in [tuple(x) for x in payload.get('rendered_variants', [])]:
                        return dict(preset=preset, strength=strength, cached=True)
                completed = subprocess.run(
                    [sys.executable, str(ROOT / 'render_variant.py'), str(folder), preset, strength],
                    capture_output=True, timeout=900,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if completed.returncode:
                    (folder / 'render.log').write_bytes(completed.stdout + completed.stderr)
                    raise ValueError('这个音乐风格生成失败，请稍后再试。')
        finally:
            with self.lock:
                self.pending_variants.pop(key, None)
        return dict(preset=preset, strength=strength, cached=False)

    def lock_for_variant(self, key):
        """Return (and remember) the lock that guards one variant."""
        lock = threading.Lock()
        self.pending_variants[key] = lock
        return lock

    def comfy(self, jid):
        c = self.config
        url = c['comfy_url'].rstrip('/')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or parsed.port == 8190:
            raise ValueError('请配置专用 ComfyUI 地址；现有 8190 工作台受保护。')
        workflow_path = Path(c['comfy_workflow'])
        if not workflow_path.is_absolute():
            workflow_path = ROOT / workflow_path
        workflow = json.loads(workflow_path.read_text(encoding='utf-8-sig'))
        inode, onode = str(c['comfy_input_node']), str(c['comfy_output_node'])
        if inode not in workflow or onode not in workflow or workflow[inode].get('class_type') != 'LoadImage':
            raise ValueError('工作流需为 API 格式，并配置 LoadImage 输入与保存图片的输出节点。')
        boundary = uuid.uuid4().hex
        raw = (self.runtime / jid / 'original.png').read_bytes()
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{jid}.png"\r\nContent-Type: image/png\r\n\r\n'.encode() + raw + f'\r\n--{boundary}--\r\n'.encode())
        req = Request(url + '/upload/image', data=body, headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
        with urlopen(req, timeout=30) as response:
            uploaded = json.load(response)
        workflow[inode]['inputs']['image'] = '/'.join(filter(None, [uploaded.get('subfolder'), uploaded['name']]))
        result = json.loads(self.request(url + '/prompt', {'prompt': workflow, 'client_id': jid}))
        if result.get('node_errors') or not result.get('prompt_id'):
            raise ValueError('ComfyUI 拒绝工作流，请检查节点和模型。')
        pid = result['prompt_id']
        self.update(jid, prompt_id=pid, stage='工作流已提交，等待结构线稿')
        deadline = time.monotonic() + c.get('timeout_seconds', 240)
        while time.monotonic() < deadline:
            history = json.loads(self.request(url + '/history/' + pid)).get(pid)
            if history:
                if history.get('status', {}).get('status_str') == 'error':
                    raise ValueError('ComfyUI 工作流执行失败，请检查专用工作台。')
                images = history.get('outputs', {}).get(onode, {}).get('images', [])
                if images:
                    item = images[0]
                    image = self.decode(self.request(url + '/view?' + urlencode({k: item[k] for k in ('filename', 'subfolder', 'type') if k in item})))
                    image.save(self.runtime / jid / 'structural.png')
                    return
                if history.get('status', {}).get('completed'):
                    raise ValueError('指定输出节点没有返回图片。')
            time.sleep(1)
        raise ValueError('结构生成超时；远端任务可能仍在运行，请在专用工作台检查。')

    def artistic(self, jid):
        self.update(jid, artistic_status='processing')
        try:
            encoded = base64.b64encode((self.runtime / jid / 'original.png').read_bytes()).decode()
            response = json.loads(self.request('https://ark.cn-beijing.volces.com/api/v3/images/generations',
                {'model': self.config['ark_model'], 'image': 'data:image/png;base64,' + encoded,
                 'prompt': '将输入图片转换为清新克制的艺术线稿。保留主体、主要轮廓、构图和空间关系，弱化阴影与噪声，不添加物体。若原始画面中出现水印或文字，请自动剔除，并依据周围结构自然补全被遮挡的画面，不添加替代文字。',
                 'size': self.config.get('ark_size', '1024x1024'), 'response_format': 'b64_json', 'watermark': True},
                {'Authorization': 'Bearer ' + os.environ['ARK_API_KEY']}))
            # Base64 output keeps transient remote asset URLs out of the result contract.
            im = self.decode(base64.b64decode(response['data'][0]['b64_json'], validate=True))
            im.save(self.runtime / jid / 'artistic.png')
            self.update(jid, artistic_status='completed', artistic=f'/media/{jid}/artistic.png')
        except Exception:
            self.update(jid, artistic_status='failed', artistic_error='艺术线稿生成失败，请检查云服务配置、额度或网络；结构处理仍可继续。')

    def run(self, jid):
        job = self.snapshot(jid)
        art_thread = None
        api_started = None
        try:
            self.update(jid, status='processing', stage='正在提取视觉结构')
            if job['artistic_requested'] and job['provider'] not in ('seedream', 'supplied'):
                art_thread = threading.Thread(target=self.artistic, args=(jid,), daemon=True)
                art_thread.start()
            folder = self.runtime / jid
            if job['provider'] == 'seedream':
                self.update(jid,stage='正在生成豆包结构线稿',artistic_status='processing')
                api_started=time.perf_counter()
                raw,metadata=seedream.generate((folder/'original.png').read_bytes(),self.config,ROOT,self.request,
                    lambda n:self.update(jid,api_attempt=n))
                im=self.decode(raw)
                im.save(folder/'artistic.png')
                # Preserve display output; normalize a separate analysis image.
                gray=ImageOps.autocontrast(im.convert('L'),cutoff=.3)
                gray.thumbnail((840,840));gray.save(folder/'structural.png')
                self.update(jid,artistic=f'/media/{jid}/artistic.png',artistic_status='completed',api_metrics=metadata)
            elif job['provider'] == 'comfy':
                self.comfy(jid)
            elif job['provider'] == 'supplied':
                # User-supplied lineart already saved in create(). Normalize for geometry.
                im = Image.open(folder / 'artistic.png').convert('L')
                gray = ImageOps.autocontrast(im, cutoff=.3)
                gray.thumbnail((840, 840))
                gray.save(folder / 'structural.png')
                self.update(jid, structural=f'/media/{jid}/structural.png', stage='正在使用本地精细线稿')
            else:
                im = Image.open(folder / 'original.png').convert('L')
                im.thumbnail((840, 840))
                gray = np.array(im)
                edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 60, 150)
                Image.fromarray(255 - edges).save(folder / 'structural.png')
            self.update(jid, structural=f'/media/{jid}/structural.png', stage='正在解析几何并准备接入数据')
            # Reuse only the deterministic extractor. No existing build scripts or outputs run.
            import importlib.util
            spec = importlib.util.spec_from_file_location('intake_existing_geometry', EXPERIMENT / 'run.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            im = Image.open(folder / 'structural.png').convert('L')
            im.thumbnail((640, 840))
            mask, skeleton, paths, groups, stats = module.extract(np.array(im))
            Image.fromarray(skeleton).save(folder / 'skeleton.png')
            geometry = dict(schema_version='sonify.intake.geometry.v1', job_id=jid, source='structural.png',
                            width=im.width, height=im.height, paths=paths, repeat_groups=groups, stats=stats)
            (folder / 'geometry.json').write_text(json.dumps(geometry, ensure_ascii=False), encoding='utf-8')
            handoff = dict(schema_version='sonify.intake.handoff.v1', job_id=jid,
                original=job['original'], structural=f'/media/{jid}/structural.png',
                geometry=f'/media/{jid}/geometry.json',
                supplied_method=job.get('supplied_method'),
                coordinate_space='normalized_structural_image', aligned_to_artistic=False,
                target_modes=['blueprint', 'soul', 'progressive'], music_status='not_started',
                ready_for_adapter=bool(paths), note='需要下游适配并生成音乐产物；不是 studio manifest 或可播放作品。')
            (folder / 'handoff.json').write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding='utf-8')
            if not paths:
                raise ValueError('未提取到足够的结构线条，请换用主体更清晰的图片或专用 AI 结构工作流。')
            self.update(jid, geometry=f'/media/{jid}/geometry.json', handoff=f'/media/{jid}/handoff.json', stats=stats,
                        stage='结构准备完成')
            if self.config.get('build_music', True):
                self.update(jid, music_status='processing', stage='正在为三个展示模式编排并渲染音乐')
                try:
                    self.update(jid, stage='等待音乐渲染')
                    with self.music_lock:
                        self.update(jid, stage='正在为三个展示模式编排并渲染音乐')
                        completed = subprocess.run([sys.executable, str(ROOT / 'bridge.py'), str(folder), self.soul_style()],
                            capture_output=True, timeout=900, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    if completed.returncode:
                        (folder / 'bridge.log').write_bytes(completed.stdout + completed.stderr)
                        raise RuntimeError('music build failed')
                    workspace_url = f'/works/{jid}/studio.html'
                    handoff.update(music_status='completed', workspace=workspace_url,
                        music_payload=f'/works/{jid}/studio/sample5.json',
                        music_path_ids='music_payload.contours[].id; note.source references these IDs',
                        candidate_path_ids='geometry.json uses separate p-prefixed candidate IDs')
                    (folder / 'handoff.json').write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding='utf-8')
                    self.update(jid, music_status='completed', workspace=workspace_url)
                except Exception:
                    reason = ''
                    log = folder / 'bridge.log'
                    if log.exists():
                        try:
                            lines = [line.strip() for line in log.read_text(encoding='utf-8', errors='ignore').splitlines() if line.strip()]
                        except OSError:
                            lines = []
                        for line in reversed(lines):
                            if line.startswith(('AssertionError', 'RuntimeError', 'ValueError', 'KeyError', 'FileNotFoundError', 'ImportError', 'AttributeError')):
                                reason = line[:160]
                                break
                    detail = f' 原因：{reason}。' if reason else ''
                    self.update(jid, music_status='failed', music_error=f'音乐生成未完成，结构数据已保留。{detail}可检查渲染依赖或主线版本后重新提交。')
            self.update(jid, status='completed', stage='作品准备完成' if self.snapshot(jid)['music_status'] == 'completed' else '结构准备完成')
        except Exception as e:
            message = str(e) if isinstance(e, ValueError) else '处理失败，请检查图片、工作流或服务连接。'
            self.update(jid, status='failed', stage='结构处理未完成', error=message)
            if job['provider']=='seedream' and self.snapshot(jid)['artistic_status']=='processing':
                self.update(jid,artistic_status='failed',error_code=getattr(e,'code','processing_error'),
                    api_metrics=dict(model=job.get('model'),elapsed_seconds=round(time.perf_counter()-api_started,3) if api_started else 0))
        finally:
            if art_thread:
                art_thread.join()
            manifest = self.runtime / jid / 'handoff.json'
            if manifest.exists():
                final = self.snapshot(jid)
                handoff = json.loads(manifest.read_text(encoding='utf-8'))
                handoff.update(artistic=final.get('artistic'), artistic_status=final.get('artistic_status'),
                               music_status=final.get('music_status'), workspace=final.get('workspace'))
                manifest.write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding='utf-8')
            self.slots.release()


class Share:
    def __init__(self, port=8782, addresses=None, runtime=None):
        self.port = port
        self.token = secrets.token_urlsafe(24)
        self.runtime = Path(runtime) if runtime else None
        self.sessions = {}
        self._load_sessions()
        self.addresses = addresses if addresses is not None else self.discover()
        self.address_labels = {}
        self.address_kinds = {}
        if addresses is None and os.name == 'nt':
            try:
                command = "Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress,InterfaceAlias | ConvertTo-Json -Compress"
                rows = json.loads(subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15).stdout)
                for row in rows if isinstance(rows, list) else [rows]:
                    address, alias = row['IPAddress'], row['InterfaceAlias']
                    name = alias.lower()
                    kind = 'tailscale' if 'tailscale' in name else 'virtual' if any(x in name for x in ('zerotier', 'vethernet', 'virtual', 'vpn')) else 'wifi' if any(x in name for x in ('wlan', 'wi-fi', 'wireless')) else 'ethernet'
                    description = {'tailscale': 'Tailscale 远程地址 · 手机需接入同一 Tailscale', 'virtual': '虚拟网络 · 普通手机通常不可达', 'wifi': '本机 Wi-Fi · 同一 Wi-Fi / 热点扫码首选', 'ethernet': '本机有线网 · 手机需能访问此网络'}[kind]
                    self.address_labels[address] = f'{address} — {description}'
                    self.address_kinds[address] = kind
                    ip = ipaddress.ip_address(address)
                    if (ip.is_private or ip in ipaddress.ip_network('100.64.0.0/10')) and not ip.is_loopback and not ip.is_link_local:
                        if address not in self.addresses:
                            self.addresses.append(address)
            except Exception:
                pass
        self.addresses.sort(key=lambda a: {'wifi': 0, 'ethernet': 1, 'tailscale': 2, 'virtual': 3}.get(self.address_kinds.get(a), 4))
        self.address = self.addresses[0] if self.addresses else None

    def _sessions_path(self):
        return self.runtime / 'share-sessions.json' if self.runtime else None

    def _load_sessions(self):
        path = self._sessions_path()
        if not path or not path.exists():
            return
        try:
            now = time.time()
            data = json.loads(path.read_text(encoding='utf-8'))
            self.sessions = {key: float(value) for key, value in data.items() if float(value) > now}
        except (OSError, ValueError, TypeError):
            self.sessions = {}

    def save_sessions(self):
        path = self._sessions_path()
        if not path:
            return
        now = time.time()
        self.sessions = {key: value for key, value in self.sessions.items() if value > now}
        try:
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.sessions), encoding='utf-8')
            temporary.replace(path)
        except OSError:
            pass

    @staticmethod
    def discover():
        found = set()
        cgnat = ipaddress.ip_network('100.64.0.0/10')
        for row in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = row[4][0]
            ip = ipaddress.ip_address(address)
            if (ip.is_private or ip in cgnat) and not ip.is_loopback and not ip.is_link_local:
                found.add(address)
        # Tailscale uses CGNAT (100.64/10) and is often missing from the hostname
        # lookup; probe the CLI so the QR can point at a phone-reachable address.
        try:
            import shutil as _shutil
            ts = _shutil.which('tailscale') or r'C:\Program Files\Tailscale\tailscale.exe'
            if ts and os.path.exists(ts):
                out = subprocess.run([ts, 'ip', '-4'], capture_output=True, text=True, timeout=3).stdout
                for line in out.split():
                    try:
                        if ipaddress.ip_address(line.strip()) in cgnat:
                            found.add(line.strip())
                    except ValueError:
                        pass
        except Exception:
            pass
        return sorted(found)

    def info(self):
        url = f'http://{self.address}:{self.port}/upload?join={self.token}' if self.address else None
        return dict(enabled=True, addresses=self.addresses, address=self.address, url=url,
                    address_labels={a: self.address_labels.get(a, f'{a} — 本机网络地址 · 请确认手机可达') for a in self.addresses})


def make_handler(pipeline, guest=False):
    # H6 (security): one limiter per listener.  The host console and the
    # guest upload port have separate budgets, so a guest phone cannot
    # block the operator and vice versa.
    limiter = RateLimiter(limit=12, window=60.0)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Pairing tokens and private asset URLs must not enter access logs.
            pass

        def owner(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
                value = cookie.get('sonify_guest')
                value = value.value if value else ''
                if not pipeline.share or pipeline.share.sessions.get(value, 0) < time.time():
                    return None
                return value
            except Exception:
                return None

        def guest_allowed(self, path):
            if not guest:
                return True
            if path in ('/phone.js', '/style.css'):
                return True
            if not self.owner():
                self.json_response(403, {'error': '请重新扫描电脑上的二维码。'})
                return False
            if path in ('/upload', '/api/health', '/api/jobs', '/experience', '/experience.js', '/experience.css',
                        '/journey', '/journey.js', '/api/host', '/community', '/community.js', '/community.css'):
                return True
            parts = path.split('/')
            jid = None
            if path.startswith('/api/jobs/') and len(parts) == 4:
                jid = parts[3]
            elif path.startswith('/media/') and len(parts) == 4:
                jid = parts[2]
            elif path.startswith('/works/') and len(parts) >= 4:
                jid = parts[2]
            if path.startswith('/api/jobs/') and len(parts) == 5 and parts[4] == 'fallback-local':
                jid = parts[3]
            if path.startswith('/api/jobs/') and len(parts) in (5,6) and parts[4]=='soul-roles':
                jid=parts[3]
            if jid and jid in pipeline.jobs and pipeline.snapshot(jid).get('guest_owner') == self.owner():
                return True
            self.json_response(403, {'error': '此页面仅能查看你自己上传的图片。'})
            return False

        def public_job(self, job):
            result = {k: v for k, v in job.items() if k != 'guest_owner'}
            result['community'] = pipeline.community.state(job['id']) if getattr(pipeline, 'community', None) else None
            return result

        def security_headers(self):
            """L4 (robustness): baseline browser security headers.

            The console serves private photos and generated works from the
            same origin, so a missing CSP would turn any XSS into a full
            data leak.  `frame-ancestors 'self'` blocks clickjacking of
            the host console; `same-origin` keeps the media/img sources
            restricted to this server.
            """
            self.send_header('Content-Security-Policy',
                             "default-src 'self'; img-src 'self' data: blob:; "
                             "media-src 'self' data: blob:; "
                             "script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'; "
                             "connect-src 'self'; font-src 'self' data:; "
                             "object-src 'none'; base-uri 'self'; "
                             "form-action 'self'; frame-ancestors 'self'")
            self.send_header('X-Frame-Options', 'SAMEORIGIN')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Permissions-Policy', 'geolocation=(), microphone=(), camera=()')

        def rate_key(self):
            """Identify the caller for rate limiting (H6)."""
            # The guest session cookie identifies a phone; the loopback
            # address identifies the host console.
            owner = self.owner()
            if owner:
                return 'guest:' + owner
            client = self.client_address[0] if self.client_address else 'unknown'
            return 'ip:' + client

        def json_response(self, status, value):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            if getattr(self, 'community_cookie', None):
                self.send_header('Set-Cookie', self.community_cookie)
                self.community_cookie = None
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.security_headers()
            self.end_headers()
            self.wfile.write(body)

        def discovery_proxy(self):
            """Keep discovery same-origin for loopback and LAN visitors alike."""
            suffix=self.path.removeprefix('/api/discover')
            path=urlsplit(suffix).path
            allowed=(self.command=='GET' and (path in ('/health','/search') or (path.startswith('/jobs/') and len(path.split('/'))==3))) or (self.command=='POST' and path=='/albums')
            if not allowed:return self.json_response(404,{'error':'在线探索接口不存在。'})
            try:
                data=None
                if self.command=='POST':
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=12000:return self.json_response(400,{'error':'请求大小无效。'})
                    data=self.rfile.read(length)
                request=Request('http://127.0.0.1:'+os.environ.get('SONIFY_DISCOVER_PORT','8784')+suffix,data=data,headers={'Content-Type':'application/json','Origin':'http://127.0.0.1:8781'},method=self.command)
                try:
                    with urlopen(request,timeout=40) as upstream:status=upstream.status;raw=upstream.read(4*1024*1024)
                except HTTPError as error:status=error.code;raw=error.read(4*1024*1024)
                self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            except Exception:return self.json_response(503,{'error':'在线探索服务暂时不可用，请稍后重试。'})


        def do_GET(self):
            if getattr(pipeline, 'community', None) and pipeline.community.route(self, pipeline, guest): return
            path = unquote(urlsplit(self.path).path)
            if not guest and path.startswith('/api/discover/'):
                return self.discovery_proxy()
            if guest and path == '/upload':
                token = parse_qs(urlsplit(self.path).query).get('join', [''])[0]
                if token:
                    if not pipeline.share or not secrets.compare_digest(token, pipeline.share.token):
                        return self.json_response(403, {'error': '二维码已失效，请扫描电脑当前显示的二维码。'})
                    self.send_response(303)
                    self.send_header('Location', '/upload')
                    owner = self.owner() or secrets.token_hex(24)
                    pipeline.share.sessions[owner] = time.time() + 28800
                    pipeline.share.save_sessions()
                    self.send_header('Set-Cookie', f'sonify_guest={owner}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
            if not self.guest_allowed(path):
                return
            if path in ('/api/host','/api/received'):
                with pipeline.lock:
                    raw = [copy.deepcopy(j) for j in pipeline.jobs.values()]
                if guest:
                    raw = [j for j in raw if j.get('guest_owner') == self.owner()]
                jobs = [self.public_job(j) for j in raw]
                share = {'enabled': False} if guest else (pipeline.share.info() if pipeline.share else {'enabled': False})
                return self.json_response(200, dict(share=share,
                    jobs=sorted(jobs, key=lambda j: j['created_at'], reverse=True)[:None if path=='/api/received' else 100]))
            if not guest and path == '/api/share/qr.png':
                if not pipeline.share or not pipeline.share.info()['url']:
                    return self.json_response(409, {'error': '未找到局域网地址，请先连接 Wi-Fi 或热点。'})
                import qrcode
                output = io.BytesIO()
                qrcode.make(pipeline.share.info()['url']).save(output, format='PNG')
                body = output.getvalue()
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == '/api/health':
                return self.json_response(200, {'providers': {'local': True} if guest else pipeline.availability(), 'music_adapter': True})
            if path.startswith('/api/jobs/'):
                parts=path.split('/')
                # H2: render one Progressive variant on demand.  The studio
                # UI calls this when the visitor switches to a style or
                # colour strength that was not pre-rendered.
                if len(parts) == 5 and parts[4] == 'progressive':
                    jid = parts[3]
                    if jid not in pipeline.jobs:
                        return self.json_response(404, {'error': '作品不存在。'})
                    if guest and pipeline.snapshot(jid).get('guest_owner') != self.owner():
                        return self.json_response(403, {'error': '只能操作自己上传的作品。'})
                    query = parse_qs(urlsplit(self.path).query)
                    preset = query.get('preset', ['nature'])[0]
                    strength = query.get('strength', ['auto'])[0]
                    try:
                        result = pipeline.render_progressive(jid, preset, strength)
                    except (ValueError, KeyError, OSError):
                        return self.json_response(400, {'error': '这个音乐风格暂时无法生成。'})
                    return self.json_response(202, result)
                if len(parts)==6 and parts[4]=='soul-roles':
                    try:
                        import role_remix
                        return self.json_response(200,role_remix.status(pipeline,parts[3],parts[5]))
                    except (OSError,ValueError,KeyError):
                        return self.json_response(404,{'error':'找不到这个改编版本。'})
                try:
                    return self.json_response(200, self.public_job(pipeline.snapshot(path.split('/')[-1])))
                except KeyError:
                    return self.json_response(404, {'error': '任务不存在。'})
            if not guest and path.startswith('/batches/'):
                base = (ROOT / 'batch_results').resolve()
                file = (base / path.removeprefix('/batches/')).resolve()
                if not file.is_relative_to(base) or file.suffix not in ('.html', '.css', '.js', '.json', '.png', '.jpg', '.wav', '.mid', '.md', '.svg', '.csv'):
                    return self.json_response(404, {'error': '测试文件不存在。'})
            elif path.startswith('/works/'):
                parts = path.split('/')
                if len(parts) < 4 or len(parts[2]) != 32 or any(c not in '0123456789abcdef' for c in parts[2]):
                    return self.json_response(404, {'error': '作品不存在。'})
                base = (pipeline.runtime / parts[2] / 'workspace').resolve()
                file = (base / '/'.join(parts[3:])).resolve()
                if not file.is_relative_to(base) or file.suffix not in ('.html', '.css', '.js', '.json', '.jpg', '.wav', '.mid'):
                    return self.json_response(404, {'error': '作品文件不存在。'})
                if parts[2] not in pipeline.jobs or pipeline.snapshot(parts[2]).get('music_status') != 'completed':
                    return self.json_response(409, {'error': '作品仍在生成。'})
            elif path.startswith('/media/'):
                parts = path.split('/')
                allowed = {'original.png', 'structural.png', 'artistic.png', 'skeleton.png', 'geometry.json', 'handoff.json'}
                if len(parts) != 4 or len(parts[2]) != 32 or any(c not in '0123456789abcdef' for c in parts[2]) or parts[3] not in allowed:
                    return self.json_response(404, {'error': '文件不存在。'})
                file = pipeline.runtime / parts[2] / parts[3]
            elif not guest and path.startswith('/museum/'):
                base = (ROOT / 'web' / 'museum').resolve()
                file = (base / path.removeprefix('/museum/')).resolve()
                if not file.is_relative_to(base) or file.suffix not in ('.json', '.jpg', '.png', '.wav', '.mp3', '.mid'):
                    return self.json_response(404, {'error': '展品不存在。'})
            elif not guest and path == '/modules/circle/index.html':
                file = ROOT / 'modules' / 'circle' / 'index.html'
            elif not guest and path.startswith('/paint/'):
                # Read-only mount of the MusicPaint project for line-art bridge integration
                paint_root = (ROOT.parents[1] / 'paint').resolve()
                if not paint_root.is_dir():
                    return self.json_response(503, {'error': 'Paint 模块尚未安装。'})
                rel = path.removeprefix('/paint/') or 'index.html'
                file = (paint_root / rel).resolve()
                if not file.is_relative_to(paint_root) or file.suffix not in ('.html', '.css', '.js', '.json', '.png', '.jpg', '.svg', '.woff', '.woff2', '.onnx', '.bin', '.gif'):
                    return self.json_response(404, {'error': 'Paint 资源不存在。'})
            elif path.startswith('/showcase/'):
                # Read-only mount of the MusicPhoto demo (experiment/dist) so the
                # intake reception page is the single entry point.
                base = (EXPERIMENT / 'dist').resolve()
                rel = path.removeprefix('/showcase/') or 'studio.html'
                file = (base / rel).resolve()
                if not file.is_relative_to(base) or file.suffix not in ('.html', '.css', '.js', '.json', '.jpg', '.jpeg', '.png', '.wav', '.mid', '.svg', '.mp3'):
                    return self.json_response(404, {'error': '示例页面不存在。'})
            else:
                names = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/host': 'host.html', '/host.js': 'host.js', '/upload': 'phone.html', '/phone.js': 'phone.js', '/journey': 'journey.html', '/journey.js': 'journey.js','/cloud-batch':'cloud-batch.html','/cloud-batch.js':'cloud-batch.js','/experience':'experience.html','/experience.js':'experience.js','/experience.css':'experience.css'}
                names.update({'/received':'received.html','/community': 'community.html', '/community.js': 'community.js', '/community.css': 'community.css', '/': 'sonify.html', '/sonify.css': 'sonify.css',
                              '/capture': 'index.html', '/paint': 'paint.html',
                              '/circle': 'circle.html', '/musiclab': 'musiclab.html', '/scroll': 'scroll.html',
                              '/museum.css': 'museum.css', '/museum.js': 'museum.js',
                              '/experience-lineart-bridge.js': 'experience-lineart-bridge.js'})
                if path not in names:
                    return self.json_response(404, {'error': '页面不存在。'})
                file = ROOT / 'web' / names[path]
            if not file.is_file():
                return self.json_response(404, {'error': '文件尚未生成。'})
            types = {'.csv': 'text/csv; charset=utf-8', '.svg': 'image/svg+xml', '.md': 'text/plain; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.mid': 'audio/midi', '.json': 'application/json', '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8'}
            if path.startswith('/museum/') and file.suffix in ('.wav', '.mp3'):
                # Museum's custom transport needs byte ranges to seek WAV audio.
                size = file.stat().st_size
                start, end, status = 0, size - 1, 200
                requested = self.headers.get('Range')
                if requested:
                    try:
                        unit, bounds = requested.split('=', 1)
                        first, last = bounds.split('-', 1)
                        if unit != 'bytes' or ',' in bounds or not (first or last):
                            raise ValueError()
                        if first:
                            start = int(first)
                            end = min(int(last), size - 1) if last else size - 1
                        else:
                            suffix = int(last)
                            if suffix <= 0:
                                raise ValueError()
                            start = max(0, size - suffix)
                        if start < 0 or start >= size or end < start:
                            raise ValueError()
                        status = 206
                    except ValueError:
                        self.send_response(416)
                        self.send_header('Content-Range', f'bytes */{size}')
                        self.send_header('Content-Length', '0')
                        self.end_headers()
                        return
                self.send_response(status)
                self.send_header('Content-Type', types[file.suffix])
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Content-Length', str(end - start + 1))
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Cache-Control', 'no-store')
                if status == 206:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.security_headers()
                self.end_headers()
                try:
                    with file.open('rb') as stream:
                        stream.seek(start)
                        remaining = end - start + 1
                        while remaining:
                            chunk = stream.read(min(65536, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass  # Browsers cancel the previous range when turning a page.
                return
            body = file.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', types[file.suffix])
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            self.security_headers()
            self.end_headers()
            self.wfile.write(body)

        def do_PUT(self):
            # M11: rename a work.  This route is handled *before* the
            # community router, because the community router only knows
            # about its own `/api/community/*` endpoints and would
            # otherwise answer 404.
            path = unquote(urlsplit(self.path).path)
            if path.startswith('/api/jobs/') and path.endswith('/title'):
                parts = path.split('/')
                if len(parts) != 5:
                    return self.json_response(404, {'error': '接口不存在。'})
                jid = parts[3]
                if jid not in pipeline.jobs:
                    return self.json_response(404, {'error': '作品不存在。'})
                # A guest may only rename a work that belongs to its own
                # session; the host console may rename anything.
                if guest and pipeline.snapshot(jid).get('guest_owner') != self.owner():
                    return self.json_response(403, {'error': '只能重命名自己上传的作品。'})
                length = int(self.headers.get('Content-Length', '0') or 0)
                if not 0 < length <= 4096:
                    return self.json_response(400, {'error': '请求大小无效。'})
                try:
                    body = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeDecodeError):
                    return self.json_response(400, {'error': '请求格式无效。'})
                if not isinstance(body, dict):
                    return self.json_response(400, {'error': '请求格式无效。'})
                try:
                    job = pipeline.rename(jid, body.get('title', ''))
                except TitleError as error:
                    return self.json_response(400, {'error': str(error)})
                except (KeyError, TypeError, ValueError):
                    return self.json_response(400, {'error': '请输入 1–60 字作品名。'})
                return self.json_response(200, self.public_job(job))
            if not (getattr(pipeline, 'community', None) and pipeline.community.route(self, pipeline, guest)):
                self.json_response(404, {'error': '接口不存在。'})

        def do_POST(self):
            if getattr(pipeline, 'community', None) and pipeline.community.route(self, pipeline, guest): return
            # Local-only application: deny cross-origin form/fetch submissions.
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host', ''):
                return self.json_response(403, {'error': '不允许跨站提交。'})
            if not self.guest_allowed(urlsplit(self.path).path):
                return
            path=urlsplit(self.path).path
            if path.startswith('/api/jobs/') and path.endswith('/soul-roles'):
                try:
                    parts=path.split('/')
                    if len(parts)!=5 or parts[3] not in pipeline.jobs:raise ValueError('作品不存在。')
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=262144:raise ValueError('选区请求过大。')
                    body=json.loads(self.rfile.read(length))
                    import role_remix
                    return self.json_response(202,role_remix.launch(pipeline,parts[3],body.get('assignments'),body.get('regions')))
                except (ValueError,KeyError,OSError,TypeError) as e:
                    return self.json_response(400,{'error':str(e) or '无法重新编曲。'})
            if not guest and urlsplit(self.path).path.startswith('/api/discover/'):
                return self.discovery_proxy()
            if self.path.startswith('/api/jobs/') and self.path.endswith('/fallback-local'):
                try:
                    return self.json_response(202, self.public_job(pipeline.fallback_local(self.path.split('/')[3])))
                except (KeyError, ValueError):
                    return self.json_response(400, {'error': '该任务不满足豆包出图失败的条件，不能改用 OpenCV。'})
            if not guest and self.path.startswith('/api/jobs/') and self.path.endswith('/retry-music'):
                try:
                    jid=self.path.split('/')[3]
                    return self.json_response(202,self.public_job(pipeline.retry_music(jid)))
                except (KeyError,ValueError):
                    return self.json_response(400,{'error':'无法复用此任务，请确认音乐失败且线稿已保留。'})
            if not guest and self.path == '/api/share/address':
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length < 1024:
                        raise ValueError()
                    address = json.loads(self.rfile.read(length))['address']
                    if not pipeline.share or address not in pipeline.share.addresses:
                        raise ValueError()
                    pipeline.share.address = address
                    (pipeline.runtime / 'share-address.json').write_text(json.dumps({'address': address}), encoding='utf-8')
                    return self.json_response(200, pipeline.share.info())
                except (ValueError, KeyError, TypeError):
                    return self.json_response(400, {'error': '请选择本机已有的网络地址。'})
            if not guest and self.path == '/api/jobs/batch':
                # H6 (security): a batch submission can trigger up to five
                # paid API calls at once.  Rate-limit it like a single
                # submission so the quota cannot be burned in a burst.
                if not limiter.check(self.rate_key()):
                    return self.json_response(429, {'error': '提交过于频繁，请稍后再试。'})
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=MAX_BYTES*7:
                        raise ValueError('批量请求过大。')
                    body=json.loads(self.rfile.read(length));items=body.get('images')
                    if not isinstance(items,list) or not 1<=len(items)<=5:
                        raise ValueError('每批请选择1–5张独立图片。')
                    accepted=[];errors=[]
                    for index,item in enumerate(items):
                        try:
                            raw=base64.b64decode(item['image'],validate=True)
                            job=pipeline.create(raw,body.get('provider','seedream'))
                            accepted.append(dict(index=index,job=self.public_job(job)))
                        except (ValueError,KeyError,TypeError) as error:
                            errors.append(dict(index=index,error=str(error) if isinstance(error,ValueError) else '图片请求格式无效。'))
                    return self.json_response(202 if accepted else 400,dict(accepted=accepted,errors=errors))
                except (ValueError,TypeError,KeyError,AttributeError):
                    return self.json_response(400,{'error':'每批支持1–5张图片，单张最大12 MB。'})
            if self.path != '/api/jobs':
                return self.json_response(404, {'error': '接口不存在。'})
            # H6 (security): every submission here can trigger the paid
            # Seedream API.  Limit the burst rate per client so a stuck
            # retry loop (or an abusive client) cannot drain the quota.
            if not limiter.check(self.rate_key()):
                return self.json_response(429, {'error': '提交过于频繁，请稍后再试。'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > MAX_BYTES * 8 // 3 + 4096:
                    raise ValueError('图片过大或请求为空。')
                body = json.loads(self.rfile.read(length))
                raw = base64.b64decode(body['image'], validate=True)
                lineart_raw = None
                provider = body.get('provider', 'local' if not guest else 'seedream')
                supplied_method = body.get('method', 'traditional')
                if provider == 'supplied':
                    if guest:
                        raise ValueError('手机上传不支持自定义线稿。')
                    lineart_raw = base64.b64decode(body.get('lineart', ''), validate=True)
                    if not lineart_raw:
                        raise ValueError('supplied provider 需要 lineart 字段。')
                job = pipeline.create(raw, 'seedream' if guest else provider,
                    False if guest else body.get('artistic', False), 
                    guest_owner=self.owner() if guest else None,
                    supplied_lineart=lineart_raw,
                    supplied_method=supplied_method)
                return self.json_response(202, self.public_job(job))
            except (ValueError, KeyError, TypeError) as e:
                return self.json_response(400, {'error': str(e) if isinstance(e, ValueError) else '提交失败：图片无效、队列已满或所选服务未配置。请使用不超过 12 MB 的 JPG/PNG。'})

    return Handler


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8781)
    parser.add_argument('--share', action='store_true', help='Enable a paired LAN phone upload listener')
    parser.add_argument('--guest-port', type=int, default=8782)
    parser.add_argument('--host-bind', default='127.0.0.1',
                        help='Host console bind address (0.0.0.0 = reachable from other devices; 127.0.0.1 = this PC only)')
    args = parser.parse_args()
    # Windows must reject duplicate listeners instead of serving different
    # application versions on the same port.
    ThreadingHTTPServer.allow_reuse_address = False
    pipeline = Pipeline()
    server = ThreadingHTTPServer((args.host_bind, args.port), make_handler(pipeline))
    server.daemon_threads = True
    guest_server = None
    if args.share:
        pipeline.share = Share(args.guest_port, runtime=pipeline.runtime)
        address_file = pipeline.runtime / 'share-address.json'
        if address_file.exists():
            try:
                preferred = json.loads(address_file.read_text(encoding='utf-8'))['address']
                if preferred in pipeline.share.addresses:
                    pipeline.share.address = preferred
            except (ValueError, KeyError, OSError):
                pass
        guest_server = ThreadingHTTPServer(('0.0.0.0', args.guest_port), make_handler(pipeline, guest=True))
        guest_server.daemon_threads = True
        threading.Thread(target=guest_server.serve_forever, daemon=True).start()
    print(f'Sonify Intake: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if guest_server:
            guest_server.shutdown()
            guest_server.server_close()
        server.server_close()
        pipeline.pool.shutdown(wait=True)
