# 稳定性说明（段错误修复）

## 问题
2026-11-02 20:19 后端 `Segmentation fault`（exit 139）崩溃。

## 原因
Windows 上 SQLite C 扩展在**多线程并发写**时崩溃：
- 主线程：处理聊天/插件 API
- 后台线程：autopilot 每 60 秒 tick
- 两者同时写不同的 .db 文件，WAL 模式下偶发崩溃

## 修复（三层）

### 1. SQLite 加固（所有库）
```python
sqlite3.connect(..., timeout=30.0, isolation_level=None, check_same_thread=False)
PRAGMA journal_mode=WAL
PRAGMA busy_timeout=30000
PRAGMA synchronous=NORMAL
```
覆盖：`core/db.py`、`core/memory_engine.py`、`core/autopilot.py`、`core/procedural.py`

### 2. 守护进程（run_daemon.py）
崩了 3 秒内自动重启，记录崩溃次数，超 50 次放弃。

启动方式：
```bat
.venv\Scripts\python.exe run_daemon.py
```
日志：`logs/daemon.log`

### 3. 并发压力测试
8 线程 × 20 次混合读写（db/memory/procedural/autopilot）= 160 次，**零错误**。

## 以后遇到崩溃怎么查

1. 看 `logs/daemon.log` 有没有重启记录
2. 看 `logs/pccore.log` 最后几行
3. 如果是 exit 139 / Segmentation fault → 还是 SQLite 并发，检查是不是又新增了没加 WAL 的库
4. 如果是 exit 1 + Python traceback → 普通代码错误，看 traceback

## 数据安全
段错误不会丢数据（WAL 有事务保证）。实测崩溃后 10 个会话全部完好。
