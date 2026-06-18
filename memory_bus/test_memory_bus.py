#!/usr/bin/env python3
"""
Memory Bus 测试脚本 — 验证核心同步功能和查询接口
=============================================
测试项目：
1. bus.status() — 各层健康状态
2. bus.search("关键词") — 聚合查询
3. bus.recall("主题") — 快速回忆
4. bus.write({"text": "..."}) — 统一写入
5. _sync_weave_to_l1 — 织线→L1 同步
6. _sync_l1_decay — L1 衰减标记
7. 去重排序功能

用法：
  python3 test_memory_bus.py         # 运行全部测试
  python3 test_memory_bus.py --list  # 列出可用测试
  python3 test_memory_bus.py test_01_status  # 运行单个测试
"""

import os
import sys
import json
import time

# 添加脚本目录到路径
sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from memory_bus import MemoryBus, _read_l1, _write_l1

# ── 测试结果统计 ──
_pass = 0
_fail = 0
_errors = []


def _check(name: str, condition: bool, detail: str = ""):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  ✅ PASS: {name}")
    else:
        _fail += 1
        msg = f"❌ FAIL: {name} — {detail}"
        print(f"  {msg}")
        _errors.append(msg)


def _section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ═══════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════

def test_01_status():
    """测试 bus.status() 各层健康状态"""
    bus = MemoryBus()
    st = bus.status()

    _check("返回类型是 dict", isinstance(st, dict))
    _check("包含 L1 层", "l1_aaak" in st)
    _check("包含 memory_tool", "memory_tool" in st)
    _check("包含 sandglass", "sandglass" in st)
    _check("包含 weavethread", "weavethread" in st)
    _check("包含 session_search", "session_search" in st)
    _check("每层有 available 字段", all("available" in v for v in st.values()))

    print(f"\n  L1: {st.get('l1_aaak', {})}")
    print(f"  Sandglass: {st.get('sandglass', {})}")
    print(f"  WeaveThread: {st.get('weavethread', {})}")
    print(f"  Offset: {st.get('offset', {})}")


def test_02_search():
    """测试 bus.search() 聚合查询"""
    bus = MemoryBus()
    results = bus.search("服务器", limit=10)

    _check("返回列表", isinstance(results, list))
    _check("每项有 source 字段", all("source" in r for r in results))
    _check("每项有 text 字段", all("text" in r for r in results))
    _check("每项有 relevance 字段", all("relevance" in r for r in results))
    if len(results) >= 2:
        _check("按相关性降序", all(
            results[i]["relevance"] >= results[i + 1]["relevance"]
            for i in range(len(results) - 1)
        ), f"results[0].relevance={results[0]['relevance']} < results[1].relevance={results[1]['relevance']} 可能未降序")
    else:
        _check("结果≥2条时不检查排序（条数不足）", True)
    _check("结果数不超过 limit", len(results) <= 10)

    if results:
        print(f"\n  搜索「服务器」找到 {len(results)} 条结果:")
        for r in results[:5]:
            print(f"    [{r['source']}] (score={r['relevance']:.1f}) {r['text'][:100]}")


def test_03_recall():
    """测试 bus.recall() 快速回忆"""
    bus = MemoryBus()
    result = bus.recall("环境", limit=5)

    _check("返回字符串", isinstance(result, str))
    _check("非空", len(result) > 0)
    # 检查回忆结果结构：要么包含"📚"（有结果），要么包含"未找到"（无结果）
    has_proper_structure = "📚" in result or "未找到" in result
    _check("回忆结果结构正确（含 📚 或 未找到）", has_proper_structure,
           f"recall 输出应包含 '📚' 或 '未找到': {result[:100]}")

    print(f"\n  recall 结果（前200字）:")
    print(f"  {result[:200]}")


def test_04_write():
    """测试 bus.write() 统一写入"""
    bus = MemoryBus()
    result = bus.write({
        "text": "测试: 记忆总线统一写入测试",
        "sender": "test",
        "importance": 0.7,
        "category": "fact",
        "tags": ["test", "memory_bus"],
    })

    _check("写入返回 dict", isinstance(result, dict))
    _check("包含 written_to 字段", "written_to" in result)
    _check("至少写入沙漏", "sandglass" in result.get("written_to", []))
    _check("ok 为 True", result.get("ok", False))


