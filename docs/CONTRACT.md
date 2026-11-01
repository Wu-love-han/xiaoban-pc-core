# PC-CORE 工程契约（v1）

> **这份文件是「接口法律」。** 任何模块（内核 / 工具 / 服务端 / 前端）都必须按这里写的实现。
> 改契约 = 三方同时改，否则会静默错位。
>
> 建立：2026-11-01 ｜ 维护：Lead ｜ 代码根：`E:\WH\pc-core`

---

## 一、这次为什么要重做（旧流程的三个死因）

旧系统在 `C:\dog\01-工程源码\backend`，本工程**不改它一行**，只在旁边重来一遍。

| # | 旧做法 | 实测后果 |
|---|---|---|
| 1 | `task_agent.py` 先用一次模型调用判 `task / chat`，判成 task 就切到「执行器模式」 | 人格消失，回复变成冷冰冰的回显。用户原话：「为啥不是我们俩现在这种聊天」 |
| 2 | 判成 chat 的那条路上，工具只是「模型自己想起来才调」 | 指令被当闲聊吞掉，或者「好的」说完什么都不做 |
| 3 | 意图只有 `task / chat` 两档，工具只有 4 个 | 「指令单一」——稍微绕一点的说法就执行不了 |

**根因一句话：把「是不是指令」做成了一次独立的分类，而不是做成「模型自己决定要不要动手」。**

### 新原则（不可违背）

1. **没有意图分类器。** 全程只有一条模型调用链，人格 system prompt 始终在线。
2. **「是不是指令」= 模型有没有调工具。** 调了 = 指令，没调 = 聊天。同一个声音，同一个语气。
3. **判据可观测。** 每一轮把 `tool_calls` 落库并推到前端，事后能查「这句话当时被当成什么」。
4. **指令不单一。** 工具是一张可扩展的注册表，支持一次多调、多轮串行、参数由模型填。
5. **危险动作由人格开口确认**，不弹系统框，不静默执行。

---

## 二、分层

```
web/            浏览器控制台（可被用户自己的网站替换）
  │  HTTP + SSE
server/         FastAPI：路由、鉴权、事件转发
  │  函数调用
core/           大脑：persona → provider(流式) → 工具循环 → 事件
  │  子进程/HTTP/文件
tools/          真实动作：开程序、读写文件、搜索、联网、设备、记忆
  │
  ▼
PC（本机）
```

**依赖方向严格单向：`web → server → core → tools`。**
`tools` 不许 import `core.brain`；`core` 不许 import `server`。

---

## 三、数据模型（SQLite，`data/pccore.db`）

WAL 模式。所有时间戳是 **Unix 毫秒整数**。

### 3.1 `sessions`
| 列 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | `s_` + 12 位随机 |
| `title` | TEXT | 首句前 24 字 |
| `created_at` | INTEGER | |
| `updated_at` | INTEGER | |
| `meta` | TEXT | JSON，预留 |

### 3.2 `messages`
| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `session_id` | TEXT | 索引 |
| `role` | TEXT | `user` / `assistant` |
| `content` | TEXT | 纯文本（工具过程不进这里） |
| `thinking` | TEXT | 推理内容，可为空 |
| `tool_calls` | TEXT | JSON 数组，本轮模型发起的工具调用（**这就是「被判成指令」的证据**） |
| `created_at` | INTEGER | |
| `meta` | TEXT | JSON：model / latency_ms / usage |

### 3.3 `tool_runs`
| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | |
| `session_id` | TEXT | |
| `call_id` | TEXT | 与 provider 返回的 tool_call.id 一致 |
| `name` | TEXT | 工具名 |
| `args` | TEXT | JSON |
| `ok` | INTEGER | 0/1 |
| `output` | TEXT | 已截断到 4000 字 |
| `ms` | INTEGER | 耗时 |
| `created_at` | INTEGER | |

