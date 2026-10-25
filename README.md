# Sonify · 让世界唱起来

> **Techathon 2026 · 上海科技大学 · 2026-10-18 最终整合版**
> 看见形状，听见世界。把照片、绘画与长卷，变成可听、可看、可复现的音乐。

---

## ⚡ 下载即运行（精简版）

> **下载 → 解压 → 进目录 → 装依赖 → 启动。** zip 约 304 MB，解压后约 578 MB。

**下载：** 打开 Release → **拉到页面最底部** → **Assets** → 点击 **`Sonify-Runnable-20261025.zip`**（约 304 MB）。
⚠️ **不要**用绿色 **Code → Download ZIP**（那只有源码，没有音源/长卷/Paint 资源，不能直接跑）。

Release：https://github.com/DClovewatch-deville/Sonify1.1/releases/tag/v1.1-runnable

```powershell
# 1. 解压后进入目录（必须）
cd "D:\你解压的位置\Sonify-Runnable-20261025"

# 2. 安装依赖（只需一次；国内建议保留镜像）
python -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 3. 启动
python start_sonify.py --port 8895
```

打开 **http://127.0.0.1:8895/**（以控制台打印的“主页”为准）。停止：**Ctrl + C**。
详细说明与已知限制见 [`README-RUNNABLE.md`](README-RUNNABLE.md)。

> 源码仓库（clone）也已补根目录 `requirements.txt`；只想跑优先用 Release zip。
> 源码仓库不含构建后的 Paint HTML，`start_sonify.py --check` 会显示 `Paint: False`。

---

## 🔑 API Key 配置（豆包 Seedream）

> 仓库和 zip **不包含任何密钥**；每个用户用自己的 Key。没有 Key 也能跑（OpenCV 回退）。

```powershell
copy photo\intake\ark.env.example photo\intake\ark.local.env
notepad photo\intake\ark.local.env      # 填入 ARK_API_KEY=...
copy photo\intake\config.example.json photo\intake\config.local.json
# 确认 ark_model 是已开通的模型 / endpoint
```

重启服务后测试；`/api/health` 的 `seedream: true` 表示已读取。详见 [`API_SETUP.md`](API_SETUP.md)。

---

**本仓库是源码评审包**：包含全部自研代码、算法与验收记录；**不包含**约 8 GB 的生成音轨、展览图像、大型音源/模型与用户任务。完整现场版在团队笔记本运行，源码用于评委审阅与核心链路复现。

> 产品介绍、三种听法、新增能力与完整架构图见 **[PRODUCT.md](PRODUCT.md)**；第三方许可见 **[THIRD_PARTY.md](THIRD_PARTY.md)**。

---

## 在线体验

<!-- LIVE_DEMO:START -->
- **公网 Demo**：`【待补充：部署后的可访问地址】`
<!-- LIVE_DEMO:END -->
- **本机 / 现场**：`http://127.0.0.1:8895/`
- **手机访客**：打开 `/host` 接待页，用手机扫描二维码上传

> 在线地址部署完成后填入上方的 `LIVE_DEMO` 区块即可；源码包本身不附带运行所需的大型资源。

---

## 下载即运行

