#!/usr/bin/env python3
"""
Memory Bus MCP Server V1.0
==========================
暴露 bus.search, bus.recall, bus.status, bus.sync 四个工具到 MCP 协议。
标准模式：stdio（默认）
HTTP 模式：python memory_bus_mcp.py --port 8080

参考 sandglass_mcp.py 的 stdio JSON-RPC 模式。
"""

import json
import os
import sys
import argparse

# 添加脚本目录和 NexSandglass 路径
_HERMES_DIR = os.path.expanduser("~/.hermes")
_SCRIPTS_DIR = os.path.join(_HERMES_DIR, "scripts")
_NEX_SRC = os.path.join(_HERMES_DIR, "NexSandglass")
for p in [_SCRIPTS_DIR, _NEX_SRC]:
    if p not in sys.path:
        sys.path.insert(0, p)

from memory_bus import MemoryBus

# ── 全局实例 ──
_bus = MemoryBus()


# ═══════════════════════════════════════════════
# JSON-RPC 2.0 响应构建
# ═══════════════════════════════════════════════

def _rpc_response(req_id, result, wrap=True):
    """wrap=True for tools/call (MCP content blocks). wrap=False for initialize, tools/list."""
    if not wrap:
        return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {
        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result}]
    }})


def _rpc_error(req_id, code, message):
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


# ═══════════════════════════════════════════════
# 工具处理
# ═══════════════════════════════════════════════

def _handle_tool(name, args, request_id):
    try:
        if name == "bus_search":
            query = args.get("query", "")
            limit = args.get("limit", 3)
            compact = args.get("compact", False)
            # limit 最多 5 条
            limit = min(limit, 5)
            results = _bus.search(query, limit=limit)

            if compact:
                # 极简模式：纯文本行
                lines = []
                for r in results:
                    src = r.get("source", "?")
                    text = r.get("text", "")[:100]
                    lines.append(f"{src}: {text}")
                return _rpc_response(request_id, "\n".join(lines))

            # 标准模式：精简 JSON，每条只含 source + text 摘要（不超过 100 字）
            compact_results = []
            for r in results:
                compact_results.append({
                    "source": r.get("source", "?"),
                    "text": r.get("text", "")[:100],
                })
            return _rpc_response(request_id, compact_results)

        elif name == "bus_recall":
            topic = args.get("topic", "")
            max_tokens = args.get("max_tokens", 0)
            result = _bus.recall(topic, limit=5)
            if max_tokens > 0 and result:
                # 粗略截断：1 token ≈ 1.5 字符（中文）/ 4 字符（英文）
                # 保守估计按 2 字符 / token
                max_chars = max_tokens * 3
                if len(result) > max_chars:
                    result = result[:max_chars] + "...[截断]"
            return _rpc_response(request_id, result)

        elif name == "bus_status":
            compact = args.get("compact", False)
            st = _bus.status()
            if compact:
                # 极简一行文本
                l1_count = st.get("l1_aaak", {}).get("count", 0)
                l1_avail = "✓" if st.get("l1_aaak", {}).get("available") else "✗"
                mem_avail = "OK" if st.get("memory_tool", {}).get("available") else "N/A"
                sg_count = st.get("sandglass", {}).get("count", 0)
                wv_count = st.get("weavethread", {}).get("count", 0)
                offset_dir = st.get("offset", {}).get("direction", "neutral")
                line = f"L1:{l1_count}{l1_avail}|MEM:{mem_avail}|SG:{sg_count}|WV:{wv_count}|OFS:{offset_dir}"
                return _rpc_response(request_id, line)
            # 标准模式的精简版：只保留关键字段
            result = {
                "l1": {"available": st.get("l1_aaak", {}).get("available"), "count": st.get("l1_aaak", {}).get("count")},
                "memory_tool": {"available": st.get("memory_tool", {}).get("available"), "count": st.get("memory_tool", {}).get("count")},
                "sandglass": {"available": st.get("sandglass", {}).get("available"), "count": st.get("sandglass", {}).get("count")},
                "weavethread": {"available": st.get("weavethread", {}).get("available"), "count": st.get("weavethread", {}).get("count")},
                "session_search": {"available": st.get("session_search", {}).get("available")},
                "offset": {"direction": st.get("offset", {}).get("direction"), "current": st.get("offset", {}).get("current")},
            }
            return _rpc_response(request_id, result)

        elif name == "bus_sync":
            result = _bus.sync()
            return _rpc_response(request_id, result)

        else:
            return _rpc_error(request_id, -32601, f"Unknown tool: {name}")

    except Exception as e:
        return _rpc_error(request_id, -32000, str(e))