def test_05_weave_to_l1_sync():
    """测试织线→L1 同步（不破坏原有数据）"""
    bus = MemoryBus()

    # 记录同步前的 L1 行数
    l1_path = bus.config.get("weave_to_l1", {}).get("l1_path",
                      os.path.expanduser("~/.hermes/memory_layers/l1_facts.aaak"))
    before = _read_l1(l1_path)
    before_count = len(before)

    # 执行同步
    result = bus._sync_weave_to_l1()

    # 读取同步后的 L1
    after = _read_l1(l1_path)
    after_count = len(after)

    _check("同步返回 dict", isinstance(result, dict))
    _check("updated 字段存在", "updated" in result)
    _check("L1 行数未减少（不会删除现有数据）", after_count >= before_count)

    print(f"\n  L1 行数: {before_count} → {after_count}")
    print(f"  同步结果: {json.dumps(result, ensure_ascii=False, default=str)[:200]}")


def test_06_l1_decay():
    """测试 L1 衰减标记功能"""
    bus = MemoryBus()
    l1_path = bus.config.get("weave_to_l1", {}).get("l1_path",
                      os.path.expanduser("~/.hermes/memory_layers/l1_facts.aaak"))

    # 添加一条测试事实
    test_fact = "TEST_MARKER: memory_bus test fact for decay check"
    before = _read_l1(l1_path)
    _write_l1(l1_path, before + [test_fact])

    # 读取 tracker 并设置该事实的 last_seen 为 60 天前
    track_file = os.path.expanduser("~/.hermes/memory_bus/.l1_reference_tracker.json")
    os.makedirs(os.path.dirname(track_file), exist_ok=True)
    tracker = {}
    if os.path.exists(track_file):
        with open(track_file) as f:
            tracker = json.load(f)
    from datetime import datetime, timezone, timedelta
    tracker[test_fact] = {
        "last_seen": (datetime.now(timezone.utc) - timedelta(days=61)).isoformat(),
        "count": 0,
        "decayed": False,
    }
    with open(track_file, "w") as f:
        json.dump(tracker, f, ensure_ascii=False, indent=2)

    # 触发衰减
    bus.config["l1_decay"]["max_unreferenced_days"] = 30
    result = bus._sync_l1_decay()

    # 检查测试事实是否被标记
    after = _read_l1(l1_path)
    marked = [l for l in after if "[DECAY]" in l and "TEST_MARKER" in l]

    _check("衰减测试标记成功", len(marked) > 0, f"找到 {len(marked)} 条标记")

    # 清理测试标记
    clean = [l for l in after if "TEST_MARKER" not in l]
    _write_l1(l1_path, clean)

    print(f"  衰减结果: {result}")


def test_07_offset_detect():
    """测试偏移率检测"""
    from memory_bus import _sandglass_offset
    bus = MemoryBus()
    off = _sandglass_offset()

    _check("偏移率返回 dict", isinstance(off, dict))
    _check("包含 offset", "offset" in off)
    _check("包含 direction", "direction" in off)
    _check("offset 是数字", isinstance(off.get("offset"), (int, float)))

    print(f"  当前偏移: {off.get('direction', '?')} ({off.get('offset', 0):+d}%)")


def test_08_search_dedup():
    """测试查询去重功能"""
    bus = MemoryBus()
    results = bus.search("DeepSeek", limit=20)
    # 检查去重：text 前缀唯一
    seen = set()
    for r in results:
        text_key = r.get("text", "")[:50]
        if text_key in seen:
            _check(f"去重检查: 发现重复项 {text_key[:30]}...", False)
            break
        seen.add(text_key)
    else:
        _check("查询去重: 无重复", True)

    print(f"  搜索 'DeepSeek' → {len(results)} 条去重结果")
    for r in results[:5]:
        print(f"    [{r['source']}] (score={r['relevance']:.1f}) {r['text'][:80]}")


def test_09_empty_search():
    """测试空关键词搜索（健壮性）"""
    bus = MemoryBus()
    results = bus.search("")

    _check("空搜索返回列表", isinstance(results, list))
    _check("空搜索返回空列表（搜索词为空时应无结果）", len(results) == 0,
           f"期望空列表([])，实际得到 {len(results)} 条结果")
    _check("空搜索非 None", results is not None)

    print(f"  空搜索返回 {len(results)} 条结果（期望 0）")


