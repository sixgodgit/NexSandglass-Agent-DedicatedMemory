#!/usr/bin/env python3
"""
Hermes 记忆总线 (Memory Bus) V1.0
=================================
统一入口，让所有记忆子系统互通。
纯只读包装——不修改任何现有子系统代码。

架构：
  bus.write(data)          → 自动分发到织线/沙漏/影子沙
  bus.sync()               → 跨系统同步（织线→L1, 梦境→memory, 偏移→memory, L1衰减）
  bus.search(keyword)      → 聚合 L1 + memory + sandglass + session，去重排序
  bus.recall(topic)        → 快速回忆（精简版 search）
  bus.status()             → 各层健康状态

用法：
  from memory_bus import MemoryBus
  bus = MemoryBus()
  bus.search("服务器配置")
  bus.sync()  # 触发跨系统同步
"""

import json
import logging
import os
import re
import sqlite3
import sys
import time
import yaml
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ── 日志 ──
logger = logging.getLogger("memory_bus")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("[MEMORY_BUS] %(levelname)s %(message)s"))
logger.addHandler(_handler)
logger.setLevel(logging.INFO)

# ── 路径 ──
_CONF_PATH = os.path.expanduser("~/.hermes/memory_bus_config.yaml")
_SCRIPTS_DIR = os.path.expanduser("~/.hermes/scripts")
_MEMORY_BUS_DIR = os.path.expanduser("~/.hermes/memory_bus")
_HERMES_DIR = os.path.expanduser("~/.hermes")
_NB = os.environ.get("NEXSANDBASE_HOME") or os.path.expanduser("~/.hermes/NexSandglass")

# ── NexSandglass 导入路径 ──
_NEX_SRC = os.path.join(_HERMES_DIR, "NexSandglass")
if _NEX_SRC not in sys.path:
    sys.path.insert(0, _NEX_SRC)

# ── Session search DB ──
_SESSION_DB = os.path.join(_HERMES_DIR, "sessions", "hermes_sessions.db")