# ═══════════════════════════════════════════════
# 工具列表
# ═══════════════════════════════════════════════

_TOOLS = [
    {
        "name": "bus_search",
        "description": "统一记忆搜索——聚合 L1 + memory + sandglass + session，按相关性排序。返回精简JSON（仅source+text摘要≤100字）。最多5条。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "limit": {"type": "integer", "description": "最大返回条数（默认3，最多5）", "default": 3},
                "compact": {"type": "boolean", "description": "极简模式：返回纯文本行 \"source: 摘要\"，<200 tokens", "default": False},
            },
            "required": ["query"],
        },
    },
    {
        "name": "bus_recall",
        "description": "快速回忆——精简版search，返回可直接注入prompt的回忆文本。支持max_tokens截断。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "回忆主题"},
                "max_tokens": {"type": "integer", "description": "可选，截断到指定token数以内（保守估计）", "default": 0},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "bus_status",
        "description": "各层健康状态。返回各层可用性和统计。compact模式返回单行字符串，适合注入prompt。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "compact": {"type": "boolean", "description": "极简模式：返回单行文本 \"L1:11✓|MEM:OK|SG:2843|WV:6|OFS:neutral\"", "default": False},
            },
        },
    },
    {
        "name": "bus_sync",
        "description": "跨系统同步——织线→L1、梦境→memory、偏移率→memory、L1衰减标记。返回{synced, errors, ok}。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ═══════════════════════════════════════════════
# stdio 主循环
# ═══════════════════════════════════════════════

def stdio_main():
    """MCP stdio 主循环——可从 stdin 读取 JSON-RPC 请求"""
    for line in sys.stdin:
        try:
            req = json.loads(line.strip())
            method = req.get("method", "")

            # JSON-RPC 2.0: notifications 没有 id，不应回复
            if "id" not in req:
                continue
            tid = req["id"]

            if method == "tools/list":
                print(_rpc_response(tid, {"tools": _TOOLS}, wrap=False), flush=True)

            elif method == "tools/call":
                name = req.get("params", {}).get("name", "")
                args = req.get("params", {}).get("arguments", {})
                print(_handle_tool(name, args, tid), flush=True)

            elif method == "initialize":
                print(_rpc_response(tid, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "MemoryBus", "version": "1.0"},
                }, wrap=False), flush=True)

            else:
                print(_rpc_error(tid, -32601, f"Unknown method: {method}"), flush=True)

        except json.JSONDecodeError:
            print(_rpc_error(0, -32700, "Parse error"), flush=True)
        except Exception as e:
            print(_rpc_error(0, -32000, str(e)), flush=True)


# ═══════════════════════════════════════════════
# HTTP 模式
# ═══════════════════════════════════════════════

def http_main(port: int):
    """HTTP 模式——简单的 JSON-RPC over HTTP"""
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class MCPHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                req = json.loads(body)
                method = req.get("method", "")
                tid = req.get("id", 0)

                if method == "tools/list":
                    resp = _rpc_response(tid, {"tools": _TOOLS}, wrap=False)
                elif method == "tools/call":
                    name = req.get("params", {}).get("name", "")
                    args = req.get("params", {}).get("arguments", {})
                    resp = _handle_tool(name, args, tid)
                elif method == "initialize":
                    resp = _rpc_response(tid, {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "MemoryBus", "version": "1.0"},
                    }, wrap=False)
                else:
                    resp = _rpc_error(tid, -32601, f"Unknown method: {method}")

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(resp.encode("utf-8"))

            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        def log_message(self, fmt, *args):
            pass  # 静默模式

    server = HTTPServer(("0.0.0.0", port), MCPHandler)
    print(f"Memory Bus MCP Server running on HTTP port {port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


# ═══════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Memory Bus MCP Server")
    parser.add_argument("--port", type=int, default=None,
                        help="HTTP 模式端口（不指定则用 stdio 模式）")
    args = parser.parse_args()

    if args.port:
        http_main(args.port)
    else:
        stdio_main()


if __name__ == "__main__":
    main()
