# 三端同步协议（PC 中枢 / 手机 / 机器人）

## 架构

```
        ┌──────────────────────────────┐
        │  PC = 中枢 + 终端              │
        │  · 记忆/总志/对话（数据源）      │
        │  · DeepSeek API（模型）         │
        │  · 指令分发 + 日志汇总           │
        └──────┬──────────────┬────────┘
               │ LAN/Tailscale │ LAN
        ┌──────▼──────┐  ┌────▼─────────┐
        │  手机终端     │  │  ESP32 终端   │
        │ （可下指令）   │  │ （可下指令）   │
        └─────────────┘  └──────────────┘
```

**任何终端都能下指令**，目标终端领取后执行并回报。

## 同步的四类数据

| 类型 | 谁写 | 谁读 | 存储 |
|---|---|---|---|
| **指令** | 任意终端 | 目标终端 | `data/sync.db` commands 表 |
| **日志** | 任意终端 | 所有终端（按游标增量） | `data/sync.db` sync_logs 表 |
| **对话** | PC（AI 产生） | 所有终端 | `data/pccore.db` messages 表 |
| **记忆** | PC（AI 产生） | 所有终端 | `data/memory.db` |

## 安全模型（底线）

| 来源 | 要求 |
|---|---|
| **本机回环**（PC 自己的浏览器） | 免 token，直接可用 |
| **局域网 / Tailscale / 手机 / 机器人** | **必须带 `X-PC-Token`** |
| 没配 token 时的外部请求 | **一律 403 拒绝**（绝不裸奔） |

Token 在 `config/config.json` 的 `server.auth_token`。

## API 清单

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/sync/register` | `{id,name,kind,meta}` 注册终端 |
| POST | `/api/sync/heartbeat` | `{id}` 心跳（90 秒内有心跳算在线） |
| GET | `/api/sync/terminals` | 终端列表（含在线状态） |
| GET | `/api/sync/state` | 中枢总览 |
| POST | `/api/sync/command` | `{from_,to,text}` 下发指令 |
| GET | `/api/sync/commands?to=xxx` | 指令列表 |
| GET | `/api/sync/commands/claim?tid=xxx` | 目标终端领取待执行指令 |
| POST | `/api/sync/command/result` | `{id,ok,result}` 回报结果 |
| POST | `/api/sync/log` | `{tid,kind,text,data}` 写日志 |
| GET | `/api/sync/logs?since=<id>` | 按游标拉增量日志 |
| GET | `/api/sync/conversations?since_ms=` | 拉对话 |
| GET | `/api/sync/memory` | 拉记忆快照 |

## 实测记录（2026-11-02）

```
PC 注册为终端           → ✅
手机注册 (vivo V2445A)  → ✅
ESP32 注册 (陪伴机器人)  → ✅
手机下发"往前走三步"      → ✅
ESP32 领取并回报         → ✅
手机无 token 访问        → 401 ✅（被正确拒绝）
手机带 token 访问        → 200 ✅
```

手机实际请求日志（PC 端）：
```
172.30.188.163:49708 - "GET /api/sync/state" 401 Unauthorized
172.30.188.163:xxxxx - "GET /api/sync/state" 200 OK
```

## 网络地址

| 场景 | 地址 |
|---|---|
| PC 本机 | `http://127.0.0.1:8770` |
| 同一 WiFi（手机/ESP32） | `http://172.30.0.217:8770` |
| 异地（Tailscale） | `http://100.118.110.25:8770` |

## 启动方式

```bash
# 只给本机用
.venv\Scripts\python.exe run_daemon.py

# 给手机/机器人用（对外监听）
set PCORE_HOST=0.0.0.0
.venv\Scripts\python.exe run_daemon.py
```

## 手机端怎么用

浏览器打开 `http://172.30.0.217:8770`（或 Tailscale 地址）→ 设置 → 填「访问令牌」→ 保存。

## ESP32 端

见 `E:\WH\firmware\esp32\README.md`。
