# 小伴手机端（Android）

## 这是什么

一个 WebView + 无障碍服务的 Android App。既是聊天界面，也是 PC 的「手」。

## 三个核心能力

| 能力 | 实现 |
|---|---|
| **看界面** | AccessibilityService 实时读（0.3 秒，比 uiautomator 快 8 倍） |
| **点/打字** | `performAction(CLICK)` / `ACTION_SET_TEXT`（中文没问题） |
| **系统命令** | 借 Shizuku 拿 shell 权限（uid=2000，不需要 root） |

## 本地服务（PC 调它）

端口 **9123**，监听 0.0.0.0，`X-PC-Token` 鉴权。

```
GET  /ping              探活
GET  /tree              实时界面树
GET  /foreground        当前前台包名
GET  /apps              已安装应用列表
GET  /shell/info        权限级别（shizuku / app）
GET  /brain/info        模型配置状态
GET  /memory/info       记忆缓存状态
POST /click             {text} 或 {x,y}
POST /type              {text}
POST /key               {name}
POST /open_app          {package}
POST /shell             {cmd, timeout}
```

## 两种运行模式

- **PC 在线**：加载 PC 的界面，用 PC 的全部能力
- **PC 离线**：原生聊天，用缓存的 DeepSeek API + 本地工具

断线时右上角显示「● 断开」，15 秒自动重连，**不切换界面**。

## 连接优先级

```
1. http://127.0.0.1:8770      ← USB（adb reverse，最稳）
2. http://100.118.110.25:8770 ← Tailscale（异地）
3. http://172.30.0.217:8770   ← 局域网
```

## 构建

需要 JDK 21 + Android SDK（build-tools 35 + platform-35）。

```bash
bash build.sh
# 产物：xiaoban.apk
```

## 已知问题

- **重装/被系统杀后无障碍会掉**：`启动小伴.bat` 会自动恢复
- **Shizuku 授权重装后要重新点允许**
- 微信等 App 屏蔽无障碍，拿不到界面树
