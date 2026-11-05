# 权限体系（2026-11-05 放开后）

## 一句话

**以前只能"看"，现在能"做"。** 用分级审批代替了只读白名单。

---

## 一、pc.run —— 跑任意命令

取代了原来的 `pc.shell`（只读白名单，75 条）。

### 分级

| 等级 | 例子 | 处理 |
|---|---|---|
| **0 只读** | `dir` `type` `netstat` `git status` `dumpsys` | 直接跑 |
| **1 低危** | `mkdir`、未知命令、临时文件操作 | 直接跑 |
| **2 中危** | `pip install` `del` `rm` `taskkill` `git push` `echo > 文件` | **先问用户** |
| **3 高危** | `format` `bcdedit` `regedit` 系统目录操作 | **问 + 先备份** |
| **4 红线** | 转账/密码/验证码/冒充 | **永远拒绝** |

### 用法

```python
pc.run {"cmd": "dir"}                       # 等级0，直接跑
pc.run {"cmd": "pip install requests"}      # 等级2，会问
pc.run {"cmd": "pip install x", "dry_run": true}   # 只看判级，不执行
```

### 红线（永久禁止，不可绕过）

```
转账 汇款 支付 付款 银行卡 信用卡 花呗 白条
password passwd 密码 验证码 otp cvv keychain credential
冒充 impersonate
```

---

## 二、pc.write_tool —— 自己造工具

遇到没工具的场景，AI 自己写一个。

### 用法

```python
pc.write_tool {
  "action": "create",
  "name": "self.excel",
  "code": "完整 Python 代码（含 TOOL 字典）"
}
```

### 约束

- 工具名**必须 `self.` 开头**（一眼看出是自造的）
- 必须导出 `TOOL = {name, title, desc, danger, params, run}`
- 写到 `plugins/selfmade/tools/`
- **语法检查 → 加载验证 → 失败自动回滚**

### 管理

```python
pc.write_tool {"action": "list"}                  # 看造过哪些
pc.write_tool {"action": "delete", "name": "self.x"}  # 删掉
```

### 实测

```
造: 工具造好了：self.hello
  文件：E:\WH\pc-core\plugins\selfmade\tools\t_self_hello.py
  重载了 1 个自造工具，当前共 59 个工具
调: True 我是自造工具，WH 你好
```

---

## 三、临时授权 —— 别反复问

用户可以在控制台说"1 小时内等级 2 别问我"。

### 控制台

```
设置页 → 权限
  [1小时·等级2免确认]  [1小时·等级3免确认]  [撤销授权]
```

### API

```
POST /api/consent/grant   {"max_level": 2, "minutes": 60}
POST /api/consent/revoke
GET  /api/consent/grant
```

### 存储

`D:\xiaoban-data\consent_grant.json`，过期自动失效。

---

## 四、和 the agent harness 的对比

| | the agent harness | 小伴（现在） |
|---|---|---|
| 跑命令 | ✅ 任意 | ✅ 任意（分级审批） |
| 造工具 | ✅ | ✅ `pc.write_tool` |
| 红线 | 用户判断 | ✅ 硬编码禁止 |
| 临时授权 | ❌ | ✅ 有 |
| 备份高危操作 | ❌ | ✅ 等级3自动备份 |

---

## 五、还剩什么

| 能力 | 状态 |
|---|---|
| 子智能体 | ❌ 没做 |
| 上下文压缩 | ❌ 没做 |
| 多轮自主规划 | ⚠️ 有（20 轮上限） |
| 工具市场 | ⚠️ 只能从 GitHub 装插件 |

---

## 六、实测记录

```
用户：用 pc.run 查一下 E 盘剩余空间

AI：  tool_call pc.run {"cmd": "powershell -Command \"Get-PSDrive E | Select-Object Used,Free\""}
     tool_result ok=true [等级 1｜退出码 0｜803ms]
           Used         Free
           ----         ----
           682...
```

**它真的跑起来了。**