> 安装与启动步骤已移到文首 **[⚡ 下载即运行](#-下载即运行精简版)**。
> Release：https://github.com/DClovewatch-deville/Sonify1.1/releases/tag/v1.1-runnable

---

## 一分钟看懂

| 分区 | 入口 | 做什么 |
|---|---|---|
| **MusicPhoto** | `/capture` | 上传照片 → 线稿 / 几何结构 → 三种听法 |
| **MusicPaint** | `/paint` | 手绘 / 文字 / 图片 → 旋律；傅里叶绘谱 |
| **MusicLab** | `/musiclab` | 声音画册、千古长卷、在线发现 |
| **社区** | `/community` | 发布作品、试听、点赞、分类浏览 |
| **接待** | `/host` | 现场二维码、访客上传、大屏播放 |

三种呈现：

- **蓝图谱 Blueprint**：按原图坐标生成的图形乐谱，看见空间结构。
- **灵魂交响 Soul**：几何路径分成旋律、支撑、背景声部，多乐器演奏。
- **渐显乐章 Progressive**：从几乎空白开始，轮廓、结构、层次与细节依次生长，最终回到完整画面。

---

## 仓库结构

```
.
├─ photo/
│  ├─ intake/          # 上传、豆包适配、社区、Lab、长卷、角色重编曲、HTTP 服务
│  ├─ experiment/      # 几何提取、Blueprint / Soul / Progressive 编曲、Color DNA、四时共鸣
│  └─ requirements-share.txt
├─ paint/
│  └─ modules/
│     ├─ musicpaint/源码      # 手绘 / 文字 / 图像 → 旋律、配器、保存与导出
│     └─ fourier/源码         # Fourier V4.31、团队音乐增强、Photo 线稿桥接
├─ verification/       # 最终整合版验收与来源记录
├─ 第三方许可/          # 第三方许可证与音源说明
├─ start_sonify.py     # 一键启动 Photo / Paint / Lab / 社区
├─ verify_package.py   # 源码包完整性校验
└─ CORE_MANIFEST.json  # 核心文件清单与哈希
```

---

## 快速开始

### 1. 依赖

```bash
pip install -r photo/requirements-share.txt
```

（NumPy、Pillow、tinysoundfont、opencv-contrib-python-headless、qrcode、mido、soundfile）

### 2. 资源

本仓库**不含**运行所需的大型资源。按 [`ASSETS.md`](ASSETS.md) 从完整交付包补齐：

- SoundFont 音源（离线渲染）
- `photo/intake/runtime/` 用户任务与生成音频
- `photo/intake/web/museum/` 展览图像与音频
- Paint 的模型 / 便携依赖

### 3. 启动

```bash
python start_sonify.py --port 8895
```

- 主入口：<http://127.0.0.1:8895/>
- 手机访客：先打开 `/host`，再扫码
- 仅启动 Paint：`python start_sonify.py --paint-only`
- 自检：`python start_sonify.py --check`

### 4. 豆包 Seedream（可选）

照片 → 线稿默认调用豆包 Seedream。需要用户自行开通火山方舟模型与额度：

1. 复制 `photo/intake/ark.env.example` 为 `photo/intake/ark.local.env`
2. 填入 `ARK_API_KEY=...`
3. 在 `photo/intake/config.local.json` 中配置 `ark_model`

`ark.local.env` 已被 `.gitignore` 忽略，**不会进入仓库**。未配置时可使用 OpenCV 回退。

---

## 资源边界

为控制仓库体积，本包**不包含**：

- 生成音轨（`*.wav` / `*.mp3`）、SoundFont（`*.sf3`）
- 展览图像与音频、用户上传任务（`photo/intake/runtime/`）
- 大型模型（SlimSAM `*.onnx`）、便携 Python / vendor 依赖
- 任何密钥、`*.local.env`

因此：**源码可读、可评审、可复现核心算法；完整离线演示需补齐资源。**

---

## 验收

完整资源环境中的结果：

- 54 项 Python 检查通过
- Fourier 108 组组合通过
- MusicPaint 6 个测试文件通过
- 实际完成一次本地上传生成三模式，以及角色修改后的五轨渲染

核心源码包删除了大型测试样例，不能直接复现依赖这些样例的全部测试。详见 `verification/`。

---

## 第三方与许可

- 豆包 Seedream（云端图生图 API）
- FluidR3Mono GM SoundFont
- MIDI.js Soundfonts
- VSCO-2-CE（MusicPaint 音源）
- Wikimedia Commons（在线发现，CC-BY，来源随画册保留）
- NumPy / Pillow / OpenCV / tinysoundfont / qrcode / mido / soundfile

许可证与来源见 [`第三方许可/`](第三方许可/) 与各模块 README。

---

## 相关文档

- [`PRODUCT.md`](PRODUCT.md) — 产品介绍、三种听法、新增能力、架构图
- [`DEV_SETUP.md`](DEV_SETUP.md) — 远程开发者上手指南（最小资源集）
- [`THIRD_PARTY.md`](THIRD_PARTY.md) — 第三方组件与许可证汇总
- [`COPYRIGHT.md`](COPYRIGHT.md) — 版权与使用范围
- [`ASSETS.md`](ASSETS.md) — 未入库的大型资源清单
- `photo/intake/README.md` — 上传、社区、Lab、长卷
- `photo/experiment/README.md` — 几何与编曲引擎
- `photo/experiment/SOUL_ROLE_REASSIGNMENT_DELIVERY.md` — 用户角色改派
- `photo/experiment/COLOR_DNA_V2_DELIVERY.md` — Color DNA 2.0
- `photo/experiment/SEASONAL_RESONANCE_1705_1732.md` — 四时共鸣
- `photo/intake/DISCOVER_HANDOFF.md` — 在线发现与画册

---

*Sonify 团队 · Techathon 2026*
