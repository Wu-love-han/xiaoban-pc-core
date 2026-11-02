# GitHub 连接 & DeepSeek API 接口

## 一、GitHub 连接（已完成）

走本机已登录的 `gh` CLI（系统 keyring），**软件本身不存 token**。

### 账户
- 当前登录：`Wu-love-han`
- scopes：`gist` / `read:org` / `repo`（私有仓库可读可装）
- 换账号 / 首次登录（在终端）：
  ```bash
  gh auth login          # 交互式，选 GitHub.com → HTTPS → 浏览器授权
  gh auth login --web    # 直接开浏览器
  gh auth switch         # 多账号切换
  ```

### API
| 端点 | 作用 |
|---|---|
| `GET /api/github/status` | 账户状态 + 登录引导 |
| `GET /api/github/search?q=xxx&limit=20` | 搜插件（优先生态，不够自动放宽） |
| `GET /api/github/repo?fullName=owner/repo` | 仓库详情 |
| `GET /api/github/releases?fullName=owner/repo` | Release 列表（含 zip 资产） |
| `POST /api/github/install` `{"fullName":"owner/repo"}` | 一键安装 |

### 搜索精度
搜索按三级放宽，结果带 `matchLevel`：
1. `<关键词> topic:dsh-plugin` → **精准**
2. `<关键词> dsh plugin` → **相关**
3. `<关键词>` → **通用**

### 前端
设置抽屉 → **GitHub 账户**（显示登录状态）+ **搜 GitHub 插件**（输入关键词 → 搜索结果 → 点「安装」）。

## 二、DeepSeek 官方 API（接口已留好，等你填 key）

### 现状
- 默认走本地 Magpie 网关：`http://127.0.0.1:3425/v1`
- 已预留 `deepseek` provider，配置在 `config/config.json`：

```json
"providers": {
  "deepseek": {
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "timeout_s": 180
  }
}
```

### 切换到官方 API（两步）
1. 填 key：`providers.deepseek.api_key = "sk-xxx"`（申请：https://platform.deepseek.com/api_keys）
2. 改 `brain.provider = "deepseek"`，`brain.model = "deepseek-chat"`（或 `deepseek-reasoner`）

也可以在设置面板里改模型名，但 provider 要手改 config.json。

### 三端共用
`core/providers/__init__.py` 是统一工厂：`gateway` / `deepseek` / `ollama` / `openai`。
三端（PC / 手机 / ESP32）都通过 PC 的后端调模型，所以**只改 PC 一处，三端同时生效**。

## 三、插件安装机制（修过的坑）

`shutil.move` 在目标目录还存在时会把新目录塞进旧目录里 → 导致工具加载 0 个。
已修复：先 `rmtree`，残留则改名挪走，确认清空再 move。
启动时自动清理 `.fetch-*` / `.old-*` / `.dl-*` 残留。

插件格式：
```
plugin.json        # {"id","name","version","description","author"}
tools/*.py         # 每个文件一个 TOOL 字典
```
