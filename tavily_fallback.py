#!/usr/bin/env python3
"""
Tavily 搜索自动 Fallback 方案
==============================

优先调用 Tavily API，如果 Tavily 超时/报错/返回空结果，
自动 fallback 到 Exa 语义搜索（通过 mcporter CLI）。

接口兼容 Hermes web_search 工具：
  输入: query (必填), limit (可选, 默认5)
  输出: {"success": true/false, "data": {"web": [{"url":..., "title":..., "description":...}]}}

用法:
  python3 tavily_fallback.py query="搜索词" limit=5
  python3 tavily_fallback.py '{"query": "搜索词", "limit": 5}'
"""

import json
import os
import shlex
import subprocess
import sys
import traceback
from urllib.parse import urlencode, quote_plus

# ── mcporter 必须在 /root 目录下运行，以便正确加载 config/mcporter.json ──
MCPORTER_WORKDIR = os.path.expanduser("~")

# ─── 配置 ───────────────────────────────────────────────────────
TAVILY_API_URL = "https://api.tavily.com/search"
TAVILY_API_KEY_ENV = "TAVILY_API_KEY"

# Jina Reader 用于提炼网页内容
JINA_READER_URL = "https://r.jina.ai"

# mcporter 环境
MCPORTER_VENV = os.path.expanduser("~/.agent-reach-venv/bin/activate")
MCPORTER_CMD = "mcporter"

# 环境变量
NO_PROXY_WILDCARD = {"NO_PROXY": "*", "no_proxy": "*", "HTTP_PROXY": "", "HTTPS_PROXY": "", "http_proxy": "", "https_proxy": ""}

# Tavily API key (写在脚本启动时的备选路径，以防 env 未设置)
# 如果环境变量为空，尝试从已知来源读取
FALLBACK_API_KEYS = [
    os.path.expanduser("~/.hermes/.tavily_key"),
    os.path.expanduser("~/.tavily_key"),
]


def _load_dotenv():
    """从 Hermes .env 文件加载环境变量（不覆盖已存在的）"""
    dotenv_paths = [
        os.path.expanduser("~/.hermes/.env"),
        os.path.expanduser("~/.hermes/profiles/default/.env"),
    ]
    for dp in dotenv_paths:
        if not os.path.isfile(dp):
            continue
        try:
            with open(dp) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and val and key not in os.environ:
                        os.environ[key] = val
        except Exception:
            pass


def get_tavily_api_key():
    """获取 Tavily API key，优先从环境变量，其次从文件"""
    _load_dotenv()
    key = os.environ.get(TAVILY_API_KEY_ENV, "") or os.environ.get("TAVILY_API_KEY", "")
    if key:
        return key.strip()
    # 尝试从文件读取
    for key_file in FALLBACK_API_KEYS:
        if os.path.isfile(key_file):
            try:
                with open(key_file) as f:
                    k = f.read().strip()
                    if k:
                        return k
            except Exception:
                pass
    return ""


