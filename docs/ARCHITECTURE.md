# 小伴 ARCHITECTURE —— 数字生命分层架构

> 依据：用户手写笔记 + AI Agent Memory Architecture (TiDB Playbook) 的四层记忆模型。

## 一、记忆分层（4 层）

| 层 | 模块 | 存什么 | 检索方式 | 生效时机 |
|---|---|---|---|---|
| 工作记忆 | 上下文窗口 | 当前任务、最近几轮 | 直接进 prompt | 每轮 |
| 短期记忆 | `core/memory_engine.py` | 会话流水（保留 20 条） | 时间倒序 | 每轮写 |
| 长期记忆 | `core/memory_engine.py` | 事实/偏好/印象/好感度 | 关键词滑窗召回 | 每轮读+写 |
| **程序记忆** | `core/procedural.py` | 工具序列（哪类问题用哪串工具） | 意图关键词匹配 | 每轮读+写 |
| 总志 | `core/grand_log.py` | 全局状态 + 每轮总结 + 最近流水 | 全文读入 | 每轮读，**每轮写** |

## 二、执行分层

```
用户
 └─ 主大模型 root（PC，官方 API）
      ├─ 审核智能体 core/reviewer.py（高危二次判级）
      ├─ 电脑工具 25 个（文件/程序/终端/记忆/设备）
      ├─ 手机工具 15 个
      │    ├─ ADB 通道 8 个（截图/点击/滑动/输入/按键/开应用/当前应用/通知）
      │    └─ HTTP 通道 7 个（手机 Agent，Termux）
      ├─ GitHub 插件口（市场/Release/仓库）
      ├─ 主动行为 core/autopilot.py（60 秒 tick，主动发消息）
      └─ 能力插槽 core/capabilities.py（live/qq/models 预留）
```

## 三、一轮对话的完整生命周期

```
1. 用户输入
2. 读总志（grand_log.state_snippet）
3. 读长期记忆（recall_long_term）+ 印象 + 情绪 + 好感度
4. 读程序记忆（procedural.prompt_snippet）
5. 组装 system prompt（persona + 上面全部）
6. 主模型流式推理
7. 有 tool_call → 审核智能体判级 → 高危则等确认 → 执行 → 回灌
8. 写短期记忆 / 提取长期记忆 / 更新情绪
9. 写总志（一轮一条流水）
10. 写程序记忆（这类问题用了这串工具）
```

## 四、审核分级（core/reviewer.py）

| 级别 | 例子 | 处理 |
|---|---|---|
| low | 读文件、查时间、看通知 | 直接过 |
| mid | 写文件、跑命令、点手机 | 记录，不阻塞 |
| **high** | 删除、支付、转账、对外发送、发布 | **拦截，等用户确认** |

## 五、红线（永不执行）

支付/转账/银行卡、获取验证码密码、冒充用户发消息、批量注册账号、绕过平台风控。

## 六、文件地图

```
core/
  brain.py          一轮对话的生命周期（核心）
  persona.py        人格（读 docs/PERSONA.md）
  memory_engine.py  短期/长期记忆 + 情绪 + 好感度
  procedural.py     程序记忆（工具序列）
  grand_log.py      总志（每轮读写的全局状态）
  reviewer.py       审核智能体
  autopilot.py      主动行为调度
  capabilities.py   能力插槽
  plugins.py        GitHub 插件口
  toolbase.py       工具注册表
  db.py / config.py / paths.py / providers/
tools/              25 个电脑工具 + 15 个手机工具
server/routes/      API 路由
web/                前端（纯原生）
docs/               PERSONA / GRAND_LOG / ARCHITECTURE / ITERATION / CONTRACT / DECISIONS
```
