# API Key 配置（豆包 Seedream）

> **仓库和 zip 不包含任何密钥。** 每个用户用自己的 Key；没有 Key 也能跑（OpenCV 回退）。

---

## 要不要配？

| 选择 | 效果 | 需要什么 |
|---|---|---|
| **用自己的豆包 Key** | 照片→线稿质量最好，艺术性强 | 火山方舟账号 + 开通模型 + API Key |
| **不配 Key，OpenCV 回退** | 能出线稿、能继续生成音乐 | 无需账号 |

---

## 1. 申请 Key

1. 打开火山方舟控制台（Volcengine Ark）
2. 开通 **Seedream / 图生图** 模型
3. 创建 **API Key**
4. 记录你在控制台实际可用的 **模型名或 endpoint ID**

> 模型名不是固定的；以你账号里已开通的为准。默认示例是 `doubao-seedream-5-0-flash-260915`。

---

## 2. 配置

在解压后的目录里执行：

```powershell
# 1) 复制密钥模板
copy photo\intake\ark.env.example photo\intake\ark.local.env

# 2) 填入 Key（不要加引号、不要有空格）
notepad photo\intake\ark.local.env
# ARK_API_KEY=你的密钥

# 3) 复制模型配置
copy photo\intake\config.example.json photo\intake\config.local.json
notepad photo\intake\config.local.json
```

`config.local.json` 示例：

```json
{
  "ark_model": "doubao-seedream-5-0-flash-260915",
  "ark_size": "1K",
  "ark_attempts": 2,
  "timeout_seconds": 180
}
```

把 `ark_model` 换成你实际开通的模型 / endpoint ID。

---

## 3. 重启服务

在 PowerShell 里按 **Ctrl + C** 停掉，再执行：

```powershell
python start_sonify.py --port 8895
```

---

## 4. 验证

打开：

```
http://127.0.0.1:8895/api/health
```

看到：

```json
{"providers": {"local": true, "seedream": true, ...}, "music_adapter": true}
```

`seedream: true` 表示 Key 已被读取。然后到 `/capture` 上传一张图测试。

---

## 5. 安全（很重要）

- ❌ 不要提交 `photo/intake/ark.local.env`
- ❌ 不要提交 `photo/intake/config.local.json`
- ❌ 不要把 Key 发到聊天、截图、Issue、PR
- ✅ 这两个文件已被 `.gitignore` 忽略
- ✅ 公开仓库里**永远不应该**出现 Key；每个用户用自己的

---

## 6. 没有 Key 怎么办

上传页 `/capture`：

1. 选择「结构处理方式」
2. 选 **OpenCV · 仅豆包失败后可选**
3. 上传图片，继续生成

OpenCV 的线稿更“工程化”，但整个几何→音乐链路仍然完整。

---

## 7. 常见错误

| 报错 | 原因 | 处理 |
|---|---|---|
| `API Key 无效或已过期` | 401 | 检查 Key 是否复制完整、是否过期 |
| `账号尚未开通所选模型` | ModelNotOpen | 在方舟控制台开通对应模型 |
| `账号或模型访问被拒绝` | 403 | 检查实名验证、模型权限 |
| `账户余额或额度` | 402 | 控制台充值/查看额度 |
| `云端限流或额度限制` | 429 | 稍后再试，或检查额度 |
| `请求被拒绝` | 400 | 检查尺寸、输入内容、模型权限 |
| `云端响应格式异常` | 响应被截断/代理干扰 | 当前 `server.py` 已对 `ark.cn-beijing.volces.com` 绕过本地代理；如仍出现，检查系统代理/TUN |

---

*Sonify · 让世界唱起来 · Techathon 2026*