def call_tavily(query, limit=5, timeout=20):
    """
    调用 Tavily API。
    返回: (results_list, error_msg_or_None)
    """
    api_key = get_tavily_api_key()
    if not api_key:
        return None, "Tavily API key 未设置"

    import urllib.request

    # 绕过 SOCKS5 代理
    proxy_env = {**os.environ, "NO_PROXY": "api.tavily.com", "no_proxy": "api.tavily.com",
                 "HTTP_PROXY": "", "HTTPS_PROXY": "", "http_proxy": "", "https_proxy": ""}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    # ProxyHandler({}) 绕过默认代理，但保留 NO_PROXY 不生效时的手动设置

    payload = json.dumps({
        "api_key": api_key,
        "query": query,
        "max_results": limit,
        "include_answer": False,
        "include_raw_content": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        TAVILY_API_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        # 设置环境变量绕过代理 + 使用空 proxy handler
        saved_env = {}
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy"):
            saved_env[k] = os.environ.pop(k, None)
        os.environ["NO_PROXY"] = "api.tavily.com"

        resp = opener.open(req, timeout=timeout)
        data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return None, f"Tavily API 请求失败: {e}"
    finally:
        # 恢复原始代理设置
        for k, v in saved_env.items():
            if v is not None:
                os.environ[k] = v
            elif k in os.environ:
                del os.environ[k]

    results = data.get("results", [])
    if not results:
        return None, "Tavily 返回空结果"

    return results, None


def call_exa_via_mcporter(query, limit=5, timeout=30):
    """
    通过 mcporter CLI 调用 Exa 语义搜索。
    返回: (results_list, error_msg_or_None)
    """
    # 使用 --args JSON 方式传递参数，避免 shell 引号/冒号解析问题
    args_json = json.dumps({"query": query, "max_results": limit})
    mcargs = f"{MCPORTER_CMD} call exa.web_search_exa --args {shlex.quote(args_json)}"

    # 构建完整 shell 命令：激活 venv + 清除代理 + 调用 mcporter
    cmd = (
        f"source {MCPORTER_VENV} && "
        f"export NO_PROXY='*' no_proxy='*' HTTP_PROXY='' HTTPS_PROXY='' http_proxy='' https_proxy='' && "
        + mcargs
    )

    try:
        proc = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=MCPORTER_WORKDIR,  # 必须在 /root 下运行才能加载 config/mcporter.json
        )
    except subprocess.TimeoutExpired:
        return None, "Exa mcporter 调用超时"
    except Exception as e:
        return None, f"Exa mcporter 调用失败: {e}"

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        error_msg = stderr or stdout or f"mcporter 退出码 {proc.returncode}"
        return None, f"Exa mcporter 返回错误: {error_msg}"

    raw_output = (proc.stdout or "").strip()
    if not raw_output:
        return None, "Exa mcporter 返回空输出"

    # mcporter 输出是纯文本格式，每条记录用 --- 分隔
    # 需要手动解析
    return parse_mcporter_output(raw_output), None


def parse_mcporter_output(raw_output):
    """
    解析 mcporter 纯文本输出为结构化结果列表。
    mcporter 输出格式为：
      Title: ...
      URL: ...
      Published: ...
      Author: ...
      Highlights:
        text...
      ---
      Title: ...
    """
    results = []
    blocks = raw_output.split("\n---\n")

    for block in blocks:
        lines = block.strip().split("\n")
        title = ""
        url = ""
        highlights = []

        current_section = None
        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith("Title: "):
                title = line_stripped[len("Title: "):]
            elif line_stripped.startswith("URL: "):
                url = line_stripped[len("URL: "):]
            elif line_stripped.startswith("Published: "):
                pass  # 暂不处理日期
            elif line_stripped.startswith("Author: "):
                pass  # 暂不处理作者
            elif line_stripped.startswith("Highlights:"):
                current_section = "highlights"
            elif current_section == "highlights" and line_stripped:
                highlights.append(line_stripped)

        if title and url:
            description = " ".join(highlights) if highlights else title
            # 截取过长的描述
            if len(description) > 800:
                description = description[:800] + "..."
            results.append({
                "url": url,
                "title": title,
                "description": description,
            })

    return results


def call_jina_extract(url, timeout=15):
    """
    用 Jina Reader 提炼网页内容。
    返回: (markdown_text, error_or_None)
    """
    import urllib.request

    jina_url = f"{JINA_READER_URL}/{url}"
    req = urllib.request.Request(jina_url, headers={
        "Accept": "text/markdown",
        "User-Agent": "Mozilla/5.0",
    })

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        content = resp.read().decode("utf-8")
        # 截取部分内容
        if len(content) > 3000:
            content = content[:3000] + "\n\n[... truncated ...]"
        return content, None
    except Exception as e:
        return None, f"Jina Reader 提取失败: {e}"


def normalize_tavily_results(results, query, limit):
    """
    将 Tavily 结果标准化为统一格式。
    如果结果含 raw_content，一并使用。
    """
    items = []
    for r in results[:limit]:
        item = {
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "description": r.get("content", r.get("title", "")),
        }
        items.append(item)
    return items


def normalize_exa_results(results, query, limit):
    """
    将 Exa 结果标准化为统一格式。
    """
    items = []
    for r in results[:limit]:
        item = {
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "description": r.get("description", r.get("title", "")),
        }
        items.append(item)
    return items


def search(query, limit=5):
    """
    主搜索函数：优先 Tavily → fallback Exa。
    返回符合 Hermes web_search 接口格式的 dict。
    """
    if not query or not query.strip():
        return {"success": False, "data": {"web": []}}

    query = query.strip()
    limit = int(limit)
    if limit < 1:
        limit = 5
    if limit > 20:
        limit = 20  # 限制最大结果数

    # ── 阶段 1: 尝试 Tavily ──
    tavily_results, tavily_error = call_tavily(query, limit)

    if tavily_results is not None:
        # Tavily 成功
        items = normalize_tavily_results(tavily_results, query, limit)
        return {
            "success": True,
            "source": "tavily",
            "data": {"web": items},
        }

    sys.stderr.write(f"[tavily_fallback] Tavily 失败: {tavily_error}\n")

    # ── 阶段 2: Fallback 到 Exa ──
    sys.stderr.write("[tavily_fallback] Fallback 到 Exa mcporter...\n")
    exa_results, exa_error = call_exa_via_mcporter(query, limit)

    if exa_results is not None and len(exa_results) > 0:
        items = normalize_exa_results(exa_results, query, limit)
        return {
            "success": True,
            "source": "exa_fallback",
            "data": {"web": items},
        }

    sys.stderr.write(f"[tavily_fallback] Exa 也失败: {exa_error}\n")

    # ── 阶段 3: 都失败了 ──
    return {
        "success": False,
        "source": "none",
        "error": f"Tavily 失败: {tavily_error}; Exa 也失败: {exa_error}",
        "data": {"web": []},
    }


def parse_args(args=None):
    """
    解析命令行参数。
    支持:
      python3 script.py query="xxx" limit=5
      python3 script.py '{"query": "xxx", "limit": 5}'
    """
    if args is None:
        args = sys.argv[1:]

    if not args:
        return None

    # 尝试解析为 JSON (整个参数是一条 JSON 字符串)
    if len(args) == 1:
        try:
            parsed = json.loads(args[0])
            if isinstance(parsed, dict) and "query" in parsed:
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # 解析 key=value 格式
    result = {}
    for arg in args:
        if "=" in arg:
            key, value = arg.split("=", 1)
            # 去掉外层引号
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            result[key] = value
        else:
            # 单纯一个字符串，当作 query
            result["query"] = arg

    return result if "query" in result else None


def main():
    params = parse_args()
    if not params:
        print(json.dumps({
            "success": False,
            "error": "参数错误: 需要 query 参数。用法: python3 tavily_fallback.py query='搜索词' limit=5",
            "data": {"web": []},
        }, ensure_ascii=False))
        sys.exit(1)

    query = params.get("query", "")
    limit = int(params.get("limit", 5))

    result = search(query, limit)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
