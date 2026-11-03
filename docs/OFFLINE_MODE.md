# 手机离线自主（C 方案）

## 原理

```
PC 在线  → 手机加载 PC 的界面（快、省事，用 PC 的网关）
PC 离线  → 手机切原生聊天，用缓存的 DeepSeek API 自己干活
```

## 配置从哪来

PC 在线时，App 启动会调 `/api/app/brain`，拿到：
```json
{
  "usable": true,
  "baseUrl": "https://api.deepseek.com/v1",
  "model": "deepseek-chat",
  "apiKey": "sk-..."
}
```
存进 App 的 SharedPreferences。之后 PC 关了也能用。

**优先用官网 API**：因为 PC 主脑可能走本机网关（127.0.0.1），手机直连不了。
所以 `/api/app/brain` 会优先返回 `providers.deepseek` 的配置。

## 自主循环（AgentLoop）

```
用户说话 → 调模型 → 模型回 JSON
  {"tool":"ui_tree","args":{}}     → 执行工具，结果回灌，继续
  {"say":"..."}                    → 结束，显示给用户
最多 8 轮
```

本地工具：`ui_tree` / `click` / `click_xy` / `type` / `key` / `open_app` / `shell`

## 实测（2026-11-03）

```
1. PC 在线 → App 拉到配置
   {"configured":true,"baseUrl":"https://api.deepseek.com/v1","model":"deepseek-chat","hasKey":true}

2. 停掉 PC 后端 → 重启 App
   → 显示「电脑连不上，我先自己干着。」
   → 原生输入框 + 发送按钮
```

## 注意

- **API key 存在手机上**：离线自主的前提。App 的 `/brain/info` 只报状态，不返回 key。
- 主脑还是走网关（稳），只有手机离线时才用官网 API。
- 想把 PC 主脑也切到官网 API：改 `brain.provider = "deepseek"`、`brain.model = "deepseek-chat"`。