def test_10_l1_read_write():
    """测试 L1 文件读写不损坏原格式"""
    l1_path = os.path.expanduser("~/.hermes/memory_layers/l1_facts.aaak")
    before = _read_l1(l1_path)

    # 写入一条测试行再删除
    _write_l1(l1_path, before + ["TEST_TMP: temp entry"])
    mid = _read_l1(l1_path)
    clean = [l for l in mid if "TEST_TMP" not in l]
    _write_l1(l1_path, clean)
    after = _read_l1(l1_path)

    _check("L1 读写后恢复原状", len(before) == len(after),
           f"before={len(before)}, after={len(after)}")
    _check("L1 注释头保留", os.path.exists(l1_path) and open(l1_path).read().startswith("#"),
           "L1 文件开头应是注释")


def test_11_sync_integration():
    """测试 bus.sync() 完整流程（含频率限制跳过逻辑）"""
    bus = MemoryBus()

    # 第一次 sync：应正常执行
    result1 = bus.sync()
    _check("sync 返回 dict", isinstance(result1, dict))
    _check("sync 包含 synced 字段", "synced" in result1)
    _check("sync 包含 errors 字段", "errors" in result1)
    _check("sync 包含 ok 字段", "ok" in result1)

    # 第二次立即 sync：因频率限制应被跳过
    result2 = bus.sync()
    _check("频繁 sync 被跳过",
           result2.get("skipped") == "too_frequent",
           f"期望 skipped='too_frequent'，实际: {result2}")

    # 等待 sync_interval 后再次 sync
    bus._last_sync_time = 0  # 重置计时器，绕过频率限制
    result3 = bus.sync()
    _check("重置后 sync 可正常执行",
           result3.get("skipped") != "too_frequent",
           f"重置后仍被跳过: {result3}")

    print(f"\n  第一次 sync: synced={result1.get('synced', [])}")
    print(f"  第二次 sync（立即）: skipped={result2.get('skipped', 'N/A')}")
    print(f"  重置后 sync: synced={result3.get('synced', [])}")


def test_12_importance_boundary():
    """测试 importance 边界行为：0.5, 0.59, 0.6, 0.69, 0.7"""
    bus = MemoryBus()

    test_cases = [
        (0.5, False, "importance=0.5（低于阈值，不应写 memory_tool）"),
        (0.59, False, "importance=0.59（低于阈值，不应写 memory_tool）"),
        (0.6, True, "importance=0.6（等于阈值，应写 memory_tool）"),
        (0.69, True, "importance=0.69（高于阈值，应写 memory_tool）"),
        (0.7, True, "importance=0.7（等于织线阈值，应写 memory_tool）"),
    ]

    for imp, expect_memory, label in test_cases:
        result = bus.write({
            "text": f"TEST_BOUNDARY: importance={imp}",
            "sender": "test",
            "importance": imp,
            "category": "fact",
        })
        has_memory = "memory_tool" in result.get("written_to", [])
        _check(label, has_memory == expect_memory,
               f"importance={imp}: 期望 memory_tool={'是' if expect_memory else '否'}，实际={'是' if has_memory else '否'}")
        # 已确认，不保留痕迹
        if has_memory:
            # 清理写过的 memory 文件（避免污染）
            for fname in ["MEMORY.md", "USER.md"]:
                mpath = os.path.join(os.path.expanduser("~/.hermes/memories"), fname)
                if os.path.exists(mpath):
                    with open(mpath, "r+") as f:
                        content = f.read()
                        cleaned = content.replace(f"TEST_BOUNDARY: importance={imp} [bus:", "")
                        f.seek(0)
                        f.write(cleaned)
                        f.truncate()

    print(f"\n  共测试 {len(test_cases)} 个边界值")
    for imp, _, label in test_cases:
        print(f"    importance={imp}: {'✅ memory_tool' if imp >= 0.6 else '⏭️ 跳过 memory_tool'}")


