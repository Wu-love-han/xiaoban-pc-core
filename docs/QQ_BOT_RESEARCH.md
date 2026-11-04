# QQ 机器人方案调研（2026-11-04）

## 结论先说

**现在三条路都走不通**，原因都是同一个：**腾讯封了第三方协议的签名**。

---

## 试过的三个框架

### 1. NapCat v4.18.42（QQ 客户端注入）

| 项 | 值 |
|---|---|
| 仓库 | https://github.com/NapNeko/NapCatQQ |
| 星数 | 12,241 |
| 位置 | `E:\WH\qq-bot\napcat\` |
| 原理 | 把 DLL 注入 QQ NT 客户端 |

**结果：失败**

```
NapCat 的 qqnt.json 声明 QQ 版本 9.9.22-40990
实际装的 QQ 版本      9.9.32 / 9.9.33
→ 主脚本 loadNapCat.js 加载了，但 napcat.mjs 不工作
→ 不生成 onebot11 配置，6099/8780 端口不监听
```

**代价**：过程中我误删了 QQ 的 `resources\app\package.json`，导致 QQ 报"文件已损坏"，用户重装。

---

### 2. LuckyLilliaBot v8.3.2（协议端）

| 项 | 值 |
|---|---|
| 仓库 | https://github.com/LLOneBot/LuckyLilliaBot |
| 星数 | 3,712 |
| 位置 | `E:\WH\qq-bot\llbot\` |
| 原理 | 基于 LagrangeV2 的协议实现，支持 OneBot 11 / Satori / Milky |

**结果：失败（缺授权）**

```
错误: 没有 Auth Token
      (bin/llbot/data/auth_token.txt 不存在)
请到 https://auth.luckylillia.com 获取
```

**Auth Token 要人工审核申请**（GitHub issues 里有人问"申请需要多久"），不是即时的。

---

### 3. Lagrange.OneBot（纯协议）

| 项 | 值 |
|---|---|
| 仓库 | https://github.com/LagrangeDev/Lagrange.Core |
| 星数 | 3,008 |
| 位置 | `E:\WH\qq-bot\lagrange\` |
| 版本 | nightly (2025-08-02)，win-x64 net9.0 自包含 |
| 原理 | 纯 C# 实现 NTQQ 协议，**不需要 QQ 客户端** |

**结果：失败（缺签名服务器）**

```
[SocketContext] Server: http://60.29.238.126:8080/ Latency: 36
[BusinessContext] [WARNING]: System.Exception:
    Signer server returned a NotFound
    at Lagrange.OneBot.Utility.OneBotSigner.Sign(...)
Unhandled exception. System.Exception: All login failed!
```

**它能连上腾讯服务器**（拿到了服务器列表和延迟），但**登录需要签名**，默认签名服务器已失效。

---

## 根本原因

腾讯从 2023 年起加固了 NTQQ 协议：

```
第三方客户端登录 → 需要腾讯签名的 t544 包 → 没有签名就登录失败
```

所以现在所有协议端都要"借"签名：

| 方案 | 签名来源 |
|---|---|
| NapCat | 注入官方 QQ 客户端，用客户端自己的签名 |
| LuckyLillia | 作者提供的授权服务（要申请） |
| Lagrange | 需要配置 `SignServerUrl`（公开的都失效了） |

**这不是技术问题，是腾讯的策略问题。**

---

## 现在能选的

### A. 申请 LuckyLillia 的 Auth Token（推荐）

```
1. 打开 https://auth.luckylillia.com
2. 注册并提交部署信息
3. 等人工审核
4. 拿到 token 后写到
   E:\WH\qq-bot\llbot\bin\llbot\data\auth_token.txt
5. 双击 LuckyLillia.exe 就能用
```

**文件已经下好解压好了，就等 token。**

### B. 买签名服务器给 Lagrange

搜"Lagrange 签名服务器"，有付费的（月付）。不推荐——灰色地带，随时可能挂。

### C. 等 NapCat 支持新版 QQ

关注 https://github.com/NapNeko/NapCatQQ/releases
等它更新 `qqnt.json` 里的版本号支持 9.9.33。

### D. 放弃 PC 端 QQ，只用手机端

手机端 QQ 实测：
- 能打开、能读聊天列表（40 个元素）
- 读不到聊天窗口内容（Canvas 渲染）

---

## 已经准备好的东西

```
E:\WH\qq-bot\
├── napcat\       NapCat v4.18.42（等 QQ 版本兼容）
├── llbot\        LuckyLilliaBot v8.3.2（等 auth token）
├── lagrange\     Lagrange.OneBot（等签名服务器）
└── 给PC端的请求.txt
```

三个都下载解压好了，哪个先能用就用哪个。

---

## 以后接 pc-core 怎么接

不管用哪个，它们对外都是 **OneBot 11 协议**：

```
LuckyLillia:  HTTP 3000 / WS 3001（默认）
Lagrange:     我在 appsettings.json 里配了 Http:8082 + ForwardWS:8081
NapCat:       配置里指定
```

pc-core 侧要加一个插件：

```
plugins/qq_bridge/
├── plugin.json
└── tools/
    ├── t_qq_send.py      pc.qq_send(to, text)
    ├── t_qq_recent.py    pc.qq_recent(limit)
    └── t_qq_groups.py    pc.qq_groups()
```

调 OneBot 的 HTTP 接口：
```
POST http://127.0.0.1:8082/send_private_msg   {"user_id":..., "message":"..."}
GET  http://127.0.0.1:8082/get_recent_contact
```
