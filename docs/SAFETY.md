# 安全底线（2026-11-03 定）

## 一、底线文件改动必须你本人确认

AI 改这几个文件时，**不能自己批准**，必须你在后台看板点「同意」：

| 文件 | 为什么 |
|---|---|
| `core/reviewer.py` | 审核红线（支付/密码/转账的判定） |
| `server/auth.py` | 鉴权（token 校验） |
| `tools/t_pc_self_update.py` | 它自己（防止把自己改坏） |

**流程**：
1. AI 调 `pc.self_update` 想改 → 自动生成确认请求，返回 `consent_id`
2. 后台看板弹出「⏳ 等你确认」+ **系统通知**弹出来
3. 你点「同意」或「拒绝」
4. AI 用 `consent_id` 重试 → 同意才放行

**关键**：确认只能用一次（用完作废），AI 没有任何接口能自己 approve。

## 二、改代码必须验证通过才能提交

```
write / patch  →  标记为「未验证」
verify         →  语法检查 + import 试跑 + JSON 校验
commit         →  只有验证过才允许，否则拒绝
```

没验证就提交会直接被拒：
> 这些文件改了还没验证，先 action=verify 再提交：docs/SAFETY.md

## 三、后台看板手机 AI 进不来

两套 token，分开的：

| token | 谁能拿 | 能干什么 |
|---|---|---|
| `auth_token` | 手机 App、所有终端 | 普通业务接口、AI 视图（只看统计） |
| `admin_token` | **只有你**，不下发给手机 | 后台看板、审批确认 |

实测：
```
本机回环                          → 200 ✅
手机 IP + 普通 token              → 403 ❌（AI 进不来）
手机 IP + admin token             → 200 ✅（你自己可以）
AI 视图 + 普通 token              → 200 ✅（只能看统计）
```

**为什么这么设计**：防止手机端 AI 自己下命令、然后说「是我说的」。

## 四、通知

三种情况会弹 Windows 系统通知（别的软件上也看得到）：
- 主动消息（提醒、资源告急）
- **有底线操作等你确认**（这个必弹）
- 任务完成

同类通知 30 秒冷却，不会刷屏。

## 五、当前 token（别外传）

```
普通 token : DVO5BZyPDRRLY_lJ-y-etSZn1UZSkF21guugqD-hz7U
管理 token : gkpKpSARrqzIeWOKS940O4IWN49MCxPc
```

后台看板第一次打开会让你填管理 token，填一次就记住（存在浏览器本地）。