def test_13_l1_empty():
    """测试 L1 文件不存在或为空时的容错行为"""
    l1_path = os.path.expanduser("~/.hermes/memory_layers/l1_facts.aaak")

    # 1. 备份当前 L1
    backup = None
    if os.path.exists(l1_path):
        with open(l1_path, "r") as f:
            backup = f.read()

    # 2. 测试空文件
    empty_path = l1_path + ".empty_test"
    try:
        # 创建空 L1 文件
        with open(empty_path, "w") as f:
            f.write("# Empty test L1\n")

        # 临时替换配置
        bus = MemoryBus()
        orig_l1_path = bus.config["weave_to_l1"]["l1_path"]
        bus.config["weave_to_l1"]["l1_path"] = empty_path

        # search 不应崩溃
        results = bus.search("anything")
        _check("空 L1 搜索返回列表", isinstance(results, list))

        # status 不应崩溃
        st = bus.status()
        _check("空 L1 状态返回 dict", isinstance(st, dict))

        # sync 不应崩溃
        sync_res = bus.sync()
        _check("空 L1 sync 返回 dict", isinstance(sync_res, dict))

        # recall 不应崩溃
        recall_res = bus.recall("anything")
        _check("空 L1 recall 返回字符串", isinstance(recall_res, str))

        # 3. 测试不存在文件
        fake_path = l1_path + ".nonexistent"
        bus.config["weave_to_l1"]["l1_path"] = fake_path
        results2 = bus.search("test")
        _check("L1 不存在时搜索返回列表", isinstance(results2, list))

        # 恢复原始配置
        bus.config["weave_to_l1"]["l1_path"] = orig_l1_path

    finally:
        # 清理临时文件
        if os.path.exists(empty_path):
            os.remove(empty_path)
        # 恢复 L1
        if backup is not None:
            with open(l1_path, "w") as f:
                f.write(backup)

    print(f"\n  空 L1 文件搜索: {len(results)} 条结果")
    print(f"  不存在 L1 文件搜索: {len(results2)} 条结果")


# ═══════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════

def main():
    global _pass, _fail, _errors

    tests = [
        ("test_01_status", test_01_status, "bus.status() 各层健康状态"),
        ("test_02_search", test_02_search, "bus.search() 聚合查询"),
        ("test_03_recall", test_03_recall, "bus.recall() 快速回忆"),
        ("test_04_write", test_04_write, "bus.write() 统一写入"),
        ("test_05_weave_to_l1_sync", test_05_weave_to_l1_sync, "织线→L1 同步"),
        ("test_06_l1_decay", test_06_l1_decay, "L1 衰减标记"),
        ("test_07_offset_detect", test_07_offset_detect, "偏移率检测"),
        ("test_08_search_dedup", test_08_search_dedup, "查询去重"),
        ("test_09_empty_search", test_09_empty_search, "空搜索健壮性"),
        ("test_10_l1_read_write", test_10_l1_read_write, "L1 文件读写"),
        ("test_11_sync_integration", test_11_sync_integration, "sync 完整流程与频率限制"),
        ("test_12_importance_boundary", test_12_importance_boundary, "importance 边界值"),
        ("test_13_l1_empty", test_13_l1_empty, "L1 空/不存在文件容错"),
    ]

    if "--list" in sys.argv:
        print("可用测试:")
        for name, _, desc in tests:
            print(f"  {name}: {desc}")
        return

    # 如果指定了测试名称，只运行该测试
    specific = [a for a in sys.argv[1:] if a.startswith("test_")]

    _section("Hermes 记忆总线 — 测试套件")
    print(f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Python: {sys.version.split()[0]}")

    for name, func, desc in tests:
        if specific and name not in specific:
            continue
        _section(f"  {name}: {desc}")
        try:
            func()
        except Exception as e:
            _fail += 1
            msg = f"❌ EXCEPTION: {name} — {e}"
            print(f"  {msg}")
            import traceback
            traceback.print_exc()
            _errors.append(msg)

    # 汇总
    total = _pass + _fail
    _section("测试汇总")
    print(f"  总测试数: {total}")
    print(f"  ✅ 通过: {_pass}")
    print(f"  ❌ 失败: {_fail}")
    print(f"  通过率: {(_pass / total * 100) if total > 0 else 0:.1f}%")

    if _errors:
        print(f"\n  错误详情:")
        for e in _errors[:5]:
            print(f"    {e}")

    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