### 3.4 `approvals`
| 列 | 类型 | 说明 |
|---|---|---|
| `id` | TEXT PK | `a_` + 12 位 |
| `session_id` | TEXT | |
| `call_id` | TEXT | |
| `name` | TEXT | |
| `args` | TEXT | JSON |
| `status` | TEXT | `pending` / `approved` / `denied` / `expired` |
| `created_at` / `decided_at` | INTEGER | |

### 3.5 `events`
| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | |
| `session_id` | TEXT | 可为空 |
| `kind` | TEXT | 见第四节 |
| `payload` | TEXT | JSON |
| `ts` | INTEGER | |

### 3.6 `memories`
| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | |
| `scope` | TEXT | `global` / 会话级 |
| `key` | TEXT | |
| `value` | TEXT | |
| `weight` | REAL | 默认 1.0，被召回一次 +0.1 |
| `created_at` / `updated_at` | INTEGER | |

---

## 四、事件（SSE，`text/event-stream`）

一次 `/api/chat` 请求按顺序可能产出：

| `event:` | `data:` 结构 | 何时 |
|---|---|---|
| `session` | `{"session_id": "s_xxx"}` | 立刻，第一帧 |
| `thinking` | `{"text": "..."}` | 推理增量（可能没有） |
| `content` | `{"text": "..."}` | 正文增量，**唯一该渲染到气泡里的** |
| `tool_call` | `{"call_id","name","title","args"}` | 模型发起一个工具调用 |
| `tool_result` | `{"call_id","name","ok","output","ms"}` | 工具执行完 |
| `approval` | `{"approval_id","call_id","name","args","say"}` | 需要人确认；`say` 是人格化的一句话 |
| `turn_end` | `{"message_id","tool_count","latency_ms","usage":{"in","out"}}` | 本轮结束 |
| `error` | `{"message"}` | 出错，流随即关闭 |

**规则**
- 每帧必须是单行 JSON（`json.dumps(ensure_ascii=False)` 后不许有裸换行）。
- 心跳：15 秒无事件发 `: ping` 注释行，防代理断流。
- `content` 和 `tool_call` 可以交替出现（模型先说要做什么，再调工具，再说结果）。

---

## 五、HTTP 接口

前缀 `/api`。除 `/api/health` 外，若配置了 `auth_token`，需请求头 `X-PC-Token`。

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/health` | — | `{ok, provider, model, tools, db, uptime_s}` |
| POST | `/api/sessions` | `{title?}` | `{id, title, created_at}` |
| GET | `/api/sessions` | `?limit=30` | `{items:[{id,title,updated_at,msg_count}]}` |
| GET | `/api/sessions/{id}/messages` | `?limit=100` | `{items:[{id,role,content,tool_calls,created_at}]}` |
| DELETE | `/api/sessions/{id}` | — | `{ok:true}` |
| POST | `/api/chat` | `{session_id?, text, model?, reasoning?}` | **SSE**（第四节） |
| POST | `/api/abort/{session_id}` | — | `{ok:true}` |
| GET | `/api/tools` | — | `{items:[{name,title,desc,danger,params}]}` |
| POST | `/api/approvals/{id}` | `{decision:"approve"\|"deny"}` | `{ok, status}` |
| GET | `/api/approvals` | `?status=pending` | `{items:[...]}` |
| GET | `/api/events` | `?limit=50&session_id=` | `{items:[{id,kind,payload,ts}]}` |
| GET | `/api/config` | — | 脱敏后的配置 |
| POST | `/api/config` | `{model?, reasoning?, provider?}` | 更新后的配置 |

### 5.1 `/api/chat` 请求体
```json
{ "session_id": "s_xxx", "text": "帮我把桌面那个 todo.txt 读一下", "model": null, "reasoning": null }
```
`session_id` 省略则新建会话（第一帧 `session` 会带回来）。

---

## 六、工具注册表（`tools/`）

每个工具模块暴露一个模块级 `TOOL` 字典：

```python
TOOL = {
    "name": "pc.read_file",            # 命名空间.动作，全局唯一
    "title": "读文件",                  # 给人看的短名（前端/事件用）
    "desc": "读取本机文本文件内容",      # 给模型看的说明，要写清边界
    "danger": False,                    # True = 需要人格开口确认
    "params": {                         # JSON Schema
        "type": "object",
        "properties": {"path": {"type": "string", "description": "绝对路径"}},
        "required": ["path"],
    },
    "run": run,                         # (args: dict, ctx: ToolContext) -> dict
}
```

### 6.1 返回值约定
```python
{"ok": True,  "output": "给人看的一行摘要", "data": {...任意...}}
{"ok": False, "output": "错在哪，一句人话",  "error": "ExceptionType: msg"}
```
- `output` **必须 ≤ 400 字**，超了工具自己截断。它会进模型上下文。
- 不许抛异常出去，一律 `ok:False`。

### 6.2 `ToolContext`
```python
@dataclass
class ToolContext:
    session_id: str
    call_id: str
    workspace: Path      # E:\WH\pc-core\workspace，写文件默认落这里
    config: dict
