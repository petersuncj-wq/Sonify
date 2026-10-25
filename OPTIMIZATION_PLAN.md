# Sonify 项目优化清单

> 复核基线：`c:\Users\dingc\Downloads\Sonify-main\Sonify-main`（源码评审包，`photo/` + `paint/`）
> 项目性质：上海科技大学 Techathon 2026 团队作品
> 说明：以下每条均已在代码中定位到具体文件与行，标注了证据与修复建议。

---

## 目录

- [概览](#概览)
- [🔴 高优先级](#-高优先级)
  - [H1 主控台绑定 0.0.0.0 且完全无鉴权](#h1安全主控台绑定-000且完全无鉴权--lan-内任意设备可读取全部作品并消耗付费-api-配额)
  - [H2 单次上传渲染约 190 个 WAV 文件](#h2性能单次上传渲染约-190-个-wav-文件绝大多数无人收听)
  - [H3 upgrade_workspaces.py 版本判断与当前引擎不匹配](#h3性能正确性upgrade_workspacespy-版本判断与当前引擎不匹配--每次执行都全量重建)
  - [H4 EngineSnapshot 把参考快照与测试文件纳入哈希](#h4性能正确性enginesnapshot-把参考快照与测试文件纳入哈希任何改动都作废全部作品)
  - [H5 Pipeline.update() 写盘异常未处理](#h5健壮性pipelineupdate-的写盘异常未被处理任务可能永久停留在-processing)
  - [H6 缺少速率限制，付费 API 可被刷](#h6安全缺少速率限制付费-api-可被刷)
- [🟡 中优先级](#-中优先级)
  - [M1 MIDI 导出逻辑重复实现了 4 遍](#m1代码质量drymidi-导出逻辑重复实现了-4-遍)
  - [M2 WAV 写盘逻辑重复实现](#m2代码质量wav-写盘逻辑重复实现)
  - [M3 _schedule() 调度器是 O(n²)](#m3性能_schedule-调度器是-on²且在最热的路径上)
  - [M4 trace() 用 Python 集合做像素级图遍历](#m4性能trace-用-python-集合做像素级图遍历)
  - [M5 蓝图谱音符 pitch 可能越界 MIDI 0–127](#m5健壮性蓝图谱音符-pitch-可能越界-midi-0127)
  - [M6 PENTA 音阶与 REGISTER 音区隐式耦合](#m6健壮性penta-音阶与-register-音区隐式耦合)
  - [M7 跨模块调用私有函数](#m7代码质量跨模块调用私有函数_-前缀)
  - [M8 soul_composition.py 的 west 风格是死代码](#m8代码质量soul_compositionpy-的-west-风格是死代码)
  - [M9 living_color.py 临时 stem 清理路径与命名不符](#m9健壮性living_colorpy-的临时-stem-清理路径与实际命名不符)
  - [M10 SQLite 连接在异常路径下可能不释放](#m10健壮性sqlite-连接在异常路径下可能不释放)
  - [M11 作品列表中的作品无法重命名](#m11交互体验作品列表中的作品无法重命名--缺少重命名入口与接口)
- [🟢 低优先级](#-低优先级)
  - [L1 intake/ 构建脚本可读性极差](#l1可读性photointake-下的构建脚本可读性极差)
  - [L2 _overlap_peak 是测试辅助函数却放在生产模块](#l2可维护性_overlap_peak-是测试辅助函数却放在生产模块)
  - [L3 历史参考快照与生产模块同目录](#l3可维护性历史参考快照与生产模块同目录)
  - [L4 前端缺少 CSP / X-Frame-Options / Referrer-Policy](#l4健壮性前端缺少-csp--x-frame-options--referrer-policy)
  - [L5 community.py 发布接口未限制标题字符集](#l5健壮性communitypy-的发布接口信任-bodytitle-的长度但未限制字符集)
  - [L6 find_soundfont() 硬编码历史绝对路径](#l6可维护性render_soundfontpy-的-find_soundfont-硬编码了历史绝对路径)
- [执行建议](#执行建议按投入产出比排序)
- [附录：模块质量分布观察](#附录模块质量分布观察)

---

## 概览

本次复核覆盖 `photo/intake/`（接入层，18 个模块）、`photo/experiment/`（引擎层，30+ 个模块）、`paint/modules/`（Paint 模块）与 `verification/`。

| 维度 | 评价 | 主要问题 |
|---|---|---|
| 性能 | ⚠️ 中等 | 全量预渲染（H2）、O(n²) 调度（M3）、Python 逐像素图遍历（M4） |
| 代码质量 | ⚠️ 中等 | MIDI/WAV 重复实现（M1/M2）、私有函数跨模块调用（M7）、死代码（M8） |
| 可读性 | ✅ 良好（引擎层）/ ⚠️ 较差（intake 层） | 两层质量断层明显（L1） |
| 安全性/健壮性 | ⚠️ 中等偏高风险 | 默认无鉴权暴露 LAN（H1）、无速率限制（H6）、异常路径吞状态（H5） |

**总体判断**：引擎层（`photo/experiment/`）工程质量很高——注释密度大、docstring 完整、设计决策有据可查、设计模式（引擎字节快照、复音预算硬上限、采样级事件调度、契约校验）都体现了明确的工程意识。**主要风险集中在接入层**：`photo/intake/` 下同时存在"安全关键逻辑"（SSRF 防护、许可白名单、访客隔离）与"最低可读性代码"（1 空格缩进、语句挤行、无注释），这一组合本身就是事故温床。

---

## 🔴 高优先级

### H1【安全】主控台绑定 `0.0.0.0` 且完全无鉴权 —— LAN 内任意设备可读取全部作品并消耗付费 API 配额

**位置：** `start_sonify.py:47` → `photo/intake/server.py:487-509`（`guest_allowed`）

```python
# start_sonify.py:47
command=[sys.executable,str(ROOT/'photo/intake/server.py'),'--port',str(port),'--share','--guest-port',str(port+1),'--host-bind','0.0.0.0']
```

```python
# photo/intake/server.py:487-489
def guest_allowed(self, path):
    if not guest:
        return True
```

**问题：** 项目设计了双端口 + 访客隔离（访客只能看自己的任务），但**主控台端口本身也监听 `0.0.0.0`**。而 `guest_allowed()` 对非 guest 请求直接放行。

后果是访客隔离形同虚设 —— 任何同网设备可直接：

- `GET /api/host` → 列出**全部**任务（含 `original` 原图路径）
- `GET /media/<jid>/original.png` → 下载所有人的**原始照片**（含人像，属隐私）
- `POST /api/jobs`（body 不带 `guest_owner`）→ 触发 `provider='seedream'` → **消耗付费的豆包 API 额度**
- `POST /api/jobs/batch` → 单次最多 5 张，无速率限制

**修改理由：** 这是本项目唯一面向公网/LAN 的入口，缺省配置下即形成未授权访问 + 计费资源滥用。README 明确说"此 HTTP 服务仅用于可信局域网"，但代码没有强制这一点。

**修复建议：**

1. `start_sonify.py` 默认改为 `--host-bind 127.0.0.1`，仅在显式传 `--lan` 时才使用 `0.0.0.0`：

   ```python
   parser.add_argument('--lan', action='store_true', help='Allow LAN access to the host console')
   ...
   host_bind = '0.0.0.0' if args.lan else '127.0.0.1'
   command=[sys.executable,str(ROOT/'photo/intake/server.py'),'--port',str(port),'--share',
            '--guest-port',str(port+1),'--host-bind',host_bind]
   ```

2. 或为主控台加一个与 `share.token` 无关的独立管理口令（`Share.token` 只保护访客端口）。

3. 无论采用哪种方案，`/api/jobs` 的 `provider='seedream'` 在非授权场景下应强制降级到 `local`（OpenCV 回退）。

---

### H2【性能】单次上传渲染约 190 个 WAV 文件，绝大多数无人收听

**位置：** `photo/intake/bridge.py:69-96`、`photo/experiment/living_color.py:20-40`

```python
# photo/intake/bridge.py:75-96
strengths = ['off','soft','mid','auto','vivid'] if color_dna and color_dna['available'] else ['auto']
payload['progressive_colors'] = {preset:{strength:arrange(payload['soul'],preset,units=units,
                                     color_dna=color_dna,color_strength=strength) for strength in strengths}
                                  for preset in PRESETS}
...
tracks = [('soul', 'soul', payload['soul']), ('soul_demo', 'soul-demo', payload['soul_demo'])]
tracks += [('progressive', 'progressive'+..., music)
           for preset,versions in payload['progressive_colors'].items() for strength,music in versions.items()]
for key, prefix, music in tracks:
    for v in range(5):
        renderer.render_wav([n for n in music['notes'] if n['voice'] == v],
                            assets / f'{slug}-{prefix}-{v}.wav', ...)
```

**量化：**

| 来源 | 组合数 | 每组合声部 | 渲染次数 |
|---|---|---|---|
| Progressive（4 预设 × 5 强度） | 20 | 5 | 100 |
| Soul + Soul Demo | 2 | 5 | 10 |
| Living Color（4 季 × 4 预设） | 16 | 5 | 80 |
| Blueprint + Identity | — | — | ~10 |
| **合计** | | | **约 190** |

每个 37 秒立体声 WAV ≈ 3.2 MB → 单任务约 **300 MB** 音频、20 次 `arrange()` 全量重算。

**修改理由：** 现场上传响应时间被这一步支配（`server.py` 给音乐阶段 900 秒超时）。用户实际只会听 1–3 个组合，但 95% 的算力花在了没人听的产物上。

**修复建议：** 改为**按需渲染**。

1. 默认只生成 `nature/auto` + soul + soul-demo（3 组合，15 次渲染）。
2. 其余组合在用户点击时由 `/api/jobs/<id>/progressive?preset=&strength=` 触发后台生成，轮询状态。
3. `check_workspace.py` 的契约校验同步放宽为"**已渲染的**组合必须正确"，而非"所有组合必须存在"：

   ```python
   # photo/intake/check_workspace.py（放宽后）
   for preset in PRESETS:
       versions = payload.get('progressive_colors', {}).get(preset)
       if not versions:
           continue  # 按需渲染，未生成则跳过
       for strength, music in versions.items():
           ...
   ```

---

### H3【性能/正确性】`upgrade_workspaces.py` 版本判断与当前引擎不匹配 → 每次执行都全量重建

**位置：** `photo/intake/upgrade_workspaces.py:18`

```python
# photo/intake/upgrade_workspaces.py:18
if not data.get('progressive_colors') or not data.get('color_dna') or \
   data['color_dna'].get('version')!='color-dna-1.0' or \
   not (folder/'engine-version.json').exists() or \
   json.loads((folder/'engine-version.json').read_text(encoding='utf-8'))!=data.get('engine_hashes'):
```

**问题：** 当前引擎 `photo/experiment/color_dna.py:40` 产出的版本是 **`color-dna-1.2`**：

```python
# photo/experiment/color_dna.py:40
return dict(..., version='color-dna-1.2', ...)
```

而此处断言的是 `color-dna-1.0`。`!=` 恒为真 → **所有工作区每次都被判定为"需要重建"**，无条件重跑 `bridge.py`。

**修改理由：** 这是典型的"常量漂移"缺陷 —— 升级 Color DNA 时漏改这里。后果是批量重建脚本失去意义，且每次重建又触发 H2 的 190 次渲染。

**修复建议：** 把版本号收敛到单一常量，各引用处从模块读取，禁止散落字面量。

```python
# photo/experiment/color_dna.py —— 新增模块级常量
VERSION = 'color-dna-1.2'

# photo/experiment/color_dna.py:40 —— 改为引用
return dict(..., version=VERSION, ...)

# photo/intake/upgrade_workspaces.py:18 —— 改为引用
from color_dna import VERSION as COLOR_DNA_VERSION
...
data['color_dna'].get('version') != COLOR_DNA_VERSION
```

同理，`photo/experiment/progressive_arrangement.py:185` 的 `version='progressive-color-2.0'` 与 `photo/experiment/publish_color_ui.py:12` 的断言也应一并收敛。

---

### H4【性能/正确性】`EngineSnapshot` 把参考快照与测试文件纳入哈希，任何改动都作废全部作品

**位置：** `photo/intake/engine_snapshot.py:11-13`

```python
# photo/intake/engine_snapshot.py:11-13
files = sorted(self.root.glob('*.py')) + sorted((self.root / 'ui').glob('*'))
self.content = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in files if p.is_file()}
```

**问题：** `glob('*.py')` 无差别收录 `photo/experiment/` 下全部脚本，包含：

- 5 个历史参考快照：`progressive_arrangement_v10/v11/v14_reference.py`、`color_dna_v10/v12_reference.py`
- `test_*.py`、`test_*.cjs`
- 各类 `build_*.py`、`publish_*.py`、`refresh_*.py`

而 `upgrade_workspaces.py` 又用 `engine-version.json != engine_hashes` 作为重建判据 → **改任何一个测试文件都会让所有历史作品"版本过期"**。

**修改理由：** 哈希的目的是保证"渲染时引擎未被改动"，应只覆盖**真正参与渲染的模块**。

**修复建议：** 改为显式白名单。

```python
# photo/intake/engine_snapshot.py —— 新增白名单
ENGINE_MODULES = (
    'run.py', 'blueprint.py', 'studio_grammar.py', 'soul_composition.py',
    'progressive_arrangement.py', 'progressive_features.py', 'color_dna.py',
    'seasonal_rules.py', 'identity_motif.py', 'living_color.py',
    'render_soundfont.py', 'compose_blueprint.py', 'build_studio.py',
    'build_progressive_arrangement.py', 'primitives.py', 'grammar.py',
)
UI_FILES = ('studio.html', 'studio.js', 'studio.css', 'soul_experience.js',
            'soul_interaction.js', 'soul_hero.js', 'progressive_revelation.js',
            'living_color.js', 'role_editor.js')

def __init__(self, root):
    self.root = Path(root)
    files = [self.root / name for name in ENGINE_MODULES if (self.root / name).is_file()]
    files += [self.root / 'ui' / name for name in UI_FILES if (self.root / 'ui' / name).is_file()]
    ...
```

---

### H5【健壮性】`Pipeline.update()` 的写盘异常未被处理，任务可能永久停留在 `processing`

**位置：** `photo/intake/server.py:79-84`、`photo/intake/server.py` 的 `Pipeline.run()` except 分支

```python
# photo/intake/server.py:79-84
def update(self, jid, **values):
    with self.lock:
        self.jobs[jid].update(values, updated_at=time.time())
        (self.runtime / jid / 'job.json').write_text(
            json.dumps(self.jobs[jid], ensure_ascii=False, indent=2), encoding='utf-8')
```

**问题链：**

1. `update()` 写盘失败（磁盘满、权限、杀毒软件锁文件）→ `OSError` 抛出
2. 在 `run()` 的 `except Exception` 中调用 `self.update(jid, status='failed', ...)` → **再次抛 OSError**
3. 异常逃逸出 `run()` → 被 `ThreadPoolExecutor` **静默吞掉**
4. 任务永远停在 `processing`，直到下次重启才被标记 failed

**信号量泄漏：** `create()` 中 `self.slots.acquire(blocking=False)` 若在之后的 `folder.mkdir()` 抛错，已获取的槽位**不会释放**（`release` 只在 `run()` 的 `finally` 里）→ 信号量逐步泄漏，最终"任务队列已满"永久锁死服务。

**修改理由：** 这是展览现场的致命故障模式 —— 磁盘满是本地部署的常见事件。

**修复建议：**

```python
# photo/intake/server.py —— update() 内部容错
def update(self, jid, **values):
    with self.lock:
        self.jobs[jid].update(values, updated_at=time.time())
        try:
            (self.runtime / jid / 'job.json').write_text(
                json.dumps(self.jobs[jid], ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            # 状态已在内存更新；落盘失败不应中断流水线（如磁盘已满）。
            pass
```

```python
# photo/intake/server.py —— create() 用 try/finally 保护信号量
def create(self, raw, provider, ...):
    ...
    if not self.slots.acquire(blocking=False):
        raise ValueError('任务队列已满，请稍后再试。')
    try:
        jid = uuid.uuid4().hex
        folder = self.runtime / jid
        folder.mkdir()
        ...
    except BaseException:
        self.slots.release()
        raise
```

并为 `run()` 增加 `except BaseException` 兜底落盘。

---

### H6【安全】缺少速率限制，付费 API 可被刷

**位置：** `photo/intake/server.py:775-790`

```python
# photo/intake/server.py:775-790
if not guest and self.path == '/api/jobs/batch':
    try:
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=MAX_BYTES*7:raise ValueError('批量请求过大。')
        body=json.loads(self.rfile.read(length));items=body.get('images')
        if not isinstance(items,list) or not 1<=len(items)<=5:raise ValueError('每批请选择1–5张独立图片。')
        accepted=[];errors=[]
        for index,item in enumerate(items):
            try:
                raw=base64.b64decode(item['image'],validate=True)
                job=pipeline.create(raw,body.get('provider','seedream'))
```

**问题：** `slots` 信号量（8）只限制**并发**任务数，不限制**速率**。任务失败后立即释放槽位，攻击者可以持续提交 5 张一批的请求。每次 `provider='seedream'` 都是一次真实计费调用。

**修改理由：** 结合 H1（主控台暴露 LAN），这是可被远程触发的计费资源耗尽。

**修复建议：**

1. 按 IP + actor 维度做令牌桶限流。
2. 对 `seedream` provider 增加"每场次最大云端调用数"硬上限，超限直接走本地 OpenCV 回退。
3. `seedream.py` 的 `ark_attempts` 已有重试逻辑，需确认重试不会放大计费 —— 目前 `attempts` 上限为 2，且仅对 429/5xx 重试，属合理范围。

---

## 🟡 中优先级

### M1【代码质量/DRY】MIDI 导出逻辑重复实现了 4 遍

**位置：**

| 文件 | 函数 | 行 |
|---|---|---|
| `photo/experiment/run.py` | `vlq` / `export` | 113-126 |
| `photo/experiment/blueprint.py` | `midi` | 43-51 |
| `photo/experiment/build_studio.py` | `export_midi` | 39-60 |
| `photo/experiment/compose_v2.py` | `export_midi` + 内嵌 `vlq` | 127-230 |

**问题：** 四份各自实现了 VLQ 编码、`MThd`/`MTrk` 打包、音符事件排序，且 `build_studio.py` 与 `compose_v2.py` 的 `export_midi` 签名与行为已不一致：

```python
# photo/experiment/build_studio.py:39 —— 支持 pans、按 tempo_bpm 算 tick
def export_midi(notes, path, tempo_bpm=120, pans=None):
```

```python
# photo/experiment/compose_v2.py:127 —— 签名不同
def export_midi(notes: Sequence[dict], path: Path, tempo_bpm: int = 80) -> None:
```

**修改理由：** MIDI 是"可复现"承诺的产物之一，四份实现意味着修一处 bug 要改四处，且容易产出互不兼容的 MIDI。

**修复建议：** 抽出 `photo/experiment/midi_io.py`：

```python
"""Single MIDI writer for every producer (Blueprint / Soul / Progressive)."""
import struct

def vlq(v: int) -> bytes:
    """Variable-length quantity, MIDI delta-time encoding."""
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.insert(0, (v & 0x7F) | 0x80)
        v >>= 7
    return bytes(out)

def write_midi(notes, path, tempo_bpm=120, pans=None) -> None:
    events = []
    ticks_per_second = 480 * tempo_bpm / 60
    for v in range(5):
        ns = [n for n in notes if n['voice'] == v]
        if ns:
            events.append((0, -1, bytes([0xC0 + v, ns[0]['program']])))
            if pans is not None:
                events.append((0, -1, bytes([0xB0 + v, 10, round((pans[v] + 1) * 63.5)])))
    for n in notes:
        events.extend([
            (round(n['start'] * ticks_per_second), 1,
             bytes([0x90 + n['voice'], n['pitch'], max(1, min(127, n['velocity']))])),
            (round((n['start'] + n['duration']) * ticks_per_second), 0,
             bytes([0x80 + n['voice'], n['pitch'], 0])),
        ])
    track = bytearray(b'\x00\xff\x51\x03' + round(60000000 / tempo_bpm).to_bytes(3, 'big'))
    last = 0
    for t, _, msg in sorted(events):
        track += vlq(t - last) + msg
        last = t
    track += b'\x00\xff\x2f\x00'
    path.write_bytes(b'MThd' + struct.pack('>IHHH', 6, 0, 1, 480)
                     + b'MTrk' + struct.pack('>I', len(track)) + track)
```

四个调用点统一改为 `from midi_io import write_midi`。

---

### M2【代码质量】WAV 写盘逻辑重复实现

**位置：**

| 文件 | 函数 | 行 | channels 支持 |
|---|---|---|---|
| `photo/experiment/render_soundfont.py` | `_write_wav` | 220-224 | ✅ |
| `photo/experiment/compose_v2.py` | `_write_wav` | 118-125 | ❌ 强制单声道 |
| `photo/experiment/build_progressive_arrangement.py` | `write` | 15-16 | ✅ |

**问题：** `compose_v2.py` 的版本连 `channels` 参数都没有，与另两处行为不一致。

**修复建议：** 统一到 `render_soundfont._write_wav`（已有 `channels` 支持），其余改为薄封装：

```python
# photo/experiment/compose_v2.py
from render_soundfont import _write_wav as write_wav
```

---

### M3【性能】`_schedule()` 调度器是 O(n²) 且在最热的路径上

**位置：** `photo/experiment/studio_grammar.py:249-291`

```python
# photo/experiment/studio_grammar.py:263-281
for _ in range(4000):
    active = 0
    conflict = False
    earliest = None
    for e, st, vv, pp in heap:
        if st - 1e-9 <= t < e - 1e-9:
            active += 1
            if vv == v and pp == p:
                conflict = True
            if earliest is None or e < earliest:
                earliest = e
```

**问题：** 每个候选音符都要**线性扫描整个 heap** 统计活跃数。对于上万条几何路径（蓝图谱符号可达 12,000），这是 O(n²) 量级，且内层 `for _ in range(4000)` 是无界的。

**修改理由：** 这是整条管线中纯 CPU 热点，与 H2 的渲染量叠加后，总时长被显著拉长。

**修复建议：** 用"按时间排序的滑动窗口 + 频次计数"替代每次全扫描，把 `active` 计数降为 O(1) 增量维护；同时把 `range(4000)` 改为有明确终止条件的循环（当前 `t` 每次至少 +0.05，4000 次即 200 秒上限，超出 `limit_end` 后应立即 break）。

---

### M4【性能】`trace()` 用 Python 集合做像素级图遍历

**位置：** `photo/experiment/run.py:16-41`

```python
# photo/experiment/run.py:16-41
def trace(skeleton):
    pixels = set(map(tuple, np.argwhere(skeleton > 0)))
    def neighbors(p):
        y,x=p
        result=[]
        for dy,dx in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
            q=(y+dy,x+dx)
            if q not in pixels: continue
            if dx and dy and ((y,x+dx) in pixels or (y+dy,x) in pixels): continue
            result.append(q)
        return sorted(result)
    adjacency={p:neighbors(p) for p in sorted(pixels)}
    visited=set(); paths=[]
    def walk(p,q):
        ...
```

**问题：** 骨架图可达数万节点，`neighbors()` 对每个像素调用 8 次 `set` 查询，且 `walk()` 中 `if tuple(sorted((current,nxt))) in visited` 每步都构造新元组并查哈希。

**修改理由：** 纯 Python 逐像素图遍历在此规模下是秒级开销。

**修复建议：** 用 NumPy 一次向量化出 8 邻接（位移数组 + 布尔掩码），再在 `scipy.sparse` 上求连通分量，把路径提取交给 C 实现。若不想引入 scipy 依赖，至少把 `visited` 的键从 `tuple(sorted(...))` 换成整数编码 `a * W + b`，避免元组分配。

---

### M5【健壮性】蓝图谱音符 `pitch` 可能越界 MIDI 0–127

**位置：** `photo/experiment/blueprint.py:26`、`photo/experiment/compose_blueprint.py:98-102`、`photo/experiment/render_soundfont.py:172`

```python
# photo/experiment/blueprint.py:26
symbols.append(dict(id=f'bp{len(symbols):05d}', path=pid, x=round(nx,6), y=round(ny,6),
                     angle=round(math.atan2(delta[1],delta[0]),3),
                     pitch=round(84-48*ny), start=round(nx*12,4), duration=.10))
```

**问题：** `ny ∈ [0,1]` 理论上 `pitch ∈ [36, 84]`，安全。但 `compose_blueprint.py` 的 `_quantise()` 对超出 `PENTATONIC` 范围的输入会返回**最近的边缘音级**而非报错 —— 即音高信息被静默截断，破坏"可追溯"承诺。

```python
# photo/experiment/render_soundfont.py:172
pitch = max(0, min(127, int(n['pitch'])))
```

同样是静默钳制而非抛错。

**修改理由：** 静默钳制会让"音符来源可追溯"的核心理念在边界情况下失真，且不产生任何告警。

**修复建议：** 统一在编曲出口处做**显式范围校验**，越界抛 `ValueError` 并附上溯源信息；钳制仅保留为最后一道防线。

```python
# photo/experiment/render_soundfont.py —— 在事件构建处显式校验
pitch = int(n['pitch'])
if not 0 <= pitch <= 127:
    raise ValueError(f"pitch {pitch} out of MIDI range (source={n.get('source')}, id={n.get('id')})")
```

---

### M6【健壮性】`PENTA` 音阶与 `REGISTER` 音区存在隐式耦合

**位置：** `photo/experiment/studio_grammar.py:41`、`photo/experiment/soul_composition.py:32`

```python
# photo/experiment/studio_grammar.py:41
PENTA = [p for p in range(36, 85) if p % 12 in (0, 2, 4, 7, 9)]
```

而 `SCALE` 是硬编码的 `[48,50,52,55,57,60,62,64,67,69,72,74,76,79]`。二者音级集合相同（`p%12` 集合 `{0,2,4,7,9}`），但 `PENTA` 从 36 起（36%12=0 ✓），`SCALE` 从 48 起。`soul_composition.py` 的 `_ladder()` 在 `east` 风格下返回 `grammar.PENTA`。

问题在于 `REGISTER` 音区与 `PENTA` 的 36–84 范围硬耦合：

```python
# photo/experiment/soul_composition.py:32
REGISTER = {0: (69, 84), 1: (63, 70), 2: (38, 48), 3: (48, 59), 4: (55, 66)}
```

若将来调整 `PENTA` 起点，这些硬编码音区会静默越界 → `_in_win` 返回空列表 → `_chord_pitches` 回退到 `_in_win` 仍为空 → `tones` 为空 → 该声部**整段无声且不报错**。

**修改理由：** 音区与音阶范围之间的隐式耦合是"沉默失败"的典型来源。

**修复建议：**

1. `REGISTER` 改为相对 `PENTA` 的比例区间：

   ```python
   # photo/experiment/soul_composition.py
   def _register_ranges(ladder):
       lo, hi = ladder[0], ladder[-1]
       span = hi - lo
       return {0: (lo + span * 0.75, hi),
               1: (lo + span * 0.60, lo + span * 0.76),
               2: (lo, lo + span * 0.28),
               3: (lo + span * 0.27, lo + span * 0.52),
               4: (lo + span * 0.42, lo + span * 0.68)}
   ```

2. 或在 `_chord_pitches` 返回空时抛出显式异常：

   ```python
   def _chord_pitches(ladder, pcs, lo, hi):
       tones = [p for p in ladder if lo <= p <= hi and p % 12 in pcs]
       if not tones:
           raise ValueError(f'no chord tones in register [{lo},{hi}] for pcs {pcs}')
       return tones
   ```

---

### M7【代码质量】跨模块调用私有函数（`_` 前缀）

**位置：** `photo/experiment/build_studio.py:89`、`photo/experiment/blueprint.py`

```python
# photo/experiment/build_studio.py:89
return [dict(id=u['id'], voice=sg._voice_for(u), type=u['type'],
```

同类还有 `photo/experiment/blueprint.py` 中 `import run as lab` 后调用 `lab.trace` / **`lab.cv2`**（通过 `run` 模块间接使用 `cv2`，即 `lab.cv2` 实际是 `run.py` 的 import 别名 —— 语义完全错误且极脆弱）。

`run.py` 顶部的 `import run as lab` 模式本身也是把一个脚本当库用，导致 `run.py` 的 `main()` 副作用（`OUT.mkdir(exist_ok=True)`）在导入时执行。

**修改理由：** `lab.cv2` 这类写法一旦 `run.py` 的 import 顺序调整就会 `AttributeError`，且完全没有静态可读性。

**修复建议：**

1. 把 `trace()` / `extract()` / `vlq` 抽到 `photo/experiment/geometry.py`（纯库），`run.py` 只保留 CLI 入口。
2. 公开 `studio_grammar._voice_for` → `voice_for`（或提供明确的 `public_api()` 导出清单）。
3. `blueprint.py` 中直接 `import cv2`，不要经由 `run` 模块转发。

---

### M8【代码质量】`soul_composition.py` 的 `west` 风格是死代码

**位置：** `photo/experiment/soul_composition.py:47-58`

```python
# photo/experiment/soul_composition.py:47-58
'west': dict(
    name='西洋古典 · 功能和声',
    pcs=(0, 2, 4, 5, 7, 9, 11),
    chords={'I': (0, {0, 4, 7}), 'ii': (2, {2, 5, 9}), 'iii': (4, {4, 7, 11}),
            'IV': (5, {5, 9, 0}), 'V': (7, {7, 11, 2}), 'V7': (7, {7, 11, 2, 5}),
            'vi': (9, {9, 0, 4})},
    prog={'A':  ['I', 'vi', 'IV', 'V', 'I', 'vi', 'IV', 'V'],
          'B':  ['ii', 'V7', 'I', 'vi', 'ii', 'V7', 'I', 'V7'],
          'C':  ['vi', 'iii', 'IV', 'V7', 'vi', 'iii', 'IV', 'V7'],
          'A′': ['I', 'vi', 'IV', 'V', 'I', 'IV', 'V7', 'I']},
),
```

**问题：** `STYLES['west']`（西洋功能和声，含 V7 和声）定义完整，但**全项目无任何调用方传入 `style_key='west'`**：

```python
# photo/experiment/soul_composition.py:234
def compose(units, grammar, style_key='east'):
```

`studio_grammar.py:338`、`photo/intake/role_remix.py:68` 均走默认 `'east'`。

**修改理由：** 约 12 行精心设计的和声数据从未被执行，等于"实现了但没验证"。

**修复建议：** 二选一 ——

1. 接入产品：把 `style_key` 暴露为配置项（`config.local.json` 或 `/api` 参数），并在前端提供风格切换。
2. 若暂不启用：加注释明确标注"已实现未启用"，并补一个单元测试确保其不腐化。

---

### M9【健壮性】`living_color.py` 的临时 stem 清理路径与实际命名不符

**位置：** `photo/experiment/living_color.py:32-33` vs `photo/experiment/living_color.py:88-91`

生成时前缀是 `f'{slug}-season-v11-{id}-{preset}'`：

```python
# photo/experiment/living_color.py:32-33
for v in range(5):rsf.render_wav([n for n in m['notes'] if n['voice']==v],assets/f'{prefix}-{v}.wav',...)
audio,rate=mix_stems(prefix,m,assets)
```

而 `__main__` 的清理分支找的是 `f"{p['id']}-season-{state['id']}-{preset}-{voice}.wav"`（**缺 `v11`**）：

```python
# photo/experiment/living_color.py:88-91
for voice in range(5):
    stem=path.parent/f"{p['id']}-season-{state['id']}-{preset}-{voice}.wav"
    if stem.exists():stem.unlink()
```

**后果：** 若某次 `mix_stems` 抛异常，5 个中间 stem（每个 37 秒立体声）会残留在 `assets/` 中不被清理。单任务 16 组 × 5 = 80 个残留文件。

**修改理由：** 命名漂移导致的资源泄漏，且在磁盘紧张的展览机器上会加速 H5 的触发。

**修复建议：** 用 `try/finally` 保证清理；把前缀生成收敛到单一函数。

```python
# photo/experiment/living_color.py
def _stem_prefix(slug, state_id, preset):
    return f'{slug}-season-v11-{state_id}-{preset}'
```

生成与清理都调用它。

---

### M10【健壮性】SQLite 事务管理依赖实现细节

**位置：** `photo/intake/community.py:33-40`、`photo/intake/community.py:143`

```python
# photo/intake/community.py:33-40
@contextmanager
def connect(self):
    db = sqlite3.connect(self.db, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()
```

`db.close()` 在 `finally` 中本身是安全的。但 `like()` 中的手动 `BEGIN IMMEDIATE`：

```python
# photo/intake/community.py:143
db.execute('BEGIN IMMEDIATE')
```

配合 `with db:` 的隐式事务管理，在 `sqlite3` legacy `isolation_level=''` 模式下属于**依赖实现细节的写法** —— 不同 Python 版本对"已显式 BEGIN 时是否再隐式 BEGIN"的处理有差异。

**修改理由：** 点赞是高频写操作，一次 `OperationalError: cannot start a transaction within a transaction` 会让点赞功能整体失效。

**修复建议：** 统一使用 `isolation_level=None`（autocommit）+ 显式 `BEGIN IMMEDIATE`/`COMMIT`，或去掉手动 BEGIN 改用 `with db:` 的默认事务。

```python
# photo/intake/community.py
def connect(self):
    db = sqlite3.connect(self.db, timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
    finally:
        db.close()
```

---

### M11【交互体验】作品列表中的作品无法重命名 —— 缺少重命名入口与接口

**位置：** `photo/intake/web/experience.js:8`（`list()`）、`photo/intake/web/host.js:24`、`photo/intake/web/community.js:27`（`mine()`）、`photo/intake/server.py:104-155`（`Pipeline.create()`）、`photo/intake/server.py:723-725`（`do_PUT`）

```javascript
// photo/intake/web/experience.js:8 — 列表标题硬编码为任务 ID 前缀
const title = document.createElement('strong');
title.textContent = `${job.submission==='phone'?'手机图片':'图片'} · ${job.id.slice(0,6).toUpperCase()}`;
```

```javascript
// photo/intake/web/host.js:24 — 待接页列表同样只能看到 ID
const title = document.createElement('strong');
title.textContent = `${job.submission === 'phone' ? '手机' : '电脑'} · ${job.id.slice(0,6).toUpperCase()}`;
```

**问题：** 作品列表里的每一个作品都只有一个自动生成的标识（ID 前 6 位），全项目归属在 **前端无重命名入口**，后端也 **没有对应接口**：

| 环节 | 现状 |
|---|---|
| `Pipeline.create()` 产生的 job 字段 | 只有 `id / status / stage / provider / music_status` 等，**无 `title` 字段** |
| `Pipeline.update()` 写盘 | 只能改动态字段，无法写入名称 |
| `server.py` 路由 | 只有 `do_GET` / `do_POST` / `do_PUT`；`do_PUT`（行 723-725）**只转发给 `community.route()`**，不接受任何作品改名请求；无 `do_PATCH` / `do_DELETE` |
| 唯一的名称入口 | `community.py:89` 的 `publish()` — 但它是“发布到社区”的副作用，存在 SQLite `works` 表，与 job 本身脱离 |

**具体表现（实测可复现）：**

1. 在 `/experience` 的「作品列表」中，作品名始终是 `图片 · A1B2C3`，无法修改；`button.onclick=()=>choose(job.id)` 以及整行都是 `<button>`，**不存在可编辑元素**，即使想做内联编辑也无处放置入口。
2. 即使用户通过 `community.js` 的发布对话框输入了作品名，作品列表**仍然显示 ID**（因为 `list()` 只读 `job.id`，不读 `job.community.title`）——“已发布 · 管理”按钮与列表显示名称不一致。
3. `host.js` 的待接列表、`community.js` 的「我的作品」列表同样只显示 ID 前缀，三个入口的命名规则不一致。

**修改理由：** 「作品」是本项目的最核心产出，但用户无法为自己的作品命名，只能看到随机生成的机器 ID。在移动端扫码作品、多人共享的展览场景下，作品标识失去了人的意义（作者不能区分自己上传的哪一张），而“发布后发现名字没变”在交互上会被视为功能失效。

**修复建议：**

1. **后端先补数据模型**：`Pipeline.create()` 的 job 字段增加 `title`（默认为空字符串，由前端回退到 ID 前缀显示），并形成一个专用方法写入并落盘：

   ```python
   # photo/intake/server.py
   def rename(self, jid, title):
       # Attach a human-readable name to one job and persist it.
       title = (title or '').strip()
       if not 1 <= len(title) <= 60:
           raise ValueError('请输入 1–60 字作品名。')
       self.update(jid, title=title)
       return self.snapshot(jid)
   ```

2. **新增一个专用接口**（现有 `do_PUT` 只转发社区路由，不能直接拆用）：

   ```python
   # photo/intake/server.py — do_PUT 内先处理作品改名
   def do_PUT(self):
       path = unquote(urlsplit(self.path).path)
       if path.startswith('/api/jobs/') and path.endswith('/title'):
           try:
               jid = path.split('/')[3]
               if jid not in pipeline.jobs:
                   return self.json_response(404, {'error': '任务不存在。'})
               if guest and pipeline.snapshot(jid).get('guest_owner') != self.owner():
                   return self.json_response(403, {'error': '只能重命名自己上传的作品。'})
               length = int(self.headers.get('Content-Length', '0'))
               if not 0 < length <= 4096:
                   return self.json_response(400, {'error': '请求大小无效。'})
               body = json.loads(self.rfile.read(length))
               if not isinstance(body, dict):
                   return self.json_response(400, {'error': '请求格式无效。'})
               return self.json_response(200, self.public_job(pipeline.rename(jid, body.get('title', ''))))
           except (ValueError, TypeError, KeyError):
               return self.json_response(400, {'error': '请输入 1–60 字作品名。'})
       if not (getattr(pipeline, 'community', None) and pipeline.community.route(self, pipeline, guest)):
           self.json_response(404, {'error': '接口不存在。'})
   ```

3. **前端增加内联重命名入口**：`experience.js` 的 `list()` 里把标题区从 `<strong>` 换成可编辑元素（双击或笔图标按钮进入编辑，Enter 确认、Esc 取消）。**注意：现有整行是 `<button>`，不能在 `<button>` 内嵌入 `<input>`（非法 HTML，且点击会触发 `choose()` 切换作品）** —— 需把列表项拆成 `<div class="item">` + 独立的选中按钮与重命名按钮。

   ```javascript
   // photo/intake/web/experience.js — list() 中的重命名
   const label = document.createElement('strong');
   label.textContent = job.title || `${job.submission==='phone'?'手机图片':'图片'} · ${job.id.slice(0,6).toUpperCase()}`;
   const rename = document.createElement('button');
   rename.className = 'rename-button';
   rename.type = 'button';
   rename.textContent = '✓';
   rename.setAttribute('aria-label', '重命名作品');
   rename.onclick = async (event) => {
     event.stopPropagation();
     const input = document.createElement('input');
     input.className = 'rename-input';
     input.maxLength = 60;
     input.value = job.title || '';
     label.replaceWith(input);
     input.focus(); input.select();
     const commit = async () => {
       const next = input.value.trim();
       try {
         if (next && next !== job.title) {
           const updated = await api('/api/jobs/' + job.id + '/title',
             {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title:next})});
           jobs.set(updated.id, updated);
         }
       } catch (e) { /* 失败时回退原名 */ }
       list();
     };
     input.onblur = commit;
     input.onkeydown = (e) => { if (e.key==='Enter'){e.preventDefault(); input.blur();} else if (e.key==='Escape'){input.value = job.title || ''; input.blur();} };
   };
   ```

4. **统一三个列表的命名规则**：`experience.js:list()`、`host.js:drawQueue()`、`community.js:mine()` 都应改为优先读 `job.title`，为空时再回退到 ID 前缀；并保证 `/api/host`、`/api/received`、`/api/jobs/<id>` 返回的 job 对象均含 `title`（`public_job()` 自动包含 job 字段，无需额外改动）。

5. **与社区名称的关系要明确：** 建议语义上区分“作品名（本地，所有列表可见）”与“社区展示名（仅发布后公开可见）”；两者分别存储、分别校验。若希望发布后修改名称并同步到社区列表，则在 `community.publish()` 里增加一个只改 `works.title` 的路径（受 `guest_owner` 校验），并在前端保留“同步到社区”开关。

6. **同步安全校验**：重命名的输入应复用社区发布的字符集白名单（参见 L5），拒绝控制字符与双向覆写字符，避免在列表中直接渲染时造成断行或伪造内容。

**验证要点：** 在 `photo/intake/test_intake.py` 中补充：改名后 `job.json` 落盘且 `/api/host` 返回新 `title`；超长/空名返回 400；非本人对访客改名返回 403；改名后前端列表显示新名称（需一个最小化的 DOM 断言测试）。

---

## 🟢 低优先级

### L1【可读性】`photo/intake/` 下的构建脚本可读性极差

**位置：** `photo/intake/upgrade_workspaces.py`、`photo/intake/build_progressive_arrangement.py`、`photo/intake/discover_service.py`、`photo/intake/scroll_score.py`

典型特征：**1 空格缩进**、多语句用 `;` 挤在一行、无 docstring、无函数注释。

```python
# photo/intake/discover_service.py:21-24
def plain(value):return html.unescape(re.sub('<[^>]*>','',str(value))).strip()[:1200]
def download(url,limit=16*1024*1024):
 if urlsplit(url).scheme!='https' or urlsplit(url).hostname not in {'commons.wikimedia.org','upload.wikimedia.org','thumb.wikimedia.org'}:raise ValueError('来源图片地址未通过检查。')
 with urlopen(Request(url,headers={'User-Agent':'SonifyHackathon/1.0 (open art discovery; educational prototype)'}),timeout=25) as r:
  if urlsplit(r.url).hostname not in {'commons.wikimedia.org','upload.wikimedia.org','thumb.wikimedia.org'}:raise ValueError('图片跳转到了未支持的来源。')
```

**对比：** `photo/experiment/` 下的核心引擎（`studio_grammar.py`、`soul_composition.py`、`progressive_arrangement.py`）注释密度高、docstring 完整、有设计决策说明 —— **质量差距极大**。

**修改理由：** 安全关键代码（SSRF 防护、许可校验）恰好在可读性最差的文件里，改动时极易出错。

**修复建议：**

1. 统一 PEP 8（`black` + `ruff`），为 `intake/` 下每个模块补 docstring。
2. 安全相关分支（域名白名单、许可校验）加显式注释说明**为什么**这样判断，而不只是**做了什么**。

```python
# 修复后示例
def download(url: str, limit: int = 16 * 1024 * 1024) -> bytes:
    """Fetch one Wikimedia image.

    The host allowlist blocks SSRF: an attacker-controlled catalog entry must
    not be able to point the server at internal services. The redirect check
    is re-applied after the request because Wikimedia may redirect to a CDN
    host that differs from the original URL.
    """
    allowed = {'commons.wikimedia.org', 'upload.wikimedia.org', 'thumb.wikimedia.org'}
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in allowed:
        raise ValueError('来源图片地址未通过检查。')
    with urlopen(Request(url, headers={'User-Agent': 'SonifyHackathon/1.0'}), timeout=25) as r:
        if urlsplit(r.url).hostname not in allowed:
            raise ValueError('图片跳转到了未支持的来源。')
        raw = r.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('图片文件过大，请选另一件作品。')
    return raw
```

---

### L2【可维护性】`_overlap_peak` 是测试辅助函数却放在生产模块

**位置：** `photo/experiment/studio_grammar.py:341-356`

```python
# photo/experiment/studio_grammar.py:341
def _overlap_peak(notes) -> int:
    # Round to microseconds so a note's end ties with another's start and
    # is processed as an "off" before the next "on" (avoid float drift).
    ...
```

仅被 `photo/experiment/test_studio.py` 使用（`test_studio.py:37`、`test_studio.py:150`），生产路径不调用。

**修复建议：** 移入测试工具模块（如 `photo/experiment/_test_support.py`），或标记为明确导出的 `public API`。

---

### L3【可维护性】历史参考快照与生产模块同目录

**位置：**

- `photo/experiment/progressive_arrangement_v10_reference.py`
- `photo/experiment/progressive_arrangement_v11_reference.py`
- `photo/experiment/progressive_arrangement_v14_reference.py`
- `photo/experiment/color_dna_v10_reference.py`
- `photo/experiment/color_dna_v12_reference.py`

这 5 个文件被 `photo/experiment/build_color_contrast_review.py` 引用，但它们与生产模块平级、命名仅靠后缀区分，极易被误改或误 import。

**修改理由：** 与 H4（哈希纳入 glob）叠加，等于让历史快照污染生产哈希。

**修复建议：** 移到 `photo/experiment/_archive/` 并从 EngineSnapshot 的收集范围排除；`build_color_contrast_review.py` 中的 import 路径同步更新。

---

### L4【健壮性】前端缺少 CSP / X-Frame-Options / Referrer-Policy

**位置：** `photo/intake/server.py` 响应头设置处（约 700-720 行）

```python
# photo/intake/server.py（约 714-720）
self.send_header('Content-Length', str(len(body)))
self.send_header('X-Content-Type-Options', 'nosniff')
self.send_header('Cache-Control', 'no-store')
```

现有头只有 `X-Content-Type-Options: nosniff` 与 `Cache-Control: no-store`。`experience.js` 会用 iframe 加载 `/works/<jid>/studio.html` 并注入 CSS（`doc.createElement('style')`）—— 同源属正常，但缺少 `frame-ancestors` 约束意味着可被任意站点点击劫持。

**修改理由：** 局域网暴露场景下，缺少 CSP 使任何 XSS 都能直接读取用户会话与私有作品。

**修复建议：** 统一加 `Content-Security-Policy: default-src 'self'; frame-ancestors 'self'`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: no-referrer`。注意需与 `/paint/` 挂载点、`/museum/` 静态资源（图片/音频）核对后调整 `img-src` / `media-src`。

---

### L5【健壮性】`community.py` 的发布接口未限制标题字符集

**位置：** `photo/intake/community.py:89-92`

```python
# photo/intake/community.py:89-92
title = body.get('title', '')
category = body.get('category')
if not isinstance(title, str) or not 1 <= len(title.strip()) <= 60 or category not in CATEGORIES:
    raise ValueError('请输入 1–60 字作品名，并选择社区模块。')
```

标题长度与类型受控，但允许任意 Unicode（含 RTL 覆写、控制字符）。前端渲染时需确认是否做了转义。

**修复建议：** 补一个字符白名单校验（拒绝控制字符与双向覆写字符），并在渲染端确认使用 `textContent` 而非 `innerHTML` 拼接用户数据。

---

### L6【可维护性】`find_soundfont()` 硬编码了历史绝对路径

**位置：** `photo/experiment/render_soundfont.py:46-52`

```python
# photo/experiment/render_soundfont.py:46-52
candidates.extend([
    here / 'dist' / 'soundfonts' / 'FluidR3Mono_GM.sf3',
    root / 'Existed_Project_Github' / 'Existed_Program_Github_IanniX'
    / 'soundfonts' / 'FluidR3Mono_GM.sf3',
    root / 'Existed_Project_Github' / 'Existed_Program_Github_IanniX'
    / 'soundfonts' / 'FluidR3_GM.sf2',
    Path('experiment/dist/soundfonts/FluidR3Mono_GM.sf3'),
    Path('soundfonts/FluidR3Mono_GM.sf3'),
])
```

含已废弃项目的路径 `Existed_Project_Github/...`，且 `Path('experiment/...')` 是相对**当前工作目录**的 —— 服务在不同 cwd 启动时会漏检。

**修改理由：** 音源缺失时抛 `RuntimeError("no FluidR3 .sf2/.sf3 found; set SONIFY_SF2 env var")`，在展览现场会直接导致所有上传失败，且错误信息没有提示去哪里找。

**修复建议：**

1. 清理废弃路径。
2. 相对路径统一基于 `ROOT` 解析。
3. 错误信息列出已搜索的绝对路径列表。

```python
# photo/experiment/render_soundfont.py
candidates.extend([
    here / 'dist' / 'soundfonts' / 'FluidR3Mono_GM.sf3',
    root / 'photo' / 'experiment' / 'dist' / 'soundfonts' / 'FluidR3Mono_GM.sf3',
    ROOT / 'soundfonts' / 'FluidR3Mono_GM.sf3',
])
...
raise RuntimeError(
    'no FluidR3 .sf2/.sf3 found; set SONIFY_SF2 env var. Searched:\n  '
    + '\n  '.join(str(c) for c in candidates))
```

---

## 执行建议（按投入产出比排序）

| 顺序 | 项 | 类型 | 预期收益 | 改动量 |
|---|---|---|---|---|
| 1 | **H1** 主控台改 `127.0.0.1` | 安全 | 消除未授权访问 + 计费滥用 | 1 行 |
| 2 | **H3** 版本号收敛为常量 | 正确性 | 修复批量重建误触发 | 小 |
| 3 | **H4** 引擎哈希白名单 | 性能 | 避免无关改动作废作品 | 小 |
| 4 | **M7 / M1 / M2** 抽公共库（geometry / midi_io / wav_io） | 质量 | 消除 4 份 MIDI / 3 份 WAV 重复 | 中 |
| 5 | **H2** 渐进式渲染改为按需 | 性能 | 上传响应时间可降一个数量级 | 中 |
| 6 | **H5** `update()` 容错 + 信号量 finally | 健壮 | 防现场永久锁死 | 小 |
| 7 | **M6** 音区/音阶耦合显式化 | 健壮 | 防"沉默失败" | 小 |
| 8 | **L1** `intake/` 代码格式化 + 补注释 | 可读性 | 降低安全代码改动风险 | 中 |

### 特别提示 H2

H2 同时是性能问题**和**产品问题 —— 用户上传后要等 20 秒以上才能看到作品，而这 20 秒里 95% 花在了没人听的 190 个 WAV 上。改成按需渲染后，"上传即出作品"的体验会显著改善，这也是 `PRODUCT.md:173` 声称的"约 20 秒"中最不划算的部分。

### 建议的验证方式

每项修改后运行现有测试：

```bash
# Python 侧（54 项检查）
cd photo/intake && python -m unittest -v test_intake
cd photo/experiment && python -m unittest -v test_studio test_pipeline_v2 test_progressive_arrangement test_color_dna test_living_color

# Node 侧
cd paint/modules/musicpaint/源码 && node tests/integration-test.js
```

重点回归：

- **H2** 改动后 `check_workspace.py` 的断言数量会下降，需同步调整 `verification/FINAL_ACCEPTANCE.json` 的记录
- **H4** 改动后 `engine-version.json` 的内容会变化（哈希集合变小），历史工作区需一次性重建
- **M1/M2** 改动后需比对新旧 MIDI/WAV 的字节一致性，确认输出未变

---

## 附录：模块质量分布观察

| 目录 | 风格 | 注释密度 | 测试覆盖 | 评价 |
|---|---|---|---|---|
| `photo/experiment/`（引擎层） | 4 空格 PEP8 | 高（含设计理由） | 完整（`test_*.py` + `test_*.cjs`） | ✅ 工程质量优秀 |
| `photo/intake/`（接入层） | 1 空格压缩 | 极低 | 有（`test_*.py` 10+） | ⚠️ 需格式化与补注释 |
| `paint/modules/musicpaint/源码/` | 2 空格 + 语义化换行 | 中（含模块头注释） | 有（`tests/*.cjs` 6 个） | ✅ 良好 |
| `paint/modules/fourier/源码/` | 压缩单行 | 低 | 有 | ⚠️ 可读性偏低 |

**结论性观察：** 项目的设计意图与核心算法质量明显高于其工程实现质量。`studio_grammar.py` 的 `VOICE_CATALOG`、`soul_composition.py` 的 `STYLES`、`progressive_arrangement.py` 的 `PRESETS` 都体现了"用数据表描述设计决策"的良好习惯 —— 这套做法应推广到 `intake/` 层（例如把白名单、常量、路由表全部抽成具名常量），而不是散落在条件表达式里。
