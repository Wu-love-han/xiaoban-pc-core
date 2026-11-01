# 小伴 · PC-CORE

> 一个住在你 Windows 电脑里的伙伴。她会聊天，也会动手。
> **这两件事是同一件事。**

重写版：不复用 `C:\dog` 旧后端的任何代码，只继承它踩过的坑。

---

## 一句话说清这次改了什么

| | 旧（C:\dog） | 新（这里） |
|---|---|---|
| 怎么分清指令和聊天 | 先问模型「这是 task 还是 chat」，判成 task 就切模式 | **不问。** 模型调了工具就是指令，没调就是聊天 |
| 人格在不在 | 只有 chat 分支有；task 分支变成冷回显 | **全程在线**，人格 system prompt 每轮都带 |
| 工具几个 | 4 个，写死在 if-else 里 | **18 个**，一个文件一个，自动发现 |
| 加一个工具要改几处 | 3 处（agent_tools / plan prompt / 意图 prompt） | **1 处**：新建一个文件 |

---

## 快速开始

```bat
:: 双击
start.bat

:: 或命令行
powershell -ExecutionPolicy Bypass -File start.ps1
```

浏览器打开 **http://127.0.0.1:8770**

停止：`stop.bat`

### 启动脚本会做什么

1. 找 Python（优先 `.venv`，其次 `C:\dog\01-工程源码\.venv`，最后 PATH）
2. 检查 fastapi / uvicorn / httpx
3. 检查 8770 端口，被占用就问你要不要结束旧进程
4. 起 uvicorn

---

## 目录

```
pc-core/
├── start.bat / start.ps1 / stop.bat   启动器
├── config/config.json                 配置（改完自动生效，不用重启）
├── docs/
│   ├── README.md                      ← 你在这
│   ├── CONTRACT.md                    ★ 接口法律（改代码前必读）
│   ├── PERSONA.md                     ★ 人格设定书（改人格只改这个）
│   └── DECISIONS.md                   决策记录（为什么这么定）
├── core/                              内核
│   ├── paths.py                       路径与默认配置
│   ├── config.py                      配置读写（带 mtime 缓存）
│   ├── db.py                          SQLite（sessions/messages/tool_runs/approvals/events/memories）
│   ├── persona.py                     读 PERSONA.md 当 system prompt
│   ├── toolbase.py                    工具注册表：发现/校验/执行
│   ├── brain.py                       ★ 一轮对话的完整生命周期（核心）
│   ├── events.py                      事件名常量
│   └── providers/
│       ├── base.py                    ProviderEvent / ToolCallAccumulator
│       ├── openai_compat.py           本机网关（默认大脑）
│       └── ollama.py                  本地兜底
├── tools/                             18 个工具，一个文件一个
├── server/                            FastAPI 路由 + SSE
├── web/                               单页控制台（纯原生，无依赖）
├── tests/                             pytest
├── data/pccore.db                     数据库（自动建）
├── workspace/                         默认写文件目录
└── logs/
```

---

## 大脑是怎么转的

```
用户：「看看 E:\WH 里有什么」
   │
   ├─ 拼 messages = 人格 system prompt + 工具清单 + 记忆 + 历史 + 这句
   │
   ├─ 调模型（流式）──→ content 增量直接推给前端
   │
   ├─ 模型返回 tool_calls: [pc.list_dir{"path":"E:\\WH"}]
   │     │
   │     ├─ 不是危险工具 → 直接执行 → 推 tool_result 事件
   │     └─ 是危险工具 → 建 approval → 推 approval 事件（带人格化的话）→ 等人点头
   │
   ├─ 把工具结果以 role=tool 回灌
   │
   ├─ 再调模型 ──→ 「看了，里面四个文件，都是跑分记录」
   │
   └─ turn_end
```

**没有第二个分类器。** 上面那个 `tool_calls` 就是「这句话是指令」的唯一证据，
它会连同整轮消息一起落进 `messages.tool_calls`，事后能查。

---

## 配置

`config/config.json`，改完**下一轮就生效**（带 mtime 检测），不用重启。

```jsonc
{
  "brain": {
    "provider": "gateway",              // gateway | ollama
    "model": "deepseek/deepseek-flash",
    "reasoning": "none",                // none（快）| high | max（深）
    "max_rounds": 6,                    // 一轮最多几次工具往返
    "history_turns": 8,
    "approval_timeout_s": 300
  },
  "providers": {
    "gateway": { "base_url": "http://127.0.0.1:3425/v1" },
    "ollama":  { "base_url": "http://127.0.0.1:11434" }
  },
  "server": { "host": "127.0.0.1", "port": 8770, "auth_token": "" }
}
```

### 换模型

改 `brain.model` 为任意网关支持的模型名即可，或者用界面右上角设置面板。

当前网关可用（实测 `GET /v1/models`）：
`deepseek/deepseek-flash`、`deepseek/deepseek-v4-pro`、`workbuddy-ai/glm-5.3`、
`workbuddy-ai/kimi-k3.1-pro`、`auto/deepseek-v4-pro` 等 70+ 个。

### 断网了怎么办

`provider=gateway` 打不开时会自动降级到 `ollama/qwen2.5:7b`，
前端会看到「已降级」提示，功能不中断（工具照样能跑，只是模型换成本地的）。

---

## 加一个工具（30 秒）

新建 `tools/t_my_tool.py`：

```python
TOOL = {
    "name": "my.thing",
    "title": "我的工具",
    "desc": "一句话说清它能干嘛，这句会给模型看",
    "danger": False,
    "params": {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
    "run": lambda args, ctx: {"ok": True, "output": f"收到 {args.get('x')}"},
}
```

**完事。** 不用注册、不用改核心、不用重启（下次请求自动扫到）。
模型的 system prompt 里会自动多出这一条能力。

---

## 改人格

只改 `docs/PERSONA.md` 里 `## 系统提示` 之后的内容。保存即生效。

---

## 危险操作

`pc.write_file` / `pc.delete` / `pc.shell` 三个标记为 `danger`。
执行前会在对话里问一句（用人格问，不是系统弹窗），拒绝则**绝不执行**，300 秒不答作废。

---

## 测试

```bat
C:\dog\01-工程源码\.venv\Scripts\python.exe -m pytest tests/ -q
```

覆盖：数据层 CRUD、流式 tool_calls 增量合并、大脑循环（聊天不调工具 / 指令调工具 /
危险动作拦截 / 工具异常不崩 / 轮数上限 / 中止）、API 契约、SSE 帧格式。

---

## 给手机 / 局域网用

1. `config/config.json`：
   - `server.host` 改 `0.0.0.0`
   - `server.auth_token` 填一串随机字符（**必须填**，否则等于没锁）
2. 防火墙放行 8770
3. 手机访问 `http://<你的IP>:8770`
4. 页面右上角设置里填 token，或 URL 带 `?t=<token>`

> 不要用 `0.0.0.0` 且留空 token —— 那等于把电脑交给整个局域网。
