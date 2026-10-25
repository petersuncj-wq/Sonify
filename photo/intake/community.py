"""Opt-in community publishing, durable likes and restricted preview assets."""
from pathlib import Path
from contextlib import contextmanager
import hashlib, hmac, json, re, secrets, shutil, sqlite3, time
from http.cookies import SimpleCookie
from urllib.parse import urlsplit, parse_qs
from PIL import Image, ImageOps

from titles import sanitize_title, TitleError

CATEGORIES = ('music-flow', 'masterpiece')
ID = re.compile(r'^[a-f0-9]{32}$')

class Community:
    def __init__(self, runtime):
        self.root = Path(runtime)
        self.assets = self.root / 'community-assets'
        self.assets.mkdir(exist_ok=True)
        self.db = self.root / 'community.sqlite'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS works (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
                    published_at REAL NOT NULL, published INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS likes (
                    work_id TEXT NOT NULL REFERENCES works(id), actor TEXT NOT NULL,
                    PRIMARY KEY(work_id, actor));
                CREATE INDEX IF NOT EXISTS works_category ON works(category, published, published_at);
            ''')
            db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', ('secret', secrets.token_hex(32)))
            self.secret = db.execute('SELECT value FROM settings WHERE key=?', ('secret',)).fetchone()[0].encode()
    @contextmanager
    def connect(self):
        """Open a SQLite connection in explicit-transaction mode.

        M10 (robustness): the connection used to run with the default
        `isolation_level=''`, where the driver implicitly opens a
        transaction before the first write.  `like()` then issued an
        explicit `BEGIN IMMEDIATE`, which depends on implementation details
        of the sqlite3 module and can fail with
        `OperationalError: cannot start a transaction within a transaction`.

        With `isolation_level=None` the driver never opens a transaction on
        its own; every write path below manages its transaction explicitly
        with `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`.
        """
        db = sqlite3.connect(self.db, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
        finally:
            db.close()

    def actor(self, handler, guest):
        if guest:
            owner = handler.owner()
            if not owner: raise PermissionError('请重新扫描电脑上的二维码。')
            return 'guest:' + owner
        cookie = SimpleCookie()
        try:
            cookie.load(handler.headers.get('Cookie', ''))
            raw = cookie['sonify_community'].value
            value, signature = raw.split('.')
            valid = bool(ID.fullmatch(value)) and hmac.compare_digest(signature, hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest())
        except (KeyError, ValueError):
            valid = False
        if not valid:
            value = secrets.token_hex(16)
            signature = hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()
            handler.community_cookie = f'sonify_community={value}.{signature}; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000'
        return 'host:' + value

    def state(self, jid):
        with self.connect() as db:
            row = db.execute('SELECT title, category, published FROM works WHERE id=?', (jid,)).fetchone()
        return dict(row) if row else None

    def ready(self, pipeline, jid):
        if not ID.fullmatch(jid): return False
        try: job = pipeline.snapshot(jid)
        except KeyError: return False
        return job.get('music_status') == 'completed' and job.get('status') == 'completed'

    def visible(self, pipeline, jid):
        state = self.state(jid)
        return bool(state and state['published'] and self.ready(pipeline, jid) and
                    (self.assets / jid / 'thumbnail.jpg').is_file() and (self.assets / jid / 'preview.wav').is_file())

    def publish(self, pipeline, jid, actor, body):
        if not ID.fullmatch(jid): raise ValueError('作品不存在。')
        try: job = pipeline.snapshot(jid)
        except KeyError: raise ValueError('作品不存在。') from None
        if actor.startswith('guest:') and actor[6:] != job.get('guest_owner'):
            raise PermissionError('只能发布自己上传的作品。')
        published = body.get('published', True)
        if type(published) is not bool: raise ValueError('发布状态无效。')
        if not published:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                try:
                    db.execute('UPDATE works SET published=0 WHERE id=?', (jid,))
                    db.execute('COMMIT')
                except Exception:
                    db.execute('ROLLBACK')
                    raise
            return {'published': False}
        title = body.get('title', '')
        category = body.get('category')
        # L5 (robustness): the length check alone allowed control characters
        # and bidirectional overrides, which can corrupt the rendered list
        # or visually spoof another author's name.  `sanitize_title` applies
        # the same whitelist as the local rename endpoint.
        try:
            title = sanitize_title(title)
        except TitleError as error:
            raise ValueError(str(error)) from None
        if category not in CATEGORIES:
            raise ValueError('请输入 1–60 字作品名，并选择社区模块。')
        if not self.ready(pipeline, jid): raise ValueError('音乐生成完成后才能发布。')
        source = pipeline.runtime / jid
        preview = source / 'workspace' / 'studio' / 'sample5-progressive-mix.wav'
        original = source / 'original.png'
        if not original.is_file() or not preview.is_file(): raise ValueError('缩略图或试听音频尚未就绪。')
        target = self.assets / jid
        target.mkdir(exist_ok=True)
        # Stable copies expose only the selected image and rendered mix, never the private workspace.
        nonce = secrets.token_hex(8)
        thumb = target / (nonce + '.jpg')
        audio = target / (nonce + '.wav')
        try:
            with Image.open(original) as im:
                im = ImageOps.exif_transpose(im).convert('RGB')
                im.thumbnail((640, 640))
                im.save(thumb, 'JPEG', quality=85)
            shutil.copyfile(preview, audio)
            thumb.replace(target / 'thumbnail.jpg')
            audio.replace(target / 'preview.wav')
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                try:
                    db.execute('''INSERT INTO works VALUES (?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title, category=excluded.category,
                        published_at=CASE WHEN works.published=0 THEN excluded.published_at ELSE works.published_at END,
                        published=1''', (jid, title, category, time.time()))
                    db.execute('COMMIT')
                except Exception:
                    db.execute('ROLLBACK')
                    raise
        finally:
            thumb.unlink(missing_ok=True)
            audio.unlink(missing_ok=True)
        return self.state(jid)

    def listing(self, pipeline, actor, category, sort, limit, offset):
        if category not in CATEGORIES or sort not in ('newest', 'likes'): raise ValueError('列表参数无效。')
        order = 'likes DESC, w.published_at DESC, w.id DESC' if sort == 'likes' else 'w.published_at DESC, w.id DESC'
        with self.connect() as db:
            rows = db.execute('''SELECT w.id,w.title,w.category,w.published_at,
                (SELECT COUNT(*) FROM likes l WHERE l.work_id=w.id) AS likes,
                EXISTS(SELECT 1 FROM likes l WHERE l.work_id=w.id AND l.actor=?) AS liked_by_me
                FROM works w WHERE w.published=1 AND w.category=? ORDER BY ''' + order, (actor, category)).fetchall()
        items = []
        for row in rows:
            if not self.visible(pipeline, row['id']): continue
            item = dict(row)
            item['liked_by_me'] = bool(item['liked_by_me'])
            item['thumbnail_url'] = '/api/community/' + item['id'] + '/thumbnail'
            item['preview_url'] = '/api/community/' + item['id'] + '/preview'
            items.append(item)
        return {'items': items[offset:offset+limit], 'total': len(items), 'has_more': offset+limit < len(items)}

    def like(self, pipeline, jid, actor, liked):
        if type(liked) is not bool: raise ValueError('点赞状态无效。')
        if not self.visible(pipeline, jid): raise ValueError('作品尚未公开或已撤回。')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                if not db.execute('SELECT 1 FROM works WHERE id=? AND published=1', (jid,)).fetchone():
                    raise ValueError('作品已撤回。')
                if liked: db.execute('INSERT OR IGNORE INTO likes VALUES (?,?)', (jid, actor))
                else: db.execute('DELETE FROM likes WHERE work_id=? AND actor=?', (jid, actor))
                count = db.execute('SELECT COUNT(*) FROM likes WHERE work_id=?', (jid,)).fetchone()[0]
                db.execute('COMMIT')
            except Exception:
                db.execute('ROLLBACK')
                raise
        return {'likes': count, 'liked_by_me': liked}

    def route(self, handler, pipeline, guest):
        parsed = urlsplit(handler.path)
        path = parsed.path
        if path != '/api/community' and not path.startswith('/api/community/'): return False
        try:
            actor = self.actor(handler, guest)
            method = handler.command
            if method in ('POST', 'PUT'):
                origin = handler.headers.get('Origin')
                if origin and origin != 'http://' + handler.headers.get('Host', ''):
                    raise PermissionError('不允许跨站提交。')
            if method == 'GET' and path == '/api/community':
                q = parse_qs(parsed.query)
                limit = min(50, max(1, int(q.get('limit', ['12'])[0])))
                offset = max(0, int(q.get('offset', ['0'])[0]))
                result = self.listing(pipeline, actor, q.get('category', ['music-flow'])[0], q.get('sort', ['newest'])[0], limit, offset)
                handler.json_response(200, result)
                return True
            match = re.fullmatch(r'/api/community/([a-f0-9]{32})/(publish|like|thumbnail|preview)', path)
            if not match:
                handler.json_response(404, {'error': '社区接口不存在。'})
                return True
            jid, action = match.groups()
            if method == 'GET' and action in ('thumbnail', 'preview'):
                if not self.visible(pipeline, jid):
                    handler.json_response(404, {'error': '作品尚未公开或已撤回。'})
                    return True
                self.send_asset(handler, jid, action)
                return True
            if (method, action) not in (('POST', 'publish'), ('PUT', 'like')):
                handler.json_response(405, {'error': '请求方法不支持。'})
                return True
            size = int(handler.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096: raise ValueError('请求大小无效。')
            body = json.loads(handler.rfile.read(size))
            if not isinstance(body, dict): raise ValueError('请求格式无效。')
            result = self.publish(pipeline, jid, actor, body) if action == 'publish' else self.like(pipeline, jid, actor, body.get('liked'))
            handler.json_response(200, result)
        except PermissionError as error:
            handler.json_response(403, {'error': str(error)})
        except (ValueError, TypeError):
            handler.json_response(400, {'error': '请求无效，请确认作品已生成、名称和分类有效。'})
        except (OSError, sqlite3.Error):
            handler.json_response(503, {'error': '社区暂时不可用，请稍后重试。'})
        return True

    def send_asset(self, handler, jid, action):
        file = self.assets / jid / ('thumbnail.jpg' if action == 'thumbnail' else 'preview.wav')
        size = file.stat().st_size
        start, end, status = 0, size - 1, 200
        requested = handler.headers.get('Range') if action == 'preview' else None
        if requested:
            try:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                if not match or not any(match.groups()): raise ValueError()
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), size-1) if last else size-1
                else:
                    if int(last) <= 0: raise ValueError()
                    start = max(0, size-int(last))
                if start >= size or start > end: raise ValueError()
                status = 206
            except ValueError:
                handler.send_response(416)
                handler.send_header('Content-Range', f'bytes */{size}')
                handler.send_header('Content-Length', '0')
                handler.end_headers()
                return
        handler.send_response(status)
        handler.send_header('Content-Type', 'image/jpeg' if action == 'thumbnail' else 'audio/wav')
        handler.send_header('Content-Length', str(end-start+1))
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        if action == 'preview': handler.send_header('Accept-Ranges', 'bytes')
        if status == 206: handler.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        # L4: the same baseline headers as the rest of the console.
        if hasattr(handler, 'security_headers'):
            handler.security_headers()
        handler.end_headers()
        try:
            with file.open('rb') as stream:
                stream.seek(start)
                remaining = end-start+1
                while remaining:
                    chunk = stream.read(min(65536, remaining))
                    if not chunk: break
                    handler.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
