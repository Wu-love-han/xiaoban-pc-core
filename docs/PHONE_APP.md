# 小伴手机端 App（Android）

## 这是什么

一个真正的 Android App（不是网页），WebView 包着小伴界面，**地址自动切换**。

- 包名：`com.xiaoban.app`
- 图标：青色圆点
- 体积：约 21 KB
- 最低 Android：7.0（API 24）

## 地址自动切换

App 启动时**并发探测**所有候选地址，谁先通用谁：

```
1. http://100.118.110.25:8770   ← Tailscale（同 WiFi / 异地都能用）
2. http://172.30.0.217:8770     ← 局域网（Tailscale 没开时）
```

探测方式：GET `/api/health`，2.5 秒超时。
成功的地址记在 SharedPreferences，下次优先用它。
WebView 加载失败会自动重新探测。

## 构建（不需要 Android Studio / Gradle）

```bash
cd E:\WH\firmware\phone-app
bash build.sh
```

产物：`xiaoban.apk`

工具链：
- JDK 21：`C:\Program Files\Microsoft\jdk-21.0.13.21-hotspot`
- Android SDK：`C:\AndroidSdk`（build-tools 35 + platforms/android-35）
- 签名密钥：`xiaoban.keystore`（密码 xiaoban123，别名 xiaoban）

构建流程：aapt2 编译资源 → aapt2 link → javac → d8 转 dex → 注入 APK → zipalign → apksigner 签名

## 安装

```bash
adb install -r xiaoban.apk
```

⚠️ **vivo 手机会弹「允许安装」确认框，必须在手机上点允许**，否则报
`INSTALL_FAILED_ABORTED: User rejected permissions`。

如果 adb 安装总被拒：
1. 手机设置 → 开发者选项 → 打开「USB 安装」
2. 或者把 APK 拷到手机，用文件管理器点开安装

## 已知问题

### 1. Tailscale 和 Clash 抢 VPN 槽位（重要）

Android 同一时间只允许**一个 VPN**。手机装了 Clash 之类翻墙软件时：
- Clash 占用 VPN 槽 → Tailscale 起不来 → 远距离地址不通
- 表现：`ps | grep tailscale` 查不到进程，`tun0` 是 Clash 的 172.19.x

**解决**：异地使用前，先在手机上关掉 Clash，再打开 Tailscale。

### 2. vivo 安装确认
见上。

### 3. 局域网 IP 会变
`172.30.0.217` 是电脑当前 IP，换网络会变。
改 `MainActivity.java` 里的 `CANDIDATES` 数组重新编译，或依赖 Tailscale 地址。

## 源码结构

```
firmware/phone-app/
├── AndroidManifest.xml
├── build.sh                    一键构建
├── xiaoban.keystore            签名密钥
├── res/mipmap-*/ic_launcher.png 图标
└── src/com/xiaoban/app/MainActivity.java
```


## 2026-11-03 更新：缓存坑 + Tailscale 连接方法

### 缓存坑（已修）
手机 WebView + Service Worker 双层缓存，改了前端手机上还是旧的。
修法：
1. 服务端给 `.html/.js/.css/.webmanifest` 加 `Cache-Control: no-cache`
2. App 的 WebView 设 `LOAD_NO_CACHE`
3. 实在不行：`adb shell pm clear com.xiaoban.app`

### 打开 Tailscale（解决远距离）
用 adb 可以直接点开并连接：

```bash
adb shell am start -n com.tailscale.ipn/.MainActivity
# 等界面出来后点 Connect 按钮（坐标约 540,1372）
adb shell input tap 540 1372
```

连上后手机 `tun0` 会拿到 `100.115.152.111`，PC 端 `tailscale status` 显示 `active`。

### 底部显示的地址
侧边栏底部显示「局域网 · 172.30.0.217:8770」或「Tailscale · 100.118.110.25:8770」，
表示手机当前实际连的是哪条路。
