# 手机控制指南（ADB 通道 + HTTP 通道）

小伴有两条"碰手机"的路，**USB 连着时优先走 ADB**（不用装任何东西）。

## 一、ADB 通道（推荐，USB 直连）

### 前提
1. 手机开「开发者选项 → USB 调试」
2. USB 连电脑，手机上点「允许 USB 调试」
3. 验证：`adb devices` 能看到设备

### 可用工具（8 个）

| 工具 | 作用 | 参数 | 级别 |
|---|---|---|---|
| `phone.screenshot` | 截图保存到 workspace | — | 只读 |
| `phone.tap` | 点击坐标 | `x`, `y` | 中 |
| `phone.swipe` | 滑动 | `x1,y1,x2,y2,ms` | 中 |
| `phone.input_text` | 输入文字 | `text` | 中（危险词拦截） |
| `phone.key` | 按键 | `key`=HOME/BACK/ENTER/POWER/VOLUP/VOLDOWN/RECENTS | 中 |
| `phone.open_app` | 开应用 | `package`（如 com.tencent.mm） | 中 |
| `phone.current_app` | 当前前台应用 | — | 只读 |
| `phone.notifications` | 读通知栏 | — | 只读 |

### 实测样例
```
phone.screenshot  -> E:\WH\pc-core\workspace\phone_screenshot.png (136 KB)
phone.current_app -> com.tailscale.ipn/com.tailscale.ipn.MainActivity
phone.notifications -> 读到微信、Tailscale 连接通知
```

## 二、HTTP 通道（手机 Agent，装 Termux）

见 `E:\WH\phone-agent\README.md`。7 个工具：
`phone.info` / `phone.apps` / `phone.clipboard_get` / `phone.speak` /
`phone.notify` / `phone.clipboard_set` / `phone.open_url`

## 三、权限底线（两条通道都遵守）

- **只读**（截图/读通知/列应用/当前应用）：直接允许
- **写**（点击/滑动/输入/开应用）：允许，但**输入内容含危险词直接拒**（支付/转账/密码/验证码/登录）
- **永不执行**：拨号、发短信、卸载应用、清除数据、修改系统设置、支付转账

## 四、坐标怎么来

截图是 1080×2408 物理像素，`phone.tap` 用的就是这套坐标。
AI 看截图后用 `phone.tap x y` 点，就像人用手指点。

## 五、无线调试（不插线也能用）

手机开「无线调试」→ 配对 `adb pair 手机IP:端口 配对码` → `adb connect 手机IP:端口`
之后所有 ADB 工具照常工作（走 WiFi/Tailscale）。