```

### 6.3 首批工具清单（名字已定，不许改）

| 工具 | danger | 作用 |
|---|---|---|
| `sys.info` | | CPU/内存/磁盘/显卡/系统版本 |
| `sys.time` | | 当前时间、时区、星期 |
| `pc.open_app` | | 启动程序或打开文件/网址 |
| `pc.list_dir` | | 列目录 |
| `pc.read_file` | | 读文本文件（≤200KB） |
| `pc.write_file` | ✅ | 写/覆盖文本文件 |
| `pc.append_file` | | 追加文本 |
| `pc.mkdir` | | 建目录 |
| `pc.delete` | ✅ | 删除文件/空目录 |
| `pc.search_files` | | 按文件名/内容搜 |
| `pc.shell` | ✅ | 白名单只读命令 |
| `net.web_search` | | 联网搜索 |
| `net.fetch` | | 抓网页正文 |
| `mem.remember` | | 记住一条 |
| `mem.recall` | | 按关键词召回 |
| `device.list` | | 列出可控设备 |
| `device.control` | | 控设备（灯/电视/风扇） |
| `device.speak` | | 让机器人说一句（走设备队列） |

> 工具**只加不改名**。新工具 = 新文件 + 自动被发现，不改核心代码。

### 6.3.1 工具名：规范名 vs 线上名（实测踩过，必须转）

| | 形态 | 用在哪 |
|---|---|---|
| **规范名** | `pc.list_dir` | 我们内部、数据库、前端、SSE 事件、`TOOL["name"]` |
| **线上名** | `pc_list_dir` | 发给模型的 `tools[].function.name` |

**为什么必须转**：实测 DeepSeek/OpenAI 的函数名只接受 `^[a-zA-Z0-9_-]+$`，
带点号会直接 **HTTP 400**：

```
Invalid 'tools[0].function.name': string does not match pattern.
Expected a string that matches the pattern '^[a-zA-Z0-9_-]+$'
```

不转的后果：每个请求都 400 → 降级到 Ollama → 默认大脑形同虚设。

**实现位置**：`core/toolbase.py`
- `to_wire(name)` —— 规范名转线上名
- `registry.schemas()` —— 自动用线上名生成
- `registry.to_canon(name)` —— 模型回来的线上名转回规范名（`core/brain.py` 每轮调用）
- 极端冲突（`pc.a_b` 与 `pc.a.b` 撞名）自动加 `_2` 后缀并打警告

**规则：写工具时 `TOOL["name"]` 一律用点号规范名，不要手写下划线。**

### 6.4 自动发现
`tools/__init__.py` 的 `load_all()` 扫 `tools/*.py`，跳过 `_` 开头，收集模块级 `TOOL`。
导入失败的工具只记警告，不影响其它工具。

---

## 七、大脑循环（`core/brain.py`）

```
用户一句话
  ↓
[1] 拼 messages = persona_system + 历史(N轮) + 用户这句
  ↓
[2] 调 provider 流式 → 边收边推 content / thinking 事件
  ↓
[3] 收到 tool_calls？
   ├─ 没有 → 直接结束，本轮是「聊天」
   └─ 有   → 对每个 call：
   │          danger? → 建 approval，推 approval 事件，等人决定（最长 300s）
   │          ├─ 拒绝 → 回灌 {"ok":false,"output":"用户没同意"}
   │          └─ 同意/不需要 → 执行 → 推 tool_result → 回灌 role=tool
   │        回到 [2]，最多 max_rounds=6 轮
  ↓
[4] 落库 + 推 turn_end
```

**关键约束**
- 工具结果回灌后**必须让模型再说话**——用户看到的最后一句话永远是人格的。
- `max_rounds` 用完还在调工具 → 用一句话收尾：「我卡住了，这个我先停下」。
- 任一轮 provider 报错 → 推 `error`，不吞。
- 一轮里 `content` 为空且没有工具调用 → 补一句兜底，不许前端空白。

---

## 八、Provider 抽象

```python
class Provider:
    name: str
    async def stream(self, messages, tools, *, model, temperature, top_p,
                     max_tokens, reasoning) -> AsyncIterator[ProviderEvent]: ...
```

`ProviderEvent`：`kind` ∈ `thinking | content | tool_call | done | error`。

必须实现两个：

| 实现 | 地址 | 说明 |
|---|---|---|
| `OpenAICompatProvider` | `config.json` 的 `base_url`，默认 `http://127.0.0.1:3425/v1` | 本机 Magpie 网关，**实测支持原生 function calling + 流式 tool_calls 增量**。默认大脑 |
| `OllamaProvider` | `http://127.0.0.1:11434` | 断网/网关没开时兜底，`qwen2.5:7b` |

**流式 tool_calls 增量必须按 `index` 合并**（实测网关会把 `arguments` 切成单字符片段发过来）。
合并规则：`id`/`name` 取首个非空；`arguments` 逐片字符串拼接；最后统一 `json.loads`，
解析失败则当空对象并把原文塞进 `output` 提示模型。

---

## 九、人格（`docs/PERSONA.md` → `core/persona.py`）

- **唯一权威**是 `docs/PERSONA.md`，代码里不许再散落人格字符串。
- `core/persona.py` 读该文件，抽 `## 系统提示` 段落作为 system prompt。
- 文件改了立即生效（每轮重读，带 mtime 缓存）。
- system prompt 结构固定三段：`【你是谁】` + `【你能动手】`（工具摘要自动生成）+ `【怎么说话】`。

---

## 十、编码与路径铁律

| 项 | 规定 |
|---|---|
| 所有 `.py` / `.md` / `.json` | **UTF-8 无 BOM** |
| 所有 `.bat` | **GBK + CRLF**（否则中文路径被 cmd 拆碎） |
| 所有 `.ps1` | **UTF-8 with BOM**（否则 PS 5.1 按 GBK 读成乱码） |
| 子进程读输出 | 必须 `encoding="utf-8", errors="replace"` |
| 路径 | 一律 `pathlib.Path`，不许手拼 `\\` |
| 启动 | 工作目录必须是 `E:\WH\pc-core`（否则相对路径全错） |
| **E: 盘是 exFAT** | 不支持硬链接/原子改名，`os.replace` 跨目录会失败；写文件用 `open(...,"w")` 直接写 |

---

## 十一、验收口径（可自动测）

1. `pytest tests/` 全绿。
2. 说「今天好累」→ **零工具调用**，回复像人（≤60 字，无 markdown）。
3. 说「看看 E:\WH 有什么」→ 调 `pc.list_dir`，**并且用她的语气把结果说出来**。
4. 说「把 X 写到 workspace/a.txt，然后读回来念给我听」→ 多轮工具，最终有人格收尾。
5. 说「删掉 workspace/a.txt」→ 先出 `approval` 事件，**拒绝则文件还在，同意才删**。
6. 每轮 `tool_calls` 落库，`GET /api/events` 能查回「这句话被判成什么」。
7. 拔掉网关 → 自动回落 Ollama，前端只看到降级提示，不白屏。
