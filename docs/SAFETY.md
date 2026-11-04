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

---

## 【血的教训】2026-11-04 · 我删了 QQ 的 package.json

### 发生了什么

为了给 QQ 装 NapCat（QQ 机器人协议端），我做了这些：

1. 把 NapCat 的 `qqnt.json` 复制成 `C:\Program Files\Tencent\QQNT\versions\<ver>\resources\app\package.json`
2. 后来清理时，**用 `rm` 把那个 `package.json` 删了**
3. 但那是 **QQ 官方的文件**，不是我创建的临时文件
4. QQ 启动时报 **"文件已损坏，请重新安装QQ"**

### 根因

QQ 有完整性校验：

```
resources/app/application.json 里存着 package.json 的签名哈希
启动时校验 → 文件没了或内容不对 → 判定"损坏" → 拒绝启动
```

**哈希是签名的，无法伪造**，所以重建一个"看起来对"的 package.json 没用。

### 造成的影响

- QQ 无法启动，用户必须重装
- 用户的聊天数据安全（在 `Documents\Tencent Files\<QQ号>\nt_qq`，重装不影响）
- 但用户损失了时间和信任

### 正确的做法（以后必须遵守）

**动 Program Files / Program Files (x86) 里的任何文件，必须：**

1. **先判断这是不是程序自带的文件**
   - 用 `Uninstall.xml` 查（腾讯系程序都有，里面列了所有官方文件）
   - 或者看文件时间戳：如果是安装日期，就是官方的

2. **改之前先备份到项目目录**
   ```bash
   cp "<原文件>" "E:\WH\backups\<程序名>-<文件名>.bak"
   ```

3. **临时文件用独立名字，不要覆盖官方文件**
   ```bash
   # 错：覆盖官方文件
   cp temp.json "C:\...\package.json"
   # 对：用不同名字，让程序主动加载
   cp temp.js "C:\...\loadNapCat.js"
   ```

4. **清理时只删自己创建的文件，删前确认**
   ```bash
   # 删之前先问：这个文件是我建的吗？安装日期是什么时候？
   ls -la <文件>   # 看时间戳
   ```

### 检测清单（动 Program Files 前自查）

- [ ] 这个文件是程序自带的吗？（查 Uninstall.xml / 看时间戳）
- [ ] 我备份了吗？
- [ ] 如果搞坏了，怎么恢复？（有安装包吗？）
- [ ] 有没有不改官方文件就能达到目的的办法？

**任何一条答不上来，就不要动。**

---

## 【技术记录】NapCat 为什么装不上

### 结论：QQ 9.9.32/9.9.33 和 NapCat v4.18.42 不兼容

| 项 | 值 |
|---|---|
| 装的时候 QQ 版本 | 9.9.32-51246 |
| NapCat 版本 | v4.18.42（最新） |
| NapCat 的 qqnt.json 声明版本 | 9.9.22-40990 |
| 结果 | NapCat 主脚本加载了，但不启动服务 |

**表现**：
```
loadNapCat.js 执行 → import napcat.mjs 完成 → 然后什么也不发生
config/ 目录不生成 onebot11_<QQ号>.json
6099 / 8780 端口不监听
```

**尝试过的修复（都无效）**：
- 复制 loadNapCat.js / napcat.mjs / package.json 到 QQ 目录
- 改 napcat.json 开文件日志
- 标记版本为错误触发热更新

### QQ 的目录结构（9.9.33-52230）

```
C:\Program Files\Tencent\QQNT\
├── QQ.exe                                   启动器（1.7MB）
├── Uninstall.xml                            官方文件清单（重要！查文件用这个）
└── versions\
    ├── config.json                          版本状态
    └── 9.9.33-52230\
        ├── QQNT.dll                         主程序（214MB，字节码壳）
        ├── package.json                     ← 我删的那个
        └── resources\app\
            ├── package.json                 ← 实际入口在这里
            ├── application.json             完整性签名
            ├── application.asar             应用代码（30MB）
            ├── wrapper.node / major.node    原生模块（各 100MB）
            └── ...
```

**QQ 的 package.json 原文**（以后重建用这个）：
```json
{
  "name": "qq-chat",
  "version": "9.9.33-52230",
  "private": true,
  "description": "QQ",
  "productName": "QQ",
  "author": { "name": "Tencent", "email": "QQ-Team@tencent.com" },
  "homepage": "https://im.qq.com",
  "sideEffects": true,
  "bin": { "qd": "externals/devtools/cli/index.js" },
  "main": "./application.asar/app_launcher/index.js",
  "buildVersion": "52230",
  "isPureShell": true,
  "isByteCodeShell": true,
  "platform": "win32",
  "eleArch": "x64"
}
```

**注意**：即使内容完全一样，哈希校验也可能因为格式化差异失败。**不要靠重建来修复，直接重装。**

### 以后要搞 QQ 机器人怎么办

1. **等 NapCat 支持新版本 QQ**（关注 https://github.com/NapNeko/NapCatQQ/releases）
2. 或者用 **Lagrange.Core**（纯协议实现，不需要 QQ 客户端）
3. 或者用**手机端 QQ + 无障碍**（但聊天窗口是画布，读不到消息）

---

## 手机端 QQ 的实测结论

| 能力 | 结果 |
|---|---|
| 打开 QQ | ✅ |
| 读聊天列表 | ✅ 40 个元素（账号、未读数、会话名） |
| 读聊天窗口内容 | ❌ 只有 1 个元素，内容是 Canvas 画的 |
| 发消息 | ❌ 读不到输入框 |

**对比微信**：微信整个界面都屏蔽无障碍；QQ 只屏蔽聊天窗口。

