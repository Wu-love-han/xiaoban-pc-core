# 事故记录：E 盘 data 目录损坏（2026-11-04 23:47）

## 发生了什么

23:47 重启后端时，所有数据库报：

```
sqlite3.OperationalError: disk I/O error
```

排查发现：

```
E:\WH\pc-core\data  →  GetFileSystemInfos() 抛 "The file or directory is corrupted and unreadable"
其他目录（docs/core/tools/logs/workspace/plugins/config）→ 全部正常
```

**只有 data 一个目录坏了**，E 盘其他目录都好。

## 磁盘状态

```
DriveLetter    : E
FileSystemType : exFAT
HealthStatus   : Warning        ← 警告
SizeRemaining  : 118 GB
```

exFAT 在异常断电/拔出时容易损坏目录索引。

## 数据救回来了

关键发现：**目录索引坏了，但文件本身完好**。

```powershell
# 目录列不出来
Get-ChildItem 'E:\WH\pc-core\data'  → 空

# 但直接访问已知文件能读到
Get-Item 'E:\WH\pc-core\data\memory.db'  → 49152 字节 ✓
```

紧急备份到 `D:\xiaoban-backup\data\`，验证全部完好：

| 文件 | 大小 | 表数 | 内容 |
|---|---|---|---|
| pccore.db | 729 KB | 7 | 12 会话 / 162 消息 |
| memory.db | 48 KB | 6 | 21 条长期记忆 / 21 条短期 |
| sync.db | 40 KB | 4 | 三端同步 |
| consent.db | 16 KB | 1 | 确认请求 |
| proactive.db | 16 KB | 2 | 主动消息 |

## 处理方式

**没能修复原目录**（rename 报 Access denied，被系统锁住）。

**改为把数据目录移到 D 盘**：

```python
# core/paths.py
DATA_DIR = Path(r"D:\xiaoban-data")
# 也支持环境变量覆盖：PCORE_DATA_DIR
```

然后从备份恢复，重启后一切正常。

## 遗留问题

**E 盘需要跑一次 chkdsk 修复**（要管理员权限）：

```cmd
chkdsk E: /f
```

修好后可以把数据目录改回 E 盘（或者就留在 D 盘，更稳）。

**E 盘 HealthStatus=Warning，建议尽快把重要数据迁走。** 这个盘可能还会坏。

## 教训

1. **exFAT 不适合放数据库**。SQLite 的 WAL 模式频繁写入，exFAT 没有日志，断电就坏。
2. **重要数据要有多份**。这次能救回来是因为文件本身完好，运气好。
3. **定期备份**。应该加个自动备份任务。

## 待办

- [ ] 加自动备份：每天把 data/*.db 复制到 D:\xiaoban-backup\daily\
- [ ] E 盘跑 chkdsk /f
- [ ] 考虑把整个项目迁到 NTFS 盘（C 或 D）
