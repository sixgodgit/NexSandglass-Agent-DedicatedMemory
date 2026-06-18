# Merged Memory System — hermes-memory-system → NexSandglass

## 合并说明

2026年6月18日：已将 `hermes-memory-system` 仓库的关键内容合并到 NexSandglass-Agent-DedicatedMemory 仓库。

### 源仓库: hermes-memory-system

该仓库提供了 Hermes Agent 记忆系统的增强组件，在 NexSandglass 现有架构的基础上添加了：

1. **Memory Bus (记忆总线)** — 统一写入/查询/同步入口，整合 L1-AAAK、Hermes memory 工具、NexSandglass 沙漏、织线知识图谱、Session 全文搜索、梦境系统和偏移率
2. **跨系统同步规则** — 织线→L1、梦境→memory、偏移率→memory、L1 衰减标记
3. **MCP 接口** — 通过 JSON-RPC 暴露 bus.search/bus.recall/bus.status/bus.sync 四个工具
4. **搜索 Fallback** — Tavily → Exa 自动降级搜索
5. **L1 引用追踪** — L1 事实的被引用次数和衰减管理

### 合并了什么

| 源文件 | 合并位置 | 说明 |
|--------|----------|------|
| `memory_bus.py` (1122行) | `memory_bus/memory_bus.py` | MemoryBus 核心类 — write/search/recall/sync/status |
| `memory_bus_mcp.py` (289行) | `memory_bus/memory_bus_mcp.py` | MCP 协议封装，暴露出 4 个 MCP 工具 |
| `memory_bus_config.yaml` | `memory_bus/memory_bus_config.yaml` | 配置模板（同步规则、权重、阈值） |
| `test_memory_bus.py` (463行) | `memory_bus/test_memory_bus.py` | 13 个测试用例，覆盖率 > 85% |
| `bus_README.md` | `memory_bus/bus_README.md` | 详细使用文档和 API 说明 |
| `tavily_fallback.py` | `tavily_fallback.py` | 搜索自动降级（Tavily→Exa） |

### 已存在的共享模块（未重复合并）

以下文件在两个仓库中内容一致，NexSandglass 中已有：

- `memory_layers/` — L0+L1 分层（已存在，未改动）
- `compress_memory.py` — 记忆压缩（已存在，未改动）
- `switch_memory_layers.sh` — 分层切换（已存在，未改动）
- `weavethread.py` — 织线知识图谱（已存在，未改动）
- `sandglass_chroma.py` — ChromaDB 后端（已存在，未改动）
- `migrate_to_chromadb.py` — 迁移脚本（已存在，未改动）
- `sandglass_mcp.py` — 沙漏 MCP 服务器（已存在，未改动）

### 关键架构

```
hermes-memory-system/                          NexSandglass/
  memory_bus.py          ─────────────────────  memory_bus/memory_bus.py
  memory_bus_mcp.py      ─────────────────────  memory_bus/memory_bus_mcp.py
  memory_bus_config.yaml ─────────────────────  memory_bus/memory_bus_config.yaml
  test_memory_bus.py     ─────────────────────  memory_bus/test_memory_bus.py
  bus_README.md          ─────────────────────  memory_bus/bus_README.md
  tavily_fallback.py     ─────────────────────  tavily_fallback.py
  nexsandglass-upgrade/                          (已在 NexSandglass 中，未重复合并)
    ├── weavethread.py               → already in root
    ├── sandglass_chroma.py          → already in root
    ├── sandglass_mcp.py             → already in root
    ├── migrate_to_chromadb.py       → already in root
    └── compress_memory.py           → already in root
  memory_layers/                                   (已在 NexSandglass 中，未重复合并)
    ├── l0_identity.md               → already in memory_layers/
    ├── l1_facts.aaak                → already in memory_layers/
    └── persona_combined.md          → already in memory_layers/
```

### Memory Bus 的依赖关系

```
MemoryBus (memory_bus/memory_bus.py)
  ├── sandglass_vault.search()        — 沙漏全文搜索
  ├── sandglass_think.search_semantic() — 语义搜索 (TF-IDF + ChromaDB)
  ├── sandglass_think.comprehensive_offset() — 偏移率
  ├── weavethread.wthread_query/Store  — 织线三元组
  ├── emotion_l3.entropy_ghost()      — 梦境分析（可选）
  └── hermes_sessions.db (SQLite)     — Session 搜索
```

### 源仓库归档

`hermes-memory-system` 仓库已完成归档。后续开发统一在 NexSandglass-Agent-DedicatedMemory 进行。

### 后续建议

1. 考虑将 `memory_bus/` 集成到 `memory_provider.py` 中，作为 NexSandglass 的默认注入层
2. 将 `tavily_fallback.py` 整合到 `search_router.py` 的四路并发搜索中
3. 改进 `memory_bus_config.yaml` 路径配置，使其与 `sandglass_paths.py` 统一