# ═══════════════════════════════════════════════
# 配置加载
# ═══════════════════════════════════════════════
def _load_config() -> dict:
    """加载 memory_bus_config.yaml"""
    default = {
        "bus": {"log_level": "INFO", "enable_all_sync": True, "sync_interval_seconds": 30},
        "weave_to_l1": {
            "enabled": True, "importance_threshold": 0.6, "l1_path": os.path.join(_HERMES_DIR, "memory_layers", "l1_facts.aaak"),
            "factual_relations": ["使用", "装了", "安装了", "依赖", "偏好", "替换为", "迁移", "安装"],
            "ephemeral_relations": ["对比", "放弃", "反感"],
            "repeat_threshold": 3, "l1_max_lines": 15,
        },
        "dream_to_memory": {
            "enabled": True,
            "min_confidence": 0.5,
            "interest_keywords": ["喜欢", "倾向", "模式", "兴趣", "新发现", "习惯", "重复"],
        },
        "offset_to_memory": {
            "enabled": True, "spike_threshold": 30, "stable_threshold": 10, "check_interval": 300,
        },
        "l1_decay": {
            "enabled": True, "max_unreferenced_days": 30, "decay_prefix": "[DECAY] ", "cleanup_days": 60,
        },
        "query": {
            "weights": {"l1_weight": 5.0, "memory_weight": 3.0, "sandglass_weight": 2.0, "session_weight": 1.0},
            "max_results": 20, "max_per_layer": 15,
        },
    }
    if os.path.exists(_CONF_PATH):
        try:
            with open(_CONF_PATH, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            # 深层合并
            for section in default:
                if section in loaded:
                    default[section].update(loaded[section])
        except Exception as e:
            logger.warning(f"配置加载失败，使用默认: {e}")
    return default


# ═══════════════════════════════════════════════
# L1 AAAK 层 读写（只通过文件操作，不改压缩脚本）
# ═══════════════════════════════════════════════
def _read_l1(path: str) -> List[str]:
    """读取 L1 AAAK 文件，返回非空非注释行"""
    if not os.path.exists(path):
        return []
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                lines.append(stripped)
    return lines


def _write_l1(path: str, lines: List[str]):
    """写回 L1 AAAK 文件，保留注释头"""
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# L1 — Key Facts (AAAK format)\n")
    # 读原有内容，保留注释头
    header = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("#"):
                    header.append(line)
                else:
                    break
    except Exception:
        header = ["# L1 — Key Facts (AAAK format)\n"]
    with open(path, "w", encoding="utf-8") as f:
        for h in header:
            f.write(h)
        for line in lines:
            f.write(line + "\n")


# ═══════════════════════════════════════════════
# Memory 工具层（写入 Hermes 原生 memory 文件 MEMORY.md / USER.md）
# ═══════════════════════════════════════════════
def _write_memory(content: str, target: str = "both"):
    """
    写入 Hermes 原生 memory。
    target: 'both' → 同时写入 MEMORY.md 和 USER.md
            'memory' → 仅 MEMORY.md
            'user' → 仅 USER.md
    追加内容，按 § 分隔。不破坏已有条目。
    """
    _mem_dir = os.path.join(_HERMES_DIR, "memories")
    os.makedirs(_mem_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d")

    if target in ("both", "memory"):
        path = os.path.join(_mem_dir, "MEMORY.md")
        _append_memory_file(path, content, timestamp)

    if target in ("both", "user"):
        path = os.path.join(_mem_dir, "USER.md")
        _append_memory_file(path, content, timestamp)


def _append_memory_file(path: str, content: str, timestamp: str):
    """追加内容到 memory 文件，带时间戳"""
    line = f"{content} [bus:{timestamp}]"
    # 去重：如果最后N条有相同内容，跳过
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read()
        # 检查最后20行是否有相同内容
        lines = existing.split("\n")
        recent = [l for l in lines[-20:] if l.strip()]
        for r in reversed(recent):
            if r.strip() == line.strip() or content in r:
                return  # 已存在
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{line}\n§\n")


# ═══════════════════════════════════════════════
# 沙漏层接口（只读调用，不改源码）
# ═══════════════════════════════════════════════
def _sandglass_search(query: str, limit: int = 10) -> List[Dict]:
    """通过沙漏搜索接口查询"""
    results = []
    try:
        if "sandglass_vault" in sys.modules:
            import importlib
            importlib.reload(sys.modules["sandglass_vault"])
        from sandglass_vault import search
        raw = search(query, limit=limit)
        for ln, ts, text in raw:
            results.append({"source": "sandglass", "line": ln, "ts": ts, "text": text[:300], "relevance": 1.0})
    except Exception as e:
        logger.warning(f"sandglass_search 失败: {e}")
    return results


def _sandglass_semantic_search(query: str, limit: int = 5) -> List[Dict]:
    """沙漏语义搜索（TF-IDF / ChromaDB）"""
    results = []
    try:
        from sandglass_think import search_semantic
        raw = search_semantic(query, limit=limit, backend="tfidf")
        for ln, ts, text in raw:
            results.append({"source": "sandglass_semantic", "line": ln, "ts": ts, "text": text[:300], "relevance": 0.9})
    except Exception as e:
        logger.warning(f"sandglass_semantic 失败: {e}")
    # ChromaDB 兜底
    if not results:
        try:
            from sandglass_chroma import search as chroma_search
            raw = chroma_search(query, limit=limit)
            for ln, ts, text in raw:
                results.append({"source": "sandglass_chroma", "line": ln, "ts": ts, "text": text[:300], "relevance": 0.8})
        except Exception as e:
            logger.warning(f"chroma_search 失败: {e}")
    return results


def _sandglass_offset() -> Dict:
    """获取当前偏移率"""
    try:
        from sandglass_think import comprehensive_offset
        return comprehensive_offset()
    except Exception as e:
        logger.warning(f"偏移率查询失败: {e}")
        return {"offset": 0, "direction": "unknown"}

# ═══════════════════════════════════════════════
# 织线程（weavethread）接口
# ═══════════════════════════════════════════════
def _wthread_query(entity: str = None, relation: str = None, limit: int = 20) -> List[Dict]:
    """查询织线三元组"""
    try:
        from weavethread import wthread_query
        return wthread_query(entity=entity, relation=relation, limit=limit)
    except Exception as e:
        logger.warning(f"wthread_query 失败: {e}")
        return []


def _wthread_stats() -> Dict:
    """织线统计"""
    try:
        from weavethread import wthread_stats
        return wthread_stats()
    except Exception as e:
        logger.warning(f"wthread_stats 失败: {e}")
        return {"total_triples": 0, "relations": []}


# ═══════════════════════════════════════════════
# Session Search 接口（直接读 SQLite FTS5）
# ═══════════════════════════════════════════════
def _session_search(query: str, limit: int = 10) -> List[Dict]:
    """通过直接查询 hermes_sessions.db 来搜索历史会话"""
    results = []
    if not os.path.exists(_SESSION_DB):
        return results
    try:
        conn = sqlite3.connect(_SESSION_DB, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        # 检查 FTS5 虚拟表是否存在
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%fts%'"
        )
        fts_tables = [r[0] for r in cursor.fetchall()]
        if fts_tables:
            fts_name = fts_tables[0]
            # FTS5 搜索
            cursor = conn.execute(
                f"SELECT rowid, rank FROM {fts_name} WHERE {fts_name} MATCH ? ORDER BY rank LIMIT ?",
                (query.replace(" ", " OR "), limit * 2)
            )
            matched_ids = [r[0] for r in cursor.fetchall()]
            if matched_ids:
                placeholders = ",".join("?" * len(matched_ids))
                cursor = conn.execute(
                    f"SELECT id, content FROM messages WHERE id IN ({placeholders}) LIMIT ?",
                    matched_ids + [limit]
                )
                for row in cursor.fetchall():
                    results.append({
                        "source": "session",
                        "id": row[0],
                        "text": str(row[1])[:300],
                        "relevance": 0.7,
                    })
        conn.close()
    except Exception as e:
        logger.warning(f"session_search (SQLite) 失败: {e}")
    return results


# ═══════════════════════════════════════════════
# 梦境系统接口
# ═══════════════════════════════════════════════
def _dream_check() -> List[Dict]:
    """
    检查梦境输出——调用真实梦境子系统分析（emotion_l3.entropy_ghost / weavethread 洞察）
    返回新发现的模式和兴趣
    """
    patterns = []
    try:
        cfg = _load_config()
        dream_cfg = cfg.get("dream_to_memory", {})
        keywords = dream_cfg.get("interest_keywords", ["喜欢", "倾向", "模式", "兴趣", "新发现", "习惯", "重复"])
        min_conf = dream_cfg.get("min_confidence", 0.5)

        # 1. 调用真实梦境子系统——幽灵决策分析
        try:
            from emotion_l3 import entropy_ghost
            ghost = entropy_ghost("今天有什么新发现的模式或兴趣？")
            if ghost and isinstance(ghost, dict):
                inference = ghost.get("inference", "")
                similar = ghost.get("similar_patterns", [])
                if inference:
                    patterns.append({
                        "source": "entropy_ghost",
                        "text": inference[:200],
                        "keywords": [kw for kw in keywords if kw in inference],
                        "confidence": 0.7,
                    })
                for sp in similar:
                    text = sp.get("choice", "") or sp.get("tags", "")
                    if text:
                        patterns.append({
                            "source": "decision_particle",
                            "text": str(text)[:200],
                            "keywords": [kw for kw in keywords if kw in str(text)],
                            "confidence": 0.6,
                        })
        except Exception:
            pass  # 梦境子系统不可用时走 fallback

        # 2. 调用 weave_l3 洞察（如果可用）
        if not patterns:
            try:
                from weave_l3 import weave_insight
                insight = weave_insight("兴趣模式")
                synthesis = insight.get("synthesis", "")
                if synthesis and any(kw in synthesis for kw in keywords):
                    patterns.append({
                        "source": "weave_insight",
                        "text": synthesis[:200],
                        "keywords": [kw for kw in keywords if kw in synthesis],
                        "confidence": 0.6,
                    })
            except Exception:
                pass

        # 3. Fallback：从 sandglass.txt 扫描最近行中的模式
        if not patterns:
            sand_path = os.path.join(_NB, "sandglass.txt")
            if os.path.exists(sand_path):
                with open(sand_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                recent_lines = lines[-50:]

                state_file = os.path.join(_MEMORY_BUS_DIR, ".dream_last_scan")
                last_scanned = 0
                if os.path.exists(state_file):
                    try:
                        with open(state_file, "r") as f:
                            last_scanned = int(f.read().strip())
                    except Exception:
                        pass

                total = len(lines)
                new_lines = recent_lines[max(0, last_scanned - (total - len(recent_lines))):]

                for i, line in enumerate(new_lines):
                    if "|" in line:
                        parts = line.split("|", 2)
                        if len(parts) >= 3:
                            text = parts[2].strip().lower()
                            found_kw = [kw for kw in keywords if kw in text]
                            if found_kw and text not in [p.get("text", "") for p in patterns]:
                                patterns.append({
                                    "source_line": total - len(recent_lines) + i,
                                    "text": parts[2].strip()[:200],
                                    "keywords": found_kw,
                                    "confidence": min(1.0, 0.5 + 0.1 * len(found_kw)),
                                })

                # 更新扫描位置
                try:
                    with open(state_file, "w") as f:
                        f.write(str(total))
                except Exception:
                    pass

    except Exception as e:
        logger.warning(f"梦境检测失败: {e}")

    return patterns


# ═══════════════════════════════════════════════
# L1 引用追踪（统计 L1 事实在对话中的出现次数）
# ═══════════════════════════════════════════════
def _track_l1_references(l1_lines: List[str]) -> Dict[str, Dict]:
    """
    追踪 L1 事实的引用情况。
    返回 {fact_text: {"last_seen": timestamp, "count": N, "decayed": bool}}
    """
    track_file = os.path.join(_MEMORY_BUS_DIR, ".l1_reference_tracker.json")
    tracker = {}
    if os.path.exists(track_file):
        try:
            with open(track_file, "r") as f:
                tracker = json.load(f)
        except Exception:
            tracker = {}

    now = datetime.now(timezone.utc).isoformat()

    # 确保所有 L1 行在跟踪器中
    for line in l1_lines:
        if line not in tracker:
            tracker[line] = {"last_seen": now, "count": 0, "decayed": False}

    # 移除 L1 中已经不存在的行
    existing_keys = set(l1_lines)
    tracker = {k: v for k, v in tracker.items() if k in existing_keys}

    # 保存
    try:
        os.makedirs(_MEMORY_BUS_DIR, exist_ok=True)
        with open(track_file, "w") as f:
            json.dump(tracker, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return tracker


def _mark_l1_referenced(line: str):
    """标记 L1 事实被引用"""
    track_file = os.path.join(_MEMORY_BUS_DIR, ".l1_reference_tracker.json")
    if not os.path.exists(track_file):
        return
    try:
        with open(track_file, "r") as f:
            tracker = json.load(f)
        if line in tracker:
            tracker[line]["last_seen"] = datetime.now(timezone.utc).isoformat()
            tracker[line]["count"] = tracker[line].get("count", 0) + 1
            if tracker[line].get("decayed"):
                tracker[line]["decayed"] = False  # 重新激活
        with open(track_file, "w") as f:
            json.dump(tracker, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ═══════════════════════════════════════════════
# MemoryBus 核心类
# ═══════════════════════════════════════════════
class MemoryBus:
    """
    Hermes 统一记忆总线。

    核心原则：
    - 单一入口：所有写入/查询经过这里
    - 不破坏现有系统：只读调用，不改原代码
    - 零侵入性：纯 Python，最小依赖
    """

    def __init__(self, config_path: str = None):
        self.config_path = config_path or _CONF_PATH
        self.config = _load_config()
        self._last_offset = {"offset": 0, "direction": "unknown"}
        self._last_offset_check = 0
        self._last_sync_time = 0
        self._setup_logging()

    def _setup_logging(self):
        level_str = self.config.get("bus", {}).get("log_level", "INFO")
        level = getattr(logging, level_str.upper(), logging.INFO)
        logger.setLevel(level)

    # ── 写入入口 ──

    def write(self, data: Dict) -> Dict:
        """
        统一写入入口。
        data 格式:
          {
            "text": "消息文本",
            "sender": "user|agent|system",
            "source": "weavethread|dream|offset_detect|manual",
            "importance": 0.0-1.0,       # 可选，重要性
            "category": "fact|pattern|behavior",  # 可选
            "tags": ["tag1", "tag2"],     # 可选
          }
        返回 {written_to: [list of subsystems], errors: [list]}
        """
        text = data.get("text", "")
        sender = data.get("sender", "user")
        importance = data.get("importance", 0.5)
        source = data.get("source", "manual")
        category = data.get("category", "general")
        tags = data.get("tags", [])

        written_to = []
        errors = []

        # 1. 始终落沙（如果沙漏可用）
        try:
            from sandglass_log import log_message
            log_message(text, sender=sender if sender != "system" else "bus")
            written_to.append("sandglass")
        except Exception as e:
            errors.append(f"sandglass: {e}")

        # 2. 高重要性 → 写入 memory 工具
        if importance >= 0.6:
            try:
                if category == "pattern":
                    _write_memory(f"🔄 [模式] {text}", target="user")
                elif category == "behavior":
                    _write_memory(f"📌 [行为] {text}", target="user")
                else:
                    _write_memory(text, target="both")
                written_to.append("memory_tool")
            except Exception as e:
                errors.append(f"memory_tool: {e}")

        # 3. 织线三元组（如果文本是结构化三元组）
        if source == "weavethread" or importance >= 0.7:
            try:
                from weavethread import wthread_store, wthread_add
                if ":" in text and "→" in text:
                    # 结构化三元组: subject:relation→object
                    parts = text.split(":")
                    if len(parts) >= 2:
                        subj = parts[0].strip()
                        rest = parts[1].strip()
                        if "→" in rest:
                            rel, obj = rest.split("→", 1)
                            wthread_add(subj.strip(), rel.strip(), obj.strip())
                            written_to.append("weavethread")
                else:
                    # 普通文本 → 自动提取
                    wthread_store(text, subject=sender)
                    written_to.append("weavethread")
            except Exception as e:
                errors.append(f"weavethread: {e}")

        return {"written_to": written_to, "errors": errors, "ok": len(errors) == 0}

    # ── 查询入口 ──

    def search(self, query: str, limit: int = None, compact: bool = False) -> List[Dict]:
        """
        统一查询入口。
        聚合各层结果 → 去重 → 按相关性排序。
        compact=True 返回纯文本行列表 ["source: 摘要", ...]（<200 tokens）。
        返回 [{source, text, relevance, ...}, ...]
        """
        if not query or not query.strip():
            return []

        if limit is None:
            limit = self.config.get("query", {}).get("max_results", 20)
        weights = self.config.get("query", {}).get("weights", {})
        max_per_layer = self.config.get("query", {}).get("max_per_layer", 15)

        all_results = []

        # ── Token 效率跟踪（用于 2d 动态权重调整）──
        _token_efficiency = {}  # layer -> (char_len, weight)

        def _track_efficiency(layer: str, char_len: int, base_weight: float):
            if layer not in _token_efficiency:
                _token_efficiency[layer] = {"total_chars": 0, "count": 0, "weight": base_weight}
            _token_efficiency[layer]["total_chars"] += char_len
            _token_efficiency[layer]["count"] += 1

        # 1. L1 层搜索
        l1_path = self.config.get("weave_to_l1", {}).get(
            "l1_path",
            os.path.join(_HERMES_DIR, "memory_layers", "l1_facts.aaak")
        )
        l1_lines = _read_l1(l1_path)
        for line in l1_lines:
            if query.lower() in line.lower():
                text = line[:300]
                weight = weights.get("l1_weight", 5.0)
                all_results.append({
                    "source": "l1",
                    "text": text,
                    "relevance": weight,
                    "layer": "L1-AAAK",
                })
                _track_efficiency("L1-AAAK", len(text), weight)
                _mark_l1_referenced(line)

        # 2. Memory 工具层搜索（搜索 MEMORY.md 和 USER.md）
        for fname in ["MEMORY.md", "USER.md"]:
            path = os.path.join(_HERMES_DIR, "memories", fname)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                sections = content.split("§")
                for sec in sections[:max_per_layer]:
                    sec = sec.strip()
                    if sec and query.lower() in sec.lower():
                        text = sec[:300]
                        weight = weights.get("memory_weight", 3.0)
                        all_results.append({
                            "source": "memory_tool",
                            "text": text,
                            "relevance": weight,
                            "layer": f"memory-{fname.replace('.md', '')}",
                        })
                        _track_efficiency(f"memory-{fname.replace('.md', '')}", len(text), weight)

        # 3. 沙漏搜索
        sand_results = _sandglass_search(query, limit=max_per_layer)
        for r in sand_results:
            w = weights.get("sandglass_weight", 2.0) * r.get("relevance", 1.0)
            r["relevance"] = w
            r["layer"] = "sandglass"
            _track_efficiency("sandglass", len(r.get("text", "")), w)
            all_results.append(r)

        # 4. 沙漏语义搜索
        semantic_results = _sandglass_semantic_search(query, limit=max_per_layer // 2)
        for r in semantic_results:
            w = weights.get("sandglass_weight", 2.0) * r.get("relevance", 0.9)
            r["relevance"] = w
            r["layer"] = "sandglass_semantic"
            _track_efficiency("sandglass_semantic", len(r.get("text", "")), w)
            all_results.append(r)

        # 5. Session 搜索
        session_results = _session_search(query, limit=max_per_layer)
        for r in session_results:
            w = weights.get("session_weight", 1.0) * r.get("relevance", 0.7)
            r["relevance"] = w
            r["layer"] = "session"
            _track_efficiency("session", len(r.get("text", "")), w)
            all_results.append(r)

        # ═══════════════════════════════════
        # 2d. 动态权重调整：如果某层返回数据太多（>500字符平均），自动降权
        # ═══════════════════════════════════
        for r in all_results:
            layer = r.get("layer", "")
            info = _token_efficiency.get(layer)
            if info and info["count"] > 0:
                avg_chars = info["total_chars"] / info["count"]
                if avg_chars > 500:
                    # 数据太多，效率低 → 降权 30%
                    r["relevance"] = r.get("relevance", 0) * 0.7
                    r["_penalized"] = True
                elif avg_chars > 300:
                    # 中等 → 降权 15%
                    r["relevance"] = r.get("relevance", 0) * 0.85
                    r["_penalized"] = True

        # 去重：按文本内容去重
        seen_texts = set()
        deduped = []
        for r in sorted(all_results, key=lambda x: x.get("relevance", 0), reverse=True):
            text_key = r.get("text", "")[:100]
            if text_key not in seen_texts:
                seen_texts.add(text_key)
                deduped.append(r)

        final = deduped[:limit]

        # compact 模式：返回纯文本行
        if compact:
            lines = []
            for r in final:
                src = r.get("source", "?")
                text = r.get("text", "")[:100]
                lines.append(f"{src}: {text}")
            return lines

        return final

    def recall(self, topic: str, limit: int = 5, max_tokens: int = 0) -> str:
        """
        快速回忆——精简版 search，返回可直接注入 prompt 的文本。
        max_tokens: 如果 >0，自动截断到指定 token 数以内。
        """
        results = self.search(topic, limit=limit)
        if not results:
            return f"🔍 关于「{topic}」未找到记忆。"

        lines = [f"📚 关于「{topic}」的记忆 ({len(results)}条):"]
        for i, r in enumerate(results, 1):
            source = r.get("source", "?")
            text = r.get("text", "")[:150]
            lines.append(f"  [{source}] {text}")

        result = "\n".join(lines)

        # max_tokens 截断：保守估计 2 字符 / token（中英文混合）
        if max_tokens > 0:
            max_chars = max_tokens * 3
            if len(result) > max_chars:
                result = result[:max_chars] + "...[截断]"

        return result

    # ── 同步入口 ──

    def sync(self) -> Dict:
        """
        跨系统同步——执行所有活跃的同步规则。
        返回 {synced: [list of rules triggered], errors: [...]}
        """
        synced = []
        errors = []

        # 防止频繁同步
        now = time.time()
        interval = self.config.get("bus", {}).get("sync_interval_seconds", 30)
        if now - self._last_sync_time < interval:
            return {"synced": [], "errors": [], "skipped": "too_frequent"}
        self._last_sync_time = now

        # 1. 织线→L1 同步
        if self.config.get("weave_to_l1", {}).get("enabled", True):
            try:
                result = self._sync_weave_to_l1()
                if result.get("updated"):
                    synced.append("weave_to_l1")
                if result.get("errors"):
                    errors.extend(result["errors"])
            except Exception as e:
                errors.append(f"weave_to_l1: {e}")

        # 2. 梦境→memory 同步
        if self.config.get("dream_to_memory", {}).get("enabled", True):
            try:
                result = self._sync_dream_to_memory()
                if result.get("written"):
                    synced.append("dream_to_memory")
            except Exception as e:
                errors.append(f"dream_to_memory: {e}")

        # 3. 偏移率→memory 同步
        if self.config.get("offset_to_memory", {}).get("enabled", True):
            try:
                result = self._sync_offset_to_memory()
                if result.get("triggered"):
                    synced.append("offset_to_memory")
            except Exception as e:
                errors.append(f"offset_to_memory: {e}")

        # 4. L1 衰减标记
        if self.config.get("l1_decay", {}).get("enabled", True):
            try:
                result = self._sync_l1_decay()
                if result.get("decayed"):
                    synced.append("l1_decay")
            except Exception as e:
                errors.append(f"l1_decay: {e}")

        return {"synced": synced, "errors": errors, "ok": len(errors) == 0}

    def _sync_weave_to_l1(self) -> Dict:
        """织线新三元组 → 判断重要性 → 自动更新 L1 AAAK 事实"""
        config = self.config.get("weave_to_l1", {})
        threshold = config.get("importance_threshold", 0.6)
        factual_rels = config.get("factual_relations", [])
        l1_path = config.get("l1_path",
                             os.path.join(_HERMES_DIR, "memory_layers", "l1_facts.aaak"))
        l1_max = config.get("l1_max_lines", 15)

        # 查询重要关系类型的三元组
        triples = []
        for rel in factual_rels:
            found = _wthread_query(relation=rel, limit=5)
            triples.extend(found)

        if not triples:
            return {"updated": False}

        # 读取当前 L1
        l1_lines = _read_l1(l1_path)
        updated = False

        for t in triples:
            subj = t.get("subject", "")
            obj = t.get("object", "")
            rel = t.get("relation", "")
            if not subj or not obj:
                continue

            # 用 importance_threshold 过滤重要性
            importance = t.get("confidence", 0) or t.get("importance", 0)
            if importance < threshold:
                continue

            # 构建 AAAK 行
            fact = f"{subj}: {rel} {obj}"

            # 去重
            if any(fact in line for line in l1_lines):
                continue

            # 检查重复度（类似事实已存在则跳过）
            similar = False
            for line in l1_lines:
                if subj in line and rel in line:
                    similar = True
                    break
            if similar:
                continue

            # 追加到 L1
            l1_lines.append(fact)
            updated = True

        # 修剪 L1（超过限制则移除最旧的非 ENV/SRV/PE 行）
        if len(l1_lines) > l1_max:
            # 保护核心行（ENV, SRV, PE, GH 开头）
            protected = [l for l in l1_lines if l.startswith(('ENV:', 'SRV:', 'PE:', 'GH:', 'MODEL:', 'MEM:'))]
            removable = [l for l in l1_lines if l not in protected]
            overflow = len(l1_lines) - l1_max
            if overflow > 0 and removable:
                # 删除最旧的 overflow 条（保留最新的）
                l1_lines = protected + removable[overflow:]

        if updated:
            _write_l1(l1_path, l1_lines)
            logger.info(f"织线→L1: 新增 {len(triples)} 三元组到 L1 ({l1_path})")

        return {"updated": updated, "l1_lines": l1_lines, "triples_found": len(triples)}

    def _sync_dream_to_memory(self) -> Dict:
        """梦境发现新兴趣/模式 → 自动写入 memory 工具"""
        patterns = _dream_check()
        if not patterns:
            return {"written": False}

        config = self.config.get("dream_to_memory", {})
        min_conf = config.get("min_confidence", 0.5)

        written = 0
        for p in patterns:
            if p.get("confidence", 0) >= min_conf:
                text = p.get("text", "")
                kw = p.get("keywords", [])
                entry = f"🔄 [{', '.join(kw)}] {text}"
                _write_memory(entry, target="user")
                written += 1

        if written:
            logger.info(f"梦境→memory: 写入 {written} 条新模式")

        return {"written": written, "patterns": patterns}

    def _sync_offset_to_memory(self) -> Dict:
        """偏移率突变(>30%) → 写一条低优先级 memory"""
        now = time.time()
        check_interval = self.config.get("offset_to_memory", {}).get("check_interval", 300)

        if now - self._last_offset_check < check_interval:
            return {"triggered": False, "reason": "too_soon"}
        self._last_offset_check = now

        current = _sandglass_offset()
        offset = abs(current.get("offset", 0))
        direction = current.get("direction", "unknown")
        spike_threshold = self.config.get("offset_to_memory", {}).get("spike_threshold", 30)

        triggered = False
        if offset >= spike_threshold:
            # 偏移率突变
            dir_label = {"frugal": "省钱", "spend": "愿投", "drift": "放弃"}.get(direction, direction)
            entry = f"📊 [偏移] {dir_label}倾向偏移 {current.get('offset', 0):+d}%"
            _write_memory(entry, target="user")
            triggered = True
            logger.info(f"偏移→memory: 检测到偏移率突变 {offset}% ({direction})")

        # 记录当前偏移用于下次对比
        self._last_offset = current

        return {"triggered": triggered, "offset": current.get("offset", 0), "direction": direction}

    def _sync_l1_decay(self) -> Dict:
        """
        L1 AAAK 中的事实超过一定时间未被引用 → 标记衰减
        """
        config = self.config.get("l1_decay", {})
        max_days = config.get("max_unreferenced_days", 30)
        decay_prefix = config.get("decay_prefix", "[DECAY] ")
        l1_path = config.get("weave_to_l1", {}).get("l1_path",
                              os.path.join(_HERMES_DIR, "memory_layers", "l1_facts.aaak"))

        l1_lines = _read_l1(l1_path)
        if not l1_lines:
            return {"decayed": False}

        tracker = _track_l1_references(l1_lines)
        now = datetime.now(timezone.utc)
        decayed = 0

        new_lines = []
        for line in l1_lines:
            # 跳过受保护的核心行
            if line.startswith(("ENV:", "SRV:", "PE:", "GH:", "MODEL:", "MEM:")):
                new_lines.append(line)
                continue

            info = tracker.get(line, {})
            if info.get("decayed"):
                # 已经标记过衰减
                new_lines.append(line)
                continue

            last_seen_str = info.get("last_seen", now.isoformat())
            try:
                last_seen = datetime.fromisoformat(last_seen_str)
                days_unreferenced = (now - last_seen).days
            except Exception:
                days_unreferenced = 0

            if days_unreferenced >= max_days:
                # 标记衰减
                decayed_line = f"{decay_prefix}{line}"
                new_lines.append(decayed_line)
                info["decayed"] = True
                decayed += 1
            else:
                new_lines.append(line)

        if decayed > 0:
            _write_l1(l1_path, new_lines)
            # 更新 tracker
            _track_l1_references(new_lines)
            logger.info(f"L1 衰减: 标记 {decayed} 条事实为衰减")

        return {"decayed": decayed > 0, "count": decayed}

    # ── 状态查询 ──

    def status(self, compact: bool = False):
        """
        各层健康状态。
        返回 {layer_name: {"available": bool, "count": int, "path": str}, ...}
        compact=True 返回单行文本 "L1:11✓|MEM:OK|SG:2843|WV:6|OFS:neutral"
        """
        result = {}

        # 1. L1 AAAK
        l1_path = self.config.get("weave_to_l1", {}).get("l1_path",
                          os.path.join(_HERMES_DIR, "memory_layers", "l1_facts.aaak"))
        l1_lines = _read_l1(l1_path)
        result["l1_aaak"] = {
            "available": os.path.exists(l1_path),
            "count": len(l1_lines),
            "path": l1_path,
        }

        # 2. Memory 工具
        mem_path = os.path.join(_HERMES_DIR, "memories", "MEMORY.md")
        user_path = os.path.join(_HERMES_DIR, "memories", "USER.md")
        mem_count = 0
        if os.path.exists(mem_path):
            with open(mem_path, "r") as f:
                mem_count = f.read().count("§")
        result["memory_tool"] = {
            "available": os.path.exists(mem_path),
            "count": mem_count,
            "path": mem_path,
        }

        # 3. 沙漏
        sand_path = os.path.join(_NB, "sandglass.txt")
        sand_count = 0
        if os.path.exists(sand_path):
            try:
                with open(sand_path, "r") as f:
                    sand_count = sum(1 for _ in f)
            except Exception:
                pass
        result["sandglass"] = {
            "available": os.path.exists(sand_path),
            "count": sand_count,
            "path": sand_path,
        }

        # 4. 织线
        try:
            stats = _wthread_stats()
            result["weavethread"] = {
                "available": stats.get("total_triples", 0) > 0,
                "count": stats.get("total_triples", 0),
                "relations": stats.get("relations", []),
            }
        except Exception as e:
            result["weavethread"] = {"available": False, "error": str(e)}

        # 5. Session Search
        result["session_search"] = {
            "available": os.path.exists(_SESSION_DB),
            "path": _SESSION_DB,
        }

        # 6. ChromaDB
        chroma_path = os.path.join(_NB, "chroma_sand")
        result["chromadb"] = {
            "available": os.path.exists(chroma_path),
            "path": chroma_path,
        }

        # 7. Souls / Offset
        try:
            off = _sandglass_offset()
            result["offset"] = {
                "available": True,
                "current": off.get("offset", 0),
                "direction": off.get("direction", "unknown"),
            }
        except Exception as e:
            result["offset"] = {"available": False, "error": str(e)}

        # compact 模式：返回单行文本
        if compact:
            l1_count = result.get("l1_aaak", {}).get("count", 0)
            l1_avail = "✓" if result.get("l1_aaak", {}).get("available") else "✗"
            mem_avail = "OK" if result.get("memory_tool", {}).get("available") else "N/A"
            sg_count = result.get("sandglass", {}).get("count", 0)
            wv_count = result.get("weavethread", {}).get("count", 0)
            offset_dir = result.get("offset", {}).get("direction", "neutral")
            return f"L1:{l1_count}{l1_avail}|MEM:{mem_avail}|SG:{sg_count}|WV:{wv_count}|OFS:{offset_dir}"

        return result

    # ── 工具方法 ──

    def reload_config(self):
        """重新加载配置"""
        self.config = _load_config()
        self._setup_logging()


# ═══════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hermes 记忆总线")
    parser.add_argument("action", nargs="?", default="status",
                        choices=["search", "recall", "sync", "status", "write"],
                        help="操作")
    parser.add_argument("query", nargs="?", default="", help="搜索关键词/写入内容")
    parser.add_argument("--limit", type=int, default=10, help="结果数量")
    parser.add_argument("--sender", default="user", help="写入时的 sender")
    parser.add_argument("--importance", type=float, default=0.5, help="写入时的重要性 (0-1)")

    args = parser.parse_args()
    bus = MemoryBus()

    if args.action == "search":
        results = bus.search(args.query, limit=args.limit)
        if not results:
            print(f"🔍 未找到「{args.query}」相关记忆")
        else:
            print(f"📚 搜索「{args.query}」结果 ({len(results)}条):")
            for i, r in enumerate(results, 1):
                src = r.get("source", "?")
                layer = r.get("layer", "")
                score = r.get("relevance", 0)
                text = r.get("text", "")
                print(f"\n  {i}. [{src}] (score={score:.1f}) layer={layer}")
                print(f"     {text[:200]}")

    elif args.action == "recall":
        result = bus.recall(args.query, limit=args.limit)
        print(result)

    elif args.action == "sync":
        result = bus.sync()
        if result.get("synced"):
            print(f"✅ 同步完成: {', '.join(result['synced'])}")
        elif result.get("skipped"):
            print(f"⏭️ 跳过（频繁同步）")
        else:
            print("ℹ️ 没有需要同步的变更")
        if result.get("errors"):
            print(f"⚠️ 错误: {result['errors']}")

    elif args.action == "status":
        st = bus.status()
        print("=" * 50)
        print("  Hermes 记忆总线 — 各层健康状态")
        print("=" * 50)
        for layer, info in st.items():
            avail = "✅" if info.get("available") else "❌"
            count = info.get("count", info.get("current", "?"))
            path = info.get("path", info.get("error", ""))
            extra = f" ({info.get('direction', '')})" if "direction" in info else ""
            print(f"  {avail} {layer}: {count}{extra}")
            if path:
                print(f"     {path}")
            if "relations" in info and info["relations"]:
                rels = info["relations"][:5]
                print(f"     关系: {[r[0] for r in rels]}")

    elif args.action == "write":
        result = bus.write({
            "text": args.query,
            "sender": args.sender,
            "importance": args.importance,
        })
        if result.get("ok"):
            print(f"✅ 已写入: {', '.join(result['written_to'])}")
        else:
            print(f"⚠️ 写入部分失败: {result['errors']}")


if __name__ == "__main__":
    main()
