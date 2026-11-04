# 小伴手机端 · 更新日志

## v2.1.0 (2026-11-03 晚)

### 新增：手机端自主模式（C 方案：混合）
- **PC 在线**：照常加载 PC 的界面（快、省事）
- **PC 离线**：自动切到手机原生聊天，用缓存的模型配置自己调模型、自己动手
- 自主循环 `AgentLoop`：看界面 → 决定 → 执行 → 看结果 → 继续，最多 8 轮
- 本地工具：ui_tree / click / click_xy / type / key / open_app / shell
- 模型配置由 PC 的 `/api/app/brain` 下发并缓存（PC 在线时同步一次即可）

⚠️ 注意：离线自主需要**手机能直连的模型地址**。如果 PC 用的是本机网关
（127.0.0.1），手机会连不上——需要在 config.json 里填官网 API key。

### 修复
- 无障碍服务被强杀后不恢复：现在 App 启动时会重新请求 Shizuku 授权

## v2.1.0 (2026-11-03)

### 新增：Shizuku 系统级权限（不用 root）
- 借 Shizuku 拿到 **shell 权限（uid=2000）**
- 能装/卸应用、改系统设置、读系统信息、dumpsys、pm、am 等
- 本地服务新增接口：
  ```
  GET  /shell/info   看当前权限级别（shizuku / app）
  POST /shell        执行命令 {cmd, timeout}
  ```
- PC 端新增工具 `phone.shell`

### 新增：终端心跳
- App 启动时向 PC 注册成终端（id=phone）
- 每 45 秒心跳一次，后台看板能看到手机在线

### 关键踩坑（供以后参考）
1. **Shizuku AIDL 不在发布包里** —— 要从 `RikkaApps/Shizuku-API` 仓库拿 4 个 .aidl，用 `aidl.exe` 编译
2. **aidl.exe 路径敏感** —— MSYS 会转换路径，要用 `MSYS_NO_PATHCONV=1` + 反斜杠路径，或直接用 Python 调
3. **AIDL 生成的类必须打进 dex** —— d8 只打包 `com/xiaoban/app/*.class` 会导致 `NoClassDefFoundError`
4. **Manifest 必须声明两项**，否则 binder 不投递：
   ```xml
   <uses-permission android:name="moe.shizuku.manager.permission.API_V23" />
   <meta-data android:name="moe.shizuku.client.V3_SUPPORT" android:value="true" />
   ```

## v2.0.0 (2026-11-03)

### 新增：无障碍服务（核心）
- 实时读取界面结构（文字 + 坐标 + 可点击 + 可编辑）
- 直接对节点 `performAction(CLICK)`，不用算坐标点像素
- 直接 `ACTION_SET_TEXT` 写输入框，**支持中文**（之前 adb 只能打英文）
- 全局动作：返回 / 主页 / 多任务 / 通知栏

### 新增：本地能力服务（端口 9123）
把上面这些能力暴露成 HTTP，PC 直接调：
```
GET  /ping         探活
GET  /tree         实时界面树
GET  /foreground   当前前台包名
POST /click        点节点（text）或点坐标（x,y）
POST /type         写文字（中文没问题）
POST /key          返回/主页/多任务/通知栏
```
监听 0.0.0.0，Tailscale 和局域网都能连；X-PC-Token 鉴权。

### 新增：自更新
- 启动时查 PC 的 `/api/app/version`
- 版本号更新就下载 APK 并拉起安装器
- 自带极简 ContentProvider（不依赖 AndroidX）

### 修复
- HTTP 请求体按**字节**读（Content-Length 是字节数，按字符读会导致中文请求永远读不满 → 15 秒超时）
- 本地服务改**每请求一线程**（单线程时一次点击就会堵死整个服务）

### 性能对比
| 操作 | 旧方案（uiautomator/adb） | 新方案（无障碍） |
|---|---|---|
| 读界面 | 2.3 秒 | **0.28 秒** |
| 点击 | 需先读界面算坐标 | **0.29 秒** |
| 输入中文 | 不支持 | **0.70 秒** |
