# 决策记录（ADR）

> 每条都是「当时为什么这么定」，避免以后反复推翻。
> 格式：编号 · 日期 · 结论 · 理由 · 代价

---

## D01 · 2026-11-01 · 废掉意图分类器，改用「有没有调工具」判指令

**结论**
不再有 `task_agent.classify_intent` 那种「先问模型 task 还是 chat」的独立判断。
「这句话是不是指令」= 模型这一轮**有没有发起工具调用**。

**理由**
旧链路实测的病：
- 判成 task → 切到执行器分支，人格消失，回复变成 `搞定啦！+ 输出前120字`
- 判成 chat → 工具只能靠模型自己想起来，指令容易被当闲聊吞掉
- 分类本身多一次模型调用，8GB 显存下是实打实的延迟

而且分类器把「一个人」劈成了「两种模式」，这与产品目标是冲突的。

**代价**
- 模型必须在有工具描述的情况下自己判断，prompt 要写清楚边界（见 PERSONA.md 第五节）
- 需要 `tool_calls` 落库做可观测性，否则出问题没法查（已做，见 messages.tool_calls）

---

## D02 · 2026-11-01 · 人格唯一权威是 docs/PERSONA.md，代码里不许有文案

**结论**
`core/persona.py` 运行时读 `docs/PERSONA.md` 的 `## 系统提示` 段落当 system prompt，
带 mtime 缓存，改文件下一轮就生效。

**理由**
旧工程人格散在 `personas.py` 的 4 个 dict 里，加上 orchestrator 里的
`DEVICE_CAPABILITY` / `SEARCH_CAPABILITY` 两段硬编码字符串，改一处忘一处。

**代价**
多一次文件 stat（可忽略）；人格文件被误删时要用兜底 prompt（已实现并打 error 日志）。

---

## D03 · 2026-11-01 · 默认大脑用本机 Magpie 网关，Ollama 做兜底

**结论**
`brain.provider = gateway`，`base_url = http://127.0.0.1:3425/v1`。
`fallback_provider = ollama`，`qwen2.5:7b`。

**理由（实测数据，2026-11-01）**

| 通道 | 简单闲聊首字 | 原生 function calling | 备注 |
|---|---|---|---|
| 网关 deepseek/deepseek-flash | 3.2s（reasoning=none） / 6.6s（默认） | ✅ 流式增量 | 需要 `reasoning_effort=none` 才快 |
| Ollama qwen2.5:7b | <1s | ⚠️ 不稳（旧工程踩过） | 断网可用、零成本 |

网关的推理质量与工具调用稳定性明显更好，符合「指令不单一」的目标；
Ollama 保证断网时系统不瘫。

**代价**
- 网关需要联网/需要 Magpie 在跑；没开时首轮会失败一次再降级（前端会看到降级提示）
- `reasoning=none` 会牺牲部分思考深度，所以设置面板留了 high/max 可切

---

## D04 · 2026-11-01 · 工具「一个文件一个工具」，自动发现

**结论**
`tools/t_*.py`，每个模块暴露一个 `TOOL` 字典。`core/toolbase.load_package()` 自动扫描。

**理由**
旧工程工具写死在 `agent_tools.py` 的 if-else 里，加一个工具要改三个文件。
现在加工具 = 新建一个文件，核心代码零改动。

**代价**
模块多了（18 个文件），但每个都很短，且互不影响——某个工具写错只丢它自己。

---

## D05 · 2026-11-01 · 危险动作走「人格开口确认」，不弹系统框

**结论**
`danger=True` 的工具（write_file / delete / shell）执行前：
1. 建 approval 记录
2. 推 `approval` SSE 事件，带一句**人格化的话**（如「删之前问一句——E:\WH\a.txt，真删啊？」）
3. 等最多 300 秒，超时作废
4. 拒绝 → 工具**不执行**，把 `{"ok":false,"output":"用户没同意"}` 回灌给模型

**理由**
旧工程用系统 confirm，冷冰冰且打断对话。
现在确认本身就是对话的一部分，符合「她是一个人」的设定。

**代价**
一轮对话可能挂起 300 秒（SSE 有心跳，不会断）；服务重启会丢掉 pending approval（可接受）。

---

## D06 · 2026-11-01 · 不向量检索，记忆用关键词 + 热度

**结论**
`core/db.py` 的 `remember/recall`：关键词 LIKE（中文 2 字滑窗）+ weight 排序，
每次被召回 `weight += 0.1`，重复记住同一 key 则更新并 `+0.2`。

**理由**
8GB 显存要留给主模型。向量库（哪怕 sqlite-vec）也要 embedding 模型常驻，
实测旧工程 7B 已占 4.4GB，再挂 embedding 会挤爆。

**代价**
召回精度不如语义检索。缓解：`recall` 同时取高权重项，不是纯字面匹配。

---

## D07 · 2026-11-01 · 新工程放 E:\WH\pc-core，旧工程 C:\dog 一行不改

**结论**
完全新建目录，旧后端保持原样可运行。

**理由**
用户明确要求「不要在原基础上改，重新来试试」。
旧工程的价值是**踩过的坑**（编码、exFAT、鉴权、SSE），不是代码本身。

**代价**
两套代码并存，磁盘多占一点；`docs/DECISIONS.md` 里记录了旧工程的关键结论供参考。

---

## D08 · 2026-11-01 · 编码三铁律（踩过的坑，别再踩）

| 文件类型 | 编码 | 换行 |
|---|---|---|
| `.py` / `.md` / `.json` | UTF-8 **无 BOM** | LF 或 CRLF 均可 |
| `.bat` | **GBK(936)** | **CRLF** |
| `.ps1` | **UTF-8 with BOM** | CRLF |

**理由（旧工程实测）**
- `.ps1` 存 UTF-8 无 BOM → PS 5.1 按 GBK 读 → 中文乱码 → `Unexpected token` 语法错
- `.bat` 存 UTF-8 → cmd 按 GBK 读 → 中文命令被拆碎 → `'ame"' 不是内部命令`
- exFAT + 中文路径 + GBK 三重叠加时，`cmd /c` 会把 `C:\dog\01-工程源码\...` 截断

**代价**
写文件时必须显式指定编码，不能靠默认。`start.bat` / `stop.bat` / `start.ps1` 已按此生成。

---

## D09 · 2026-11-01 · E: 盘是 exFAT，写文件不用原子改名

**结论**
所有写文件用 `open(path, "w", encoding="utf-8")` 直接写。
不用 `os.replace` / 硬链接 / 临时文件+改名。

**理由**
exFAT 不支持硬链接，`os.replace` 跨目录会失败（实测 DSH 的 write 工具在本盘报
`EISDIR: illegal operation on a directory, link ...`）。

**代价**
写入过程中断电可能留下半个文件。对本工程（配置/日志/用户文件）可接受。
