# 小伴项目 · 文件地图

> 最后更新：2026-11-04
> 一句话：**PC 是大脑，手机是手，机器人是身体，控制台是给你看的。**

---

## 一、顶层目录

```
E:\WH\
├── pc-core\           ← PC 端主程序（大脑）
├── firmware\
│   ├── phone-app\     ← 手机 App 源码
│   └── esp32\         ← 机器人固件（空的，等板子）
├── qq-bot\            ← QQ 机器人（NapCat）
└── phone-agent\       ← 早期的手机 Agent（已被 App 取代）
```

---

## 二、pc-core 内部结构

```
pc-core\
├── core\              ← 核心逻辑
│   ├── brain.py            一轮对话的完整生命周期（最重要）
│   ├── memory_engine.py    记忆（短期/长期/印象/情绪）
│   ├── grand_log.py        总志（每轮读写）
│   ├── persona.py          人格加载（读 docs/PERSONA.md）
│   ├── reviewer.py         审核（高危动作判级）
│   ├── autopilot.py        主动行为调度
│   ├── proactive.py        主动消息队列
│   ├── proactive_gen.py    主动消息由模型生成
│   ├── consent.py          人工确认（底线文件）
│   ├── activity.py         实时活动（它在干嘛）
│   ├── notify.py           Windows 系统通知
│   ├── sync_hub.py         三端同步中枢
│   ├── plugins.py          GitHub 插件安装
│   ├── github_api.py       GitHub 搜索/仓库
│   ├── body_state.py       身体状态（模型知道自己能干什么）
│   ├── daily_review.py     每日复盘
│   ├── procedural.py       程序记忆
│   └── providers\          模型接入（gateway/deepseek/ollama）
│
├── tools\             ← 工具（每个文件一个 TOOL）
│   ├── _common.py          工具公共层（输出压缩）
│   ├── _adb_common.py      手机 ADB + App 端口
│   ├── _desktop_common.py  桌面鼠标键盘/截图
│   ├── t_pc_*.py           电脑工具（24 个）
│   ├── t_adb_*.py          手机工具（19 个）
│   ├── t_device_*.py       设备控制（灯/电视/风扇）
│   ├── t_mem_*.py          记忆工具
│   ├── t_voice_mode.py     语音
│   └── t_github_*.py       GitHub 搜索/安装
│
├── server\            ← HTTP API
│   ├── main.py             应用入口（注册所有路由）
│   ├── auth.py             鉴权（token / admin token）
│   └── routes\             各个 API 模块
│
├── console\           ← 控制台（独立进程，端口 8771）
│   ├── server.py           人用的后台（PIN 保护）
│   └── index.html          控制台界面
│
├── web\               ← 聊天界面（端口 8770）
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── manifest.webmanifest  PWA（可加到主屏幕）
│
├── docs\              ← 文档
│   ├── PERSONA.md          人格设定（改这个就改人格）
│   ├── GRAND_LOG.md        总志（自动维护）
│   ├── ARCHITECTURE.md     架构说明
│   ├── SAFETY.md           安全底线
│   ├── CONSOLE.md          控制台用法
│   ├── PHONE_AI.md         手机端 AI 说明
│   ├── PROJECT_MAP.md      这个文件
│   └── backups\            人格历史备份
│
├── scripts\           ← 辅助脚本
│   ├── tunnel.py           公网隧道
│   └── legacy\             旧启动脚本
│
├── data\              ← 运行时数据（不入库）
│   ├── pccore.db           主库（会话/消息/工具记录）
│   ├── memory.db           记忆库
│   ├── sync.db             三端同步
│   ├── consent.db          确认请求
│   └── proactive.db        主动消息
│
├── logs\              ← 日志（不入库）
├── workspace\         ← 临时文件/截图
├── plugins\           ← 已安装插件
│
└── 根目录文件
    ├── run_daemon.py       守护进程（崩了自动重启）
    ├── 启动小伴.bat        ← 你双击这个
    ├── 启动小伴-开机静默.bat  ← 开机自启用
    └── 启动公网隧道.bat    ← 外出访问用
```

---

## 三、三个端口

| 端口 | 是什么 | 谁能用 |
|---|---|---|
| **8770** | 主 API + 聊天界面 | AI + 你 |
| **8771** | 控制台（PIN 159270） | **只有你** |
| **9123** | 手机 App 本地服务 | PC 调手机 |

---

## 四、三端能力差异

| 能力 | PC | 手机 | 机器人 |
|---|---|---|---|
| 聊天 | ✅ | ✅ | ❌ |
| 记忆 | ✅ 完整 | ✅ 同步副本 | ❌ |
| 控电脑 | ✅ 24 工具 | ✅ 经 PC | ❌ |
| 控手机 | ✅ 19 工具 | ✅ 9 工具 | ❌ |
| 语音 | ✅ TTS+STT | ✅ TTS | 待定 |
| 看图 | ✅ | ❌ | ❌ |
| 离线自主 | ❌ | ✅ | ❌ |
| QQ | ❌ | ⚠️ 只能开不能读 | ❌ |

---

## 五、常用命令

```bash
# 启动全部
双击 启动小伴.bat

# 只启后端（调试用）
.venv\Scripts\python.exe run_daemon.py

# 看健康
curl http://127.0.0.1:8770/api/health

# 看控制台
浏览器打开 http://127.0.0.1:8771   PIN 159270

# 提交改动
git add -A && git commit -m "说明" && git push origin master
```
