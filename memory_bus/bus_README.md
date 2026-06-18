# Hermes 记忆总线 (Memory Bus)

## 概览

记忆总线是 Hermes 记忆系统的统一入口。它把 10 个松散的记忆子系统整合为一个可查询、可同步、可管理的整体——**不改任何现有代码**。

```
用户/LLM
   │
   ▼
┌─────────────────────────────┐
│     MemoryBus (memory_bus)  │  统一入口
│   ├─ write()  → 自动分发    │
│   ├─ search() → 聚合查询    │
│   ├─ recall() → 快速回忆    │
│   ├─ sync()   → 跨系统同步  │
│   └─ status() → 健康状态    │
└────┬────┬────┬────┬────┬───┘
     │    │    │    │    │
     ▼    ▼    ▼    ▼    ▼
   L1   Mem  沙漏  织线  Session
 AAAK  工具  语义  图谱  全文搜索
```

### 已整合的子系统

| # | 系统 | 层 | 方式 |
|---|------|---|------|
| 1 | L0/L1 AAAK 分层 | L1 | 文件读写 (`/root/.hermes/memory_layers/l1_facts.aaak`) |
| 2 | Hermes 原生 memory 工具 | Memory | 文件追加 (`/root/.hermes/memories/MEMORY.md` + `USER.md`) |
| 3 | NexSandglass 沙漏 | Sandglass | `import sandglass_vault` |
| 4 | NexSandglass 语义搜索 | Sematic | `import sandglass_think.search_semantic` |
| 5 | NexSandglass 织线知识图谱 | WeaveThread | `import weavethread` |
| 6 | NexSandglass 偏移率 | Offset | `import sandglass_think.comprehensive_offset` |
| 7 | NexSandglass ChromaDB | Chroma | `import sandglass_chroma` |
| 8 | Session Search (FTS5) | Session | 直接 SQLite (`hermes_sessions.db`) |
| 9 | 梦境系统 | Dream | 文本模式检测 |
| 10 | L1 引用追踪 | Tracker | JSON 状态文件 |

## 文件位置

```
/root/.hermes/
├── scripts/
│   ├── memory_bus.py          # 主模块（可 CLI 调用）
│   └── test_memory_bus.py     # 测试脚本
├── memory_bus/
│   └── .l1_reference_tracker.json  # L1 引用跟踪器（自动生成）
└── memory_bus_config.yaml     # 配置文件
```

## 快速开始

```python
from memory_bus import MemoryBus

bus = MemoryBus()

# 聚合搜索所有子系统
results = bus.search("服务器配置")
for r in results:
    print(f"[{r['source']}] {r['text'][:100]}")

# 快速回忆
print(bus.recall("环境"))

# 触发跨系统同步
bus.sync()

# 查看各层健康状态
status = bus.status()
for layer, info in status.items():
    print(f"{layer}: {'✅' if info['available'] else '❌'} count={info.get('count', '?')}")

# 写入一条重要信息（自动分发到沙漏+memory+织线）
bus.write({
    "text": "用户偏好：使用 FastAPI 开发",
    "sender": "user",
    "importance": 0.8,
    "category": "behavior",
})
```

## CLI 用法

```bash
# 查看各层健康状态
python3 /root/.hermes/scripts/memory_bus.py status

# 聚合搜索
python3 /root/.hermes/scripts/memory_bus.py search "服务器"

# 快速回忆
python3 /root/.hermes/scripts/memory_bus.py recall "环境"

# 触发同步
python3 /root/.hermes/scripts/memory_bus.py sync

# 写入数据
python3 /root/.hermes/scripts/memory_bus.py write "测试写入" --importance 0.7

# 指定搜索数量
python3 /root/.hermes/scripts/memory_bus.py search "DeepSeek" --limit 5
```

## 运行测试

```bash
python3 /root/.hermes/scripts/test_memory_bus.py
```

### 选择单个测试

```bash
python3 /root/.hermes/scripts/test_memory_bus.py test_01_status
python3 /root/.hermes/scripts/test_memory_bus.py --list   # 列出所有测试
```

## 核心 API

### `MemoryBus()`

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `search()` | `query: str, limit: int` | `List[Dict]` | 聚合查询，去重排序 |
| `recall()` | `topic: str, limit: int` | `str` | 快速回忆（可直接注入 prompt） |
| `write()` | `data: Dict` | `Dict` | 统一写入，自动分发 |
| `sync()` | — | `Dict` | 执行所有同步规则 |
| `status()` | — | `Dict` | 各层健康状态 |
| `reload_config()` | — | — | 重载配置 |

