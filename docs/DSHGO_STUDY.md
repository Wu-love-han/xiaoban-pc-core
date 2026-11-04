# dsh-Go 研究笔记（2026-11-04）

> 仓库：https://github.com/ccch1mneyyy/dsh-Go
> 星数：9062（Trendshift 全语言日榜 #1，2026-10-30）
> 许可证：AGPL-3.0

## 一、它是什么

DeepSeek Harness 的 **Android 客户端**，两种用法：
1. **手机上直接跑** —— App 内装 Ubuntu + Node.js + DSH（PRoot，免 root 免 Termux）
2. **遥控电脑** —— 通过 SSH 或 DSHarness Remote 连电脑上的 DSH

## 二、技术栈

| 语言 | 代码量 |
|---|---|
| Dart (Flutter) | 19.6 MB |
| Kotlin (Android 原生) | 2.3 MB |
| JavaScript | 2.1 MB |
| Python | 547 KB |
| TypeScript | 298 KB |

**架构**：Flutter 做 UI，Kotlin 做原生能力（无障碍、Shizuku、虚拟屏），PRoot 跑 Linux 环境。

## 三、它的手机操控设计（最值得学的部分）

### 3.1 三档确认

```
每次都询问（默认）  → 进新 App、发送、删除、付款前都问
本任务免确认        → 每个任务只问一次
免确认              → 全放开（有风险提示）
```

### 3.2 悬浮条（实时显示在干嘛）

三种形态可切换：
- **胶囊**：一行显示「点「发送」」+ 暂停/停止按钮
- **卡片**：展开看正在操作的应用、是否免确认、最近几步
- **小球**：贴边小圆点，按住 1 秒直接停止

**闲置不透明度** 30%-100% 可调，3 秒不碰变淡。

### 3.3 自动恢复无障碍（关键）

```
前提：手机操控开关开着 + 有 Shizuku/Sui/root/自连 ADB 权限
动作：只在系统里单独关掉无障碍时，尝试重新打开
限制：只改自己那条服务项，保留其他无障碍服务
退避：持续崩溃时逐渐延长重试间隔，最长约 10 分钟
```

### 3.4 特权通道保活（ShizukuStarter.kt）

```kotlin
// 检查状态
fun running() = Shizuku.pingBinder()
fun granted() = running() && Shizuku.checkSelfPermission() == GRANTED

// 绑定（15 秒超时）
Shizuku.bindUserService(args, listener)
owner.latch.await(15, TimeUnit.SECONDS)

// 绑定后 PROBE 验证
val probe = remote.execute(Bundle().apply { putString(OP, OP_PROBE) })
if (!probe.getBoolean(OK) || probe.getString("revision") != REVISION) return null

// 断开时立刻清理
override fun onServiceDisconnected(name: ComponentName?) {
    synchronized(guard) { if (binding === owner) retire(owner) }
    onChanged()
}

// 坑：API 13.1.5 的 unbindUserService(remove=true) 会留本地回调缓存
// 必须先 detach 再 kill
runCatching { Shizuku.unbindUserService(args, listener, false) }
runCatching { Shizuku.unbindUserService(args, listener, true) }
```

**恢复触发时机**（不做周期轮询）：
- App 插件 attach
- Activity 返回前台
- 新手机操控任务开始前
- Binder/网络可用性事件

**失败退避**：只在下一实际事件到来且距失败 ≥5 秒时重查，不安排定时唤醒。

### 3.5 其他细节

- **任务超时**：连续 3 分钟没有新操作，任务自动结束
- **敏感打码**：银行卡号、身份证号发给模型前先打码
- **熄屏停止**：任务进行中熄屏会停止任务
- **系统限制**：BOOT_COMPLETED 只排一个 Job，不启动 Activity/Flutter engine

## 四、我们学到的（已实现）

### 4.1 Keeper.java（v2.4.0）

```
位置：E:\WH\firmware\phone-app\src\com\xiaoban\app\Keeper.java
```

**做的事**：
1. 后台线程每 30 秒检查一次（失败翻倍，最长 10 分钟）
2. 检查 Shizuku 是否可用 + 无障碍是否开着
3. 无障碍掉了但 Shizuku 在 → 自动用 shell 修回来
4. 只动自己那条服务项，保留别人的

**和 dsh-Go 的差异**：
- 它事件驱动，我们定时（简单一些，功耗略高）
- 它用 UserService 绑定，我们直接用 Shizuku API（简单但恢复能力弱一些）

### 4.2 我们还缺的

| dsh-Go 有 | 我们 |
|---|---|
| 悬浮条（暂停/停止/插话） | ❌ 只有网页端状态条 |
| 三档确认 | ⚠️ 有确认机制但没分档 |
| 敏感信息打码 | ❌ |
| 任务 3 分钟超时 | ❌ |
| 虚拟屏（Android 14+，不占你屏幕） | ❌ 这是"后台操作"的真正解法 |

## 五、虚拟屏 —— 后台操作的正解

dsh-Go 文档提到「虚拟屏仍要求 Android 14/API34 以上」。

**这是 Android 14 的 `VirtualDisplay` + `InputManager` 注入**：
- 创建一个虚拟屏幕
- 在虚拟屏上跑 App
- 用 InputManager 注入触摸事件到虚拟屏
- **真实屏幕完全不受影响**

这就是用户想要的「后台操作不打扰」。

**代价**：需要 Shizuku/ADB 权限注入 InputManager，实现复杂。

## 六、结论

dsh-Go 是**成熟产品**，我们的「小伴」是**自建系统**。定位不同：

| | dsh-Go | 小伴 |
|---|---|---|
| 定位 | DSH 的客户端 | 自己的 AI（PC + 手机 + 机器人） |
| 手机跑什么 | DSH 引擎（Node.js） | 自己的 App（Java） |
| 控电脑 | 通过 SSH 连 DSH | 自己的 55 个工具 |
| 记忆 | DSH 自己的 | 自建分层记忆 + 三端同步 |
| 机器人 | ❌ | ESP32（待做） |

**可借鉴**：Keeper（已做）、悬浮条、三档确认、虚拟屏（以后做）。