### `write()` data 格式

```python
{
    "text": "消息内容",
    "sender": "user | agent | system",    # 默认 "user"
    "source": "weavethread | dream | offset_detect | manual",  # 默认 "manual"
    "importance": 0.0-1.0,               # 默认 0.5，>=0.6 写入 memory 工具
    "category": "fact | pattern | behavior",  # 默认 "general"
    "tags": ["tag1", "tag2"],             # 可选标签
}
```

### `search()` 返回格式

```python
[
    {
        "source": "l1 | memory_tool | sandglass | sandglass_semantic | session",
        "text": "匹配文本片段",
        "relevance": 5.0,        # 权重分
        "layer": "L1-AAAK | memory-MEMORY | sandglass | ...",
        "line": 42,              # 仅 sandglass 有
        "ts": "2026-06-17 ...",  # 仅 sandglass 有
        "id": 123,               # 仅 session 有
    },
]
```

## 同步规则详解

### 1. 织线→L1 (`_sync_weave_to_l1`)
从织线知识图谱中抽取事实类三元组（使用、安装、依赖、偏好等），判断重要性后写入 L1 AAAK 文件。
- 去重：不写入重复 AA AK 行
- 修剪：超过 `l1_max_lines`（默认15）时保护核心行（ENV/SRV/PE/GH），移除最旧自由行
- 忽略：对比、放弃、反感等临时关系不提升

### 2. 梦境→memory (`_sync_dream_to_memory`)
扫描沙漏最新记录，检测包含兴趣关键词（喜欢、模式、习惯等）的行，高置信度写入 USER.md。
- 记录扫描位置避免重复
- 多关键词出现时自动提升置信度

### 3. 偏移率→memory (`_sync_offset_to_memory`)
检测 NexSandglass 偏移率，当绝对值超过 `spike_threshold`（默认30%）时写入一条低优先级 USER.md 条目。
- 自带 5 分钟防重复检查
- 方向标签：省钱/愿投/放弃

### 4. L1 衰减 (`_sync_l1_decay`)
跟踪 L1 事实的引用情况，超过 `max_unreferenced_days`（默认30天）未引用时标记 `[DECAY]` 前缀。
- 核心行（ENV/SRV/PE/GH/MODEL/MEM）不衰减
- 引用重新激活：搜索命中后自动清除衰减标记
- 60天未引用可自动清理

## 配置说明

配置文件 `/root/.hermes/memory_bus_config.yaml`：

```yaml
bus:
  log_level: INFO
  enable_all_sync: true
  sync_interval_seconds: 30

weave_to_l1:
  enabled: true
  importance_threshold: 0.6
  factual_relations: [使用, 装了, 安装了, 依赖, 偏好, 替换为, 迁移, 安装]
  ephemeral_relations: [对比, 放弃, 反感]
  repeat_threshold: 3
  l1_max_lines: 15

dream_to_memory:
  enabled: true
  min_confidence: 0.5
  interest_keywords: [喜欢, 倾向, 模式, 兴趣, 新发现, 习惯, 重复]

offset_to_memory:
  enabled: true
  spike_threshold: 30
  stable_threshold: 10
  check_interval: 300

l1_decay:
  enabled: true
  max_unreferenced_days: 30
  decay_prefix: "[DECAY] "
  cleanup_days: 60

query:
  weights:
    l1_weight: 5.0
    memory_weight: 3.0
    sandglass_weight: 2.0
    session_weight: 1.0
  max_results: 20
  max_per_layer: 15
```

## 技术原则

1. **零侵入** — 不对 `config.yaml`、Hermes 核心、子系统源码做任何修改
2. **纯只读包装** — 通过 `import` + 函数调用而非子类化或 monkey-patch
3. **最小依赖** — 只用 `pyyaml`（读取 yaml 配置）+ Python 标准库
4. **错误隔离** — 每个子系统独立 try/except，一个失败不影响其他
5. **引用安全** — NexSandglass 路径通过 `sys.path` 动态添加，不影响已有 import 顺序

## 注意

- 首次导入 `memory_bus` 会自动添加 NexSandglass 到 `sys.path`
- 同步间隔默认 30 秒（`sync_interval_seconds`），防止频繁写入
- Session Search 直接读 SQLite FTS5，性能受索引影响
- `sync()` 返回 `{"synced": [...], "errors": [...], "ok": bool}`
