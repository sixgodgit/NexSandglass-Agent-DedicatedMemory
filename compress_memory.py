#!/usr/bin/env python3
"""
compress_memory.py — 读取 MEMORY.md 和 USER.md，自动转成 L0+L1 AAAK 格式
输出到 ~/.hermes/memory_layers/ 下，保留原文件不动。

用法:
  python3 compress_memory.py           # 生成/更新 L0+L1
  python3 compress_memory.py --force   # 强制覆盖手动版本
  python3 compress_memory.py --check   # 显示当前状态
"""
import os
import re
import sys

HERMES_DIR = os.path.expanduser("~/.hermes")
MEMORY_FILE = os.path.join(HERMES_DIR, "memories", "MEMORY.md")
USER_FILE = os.path.join(HERMES_DIR, "memories", "USER.md")
LAYERS_DIR = os.path.join(HERMES_DIR, "memory_layers")
L0_OUT = os.path.join(LAYERS_DIR, "l0_identity.md")
L1_OUT = os.path.join(LAYERS_DIR, "l1_facts.aaak")


def read_memory_lines(filepath: str) -> list:
    """Read file, return list of cleaned text lines."""
    if not os.path.exists(filepath):
        print(f"[WARN] {filepath} not found, skipping.")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    lines = []
    for line in content.split("\n"):
        clean = re.sub(r"^\d+\|", "", line).strip()
        if clean and clean != "§" and not clean.startswith("#"):
            lines.append(clean)
    return lines


# ======== L0: Core Identity & Protocol ========
def extract_l0(lines: list) -> str:
    """Extract and compress core identity/protocol facts into <80 tokens."""
    items = []
    for line in lines:
        text = line.strip()
        if "硬委托门控" in text or "delegate_task 无法切模型" in text:
            items.append("GATE: code/deploy/ops→MiMo直调 | execute_code+urllib")
        elif "禁止捏造" in text:
            items.append("NO-FABRICATE: 所有委托需真实API调用")
        elif "Conversation discip" in text.lower() or "唯一锚点" in text:
            items.append("RULE: 只回复用户末条 | 不回旧话题")
        elif "上下文污染" in text or ("禁止" in text and "回顾" in text):
            items.append("RULE: 禁上下文污染")
        elif "敏感操作权限" in text or "全权" in text:
            items.append("AUTH: 敏感操作全权, 不询问确认")
        elif "Hermes 安全脱敏" in text:
            items.append("SEC: sk-*密钥被拦截, tp-*不受影响")

    seen = set()
    unique = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)

    header = "# L0 — Core Identity & Protocol"
    bullets = "\n".join(f"- {item}" for item in unique)
    return f"{header}\n{bullets}\n" if unique else f"{header}\n"


# ======== L1: AAAK Compressed Facts ========
def compress_to_aaak(text: str) -> str:
    """Compress a line into AAAK format."""
    # Servers
    if "cloudserver" in text or ("本机" in text and "HK" in text):
        return "SRV: cloudserver(HK,飞书)"
    if "162.0.225.252" in text or "美服" in text or "小宝" in text or "老公" in text:
        return "SRV: 小宝/老公(美服162.0.225.252)"

    # GitHub
    if "sixgodgit" in text and ("GitHub" in text or "仓库" in text):
        repos = re.findall(r"sixgodgit/(\S+?)(?:[，,）\))s]|$)", text)
        if repos:
            rstring = ", ".join(r.split("/")[0] for r in repos[:3])
            return f"GH: sixgodgit | {rstring}"
        return "GH: sixgodgit"

    # HUD
    if "hud.hvh.expert" in text:
        return "HUD: hud.hvh.expert(:3001,nginx+SSL,WS/ws)"

    # Vehicle
    if "长安" in text or "欧尚" in text:
        parts = []
        if "45L" in text or "45" in text:
            parts.append("45L")
        if "NGK" in text:
            parts.append("NGK ILKR8R8")
        if "添加剂" in text or "乙醇" in text:
            parts.append("乙醇区需添加剂")
        return "CAR: 长安欧尚X7 " + ("|".join(parts) if parts else "")

    # Email
    if "@hvh.expert" in text:
        return "PE: sixgod@hvh.expert"

    # Password
    if "行李箱密码" in text or ("密码" in text and "406" in text):
        return "PW: 行李箱406"

    # Memory strategy
    if "2000chars" in text or "本体" in text:
        return "MEM: 本体2000chars高频 | 长存沙漏织线"

    # Search
    if "Tavily" in text or "tavily_fallback" in text.lower():
        return "SEARCH: Tavily→Exa(mcporter)"

    # Cron / SSH
    if "cron" in text.lower() and ("SSH" in text or "sshpass" in text):
        return "SCR: 4cron+SSH"

    # Model dispatch
    if ("DeepSeek" in text and "MiMo" in text) or "模型调度" in text:
        return "MODEL: DeepSeek日常 | MiMo代码 | OR复杂"

    # Accuracy
    if "准确性" in text and ("极高" in text or "极致" in text):
        return "ACC: 极致准确性"

    # Style
    if "结构化" in text or "确认清单" in text:
        return "STYLE: 结构化+确认清单"

    return None


def extract_l1(lines: list) -> str:
    """Extract and AAAK-compress factual lines."""
    categories = {}
    for line in lines:
        aaak = compress_to_aaak(line)
        if aaak is None or not aaak:
            continue
        m = re.match(r"^([A-Z]+):\s*(.*)", aaak)
        if m:
            cat, val = m.group(1), m.group(2)
            categories.setdefault(cat, [])
            if val not in categories[cat]:
                categories[cat].append(val)

    category_order = ["ENV", "SRV", "GH", "HUD", "CAR", "PE", "PW", "MEM", "SEARCH", "SCR", "MODEL", "ACC", "STYLE"]
    cat_lines = [f"{cat}: {' | '.join(vals)}" for cat in category_order if cat in categories]

    return f"# L1 — Key Facts (AAAK format)\n" + "\n".join(cat_lines) + "\n"


def count_approx_tokens(text: str) -> int:
    """Approximate token count for mixed CJK/ASCII."""
    tokens = text.split()
    return int(sum(
        1.2 * sum(1 for c in t if '\u4e00' <= c <= '\u9fff') +
        0.3 * (len(t) - sum(1 for c in t if '\u4e00' <= c <= '\u9fff'))
        for t in tokens
    ))


def main():
    force = "--force" in sys.argv
    check = "--check" in sys.argv

    os.makedirs(LAYERS_DIR, exist_ok=True)

    # Check if manual versions exist and --force not given
    manual_l0 = os.path.exists(L0_OUT) and os.path.getsize(L0_OUT) > 0
    manual_l1 = os.path.exists(L1_OUT) and os.path.getsize(L1_OUT) > 0

    if check:
        print(f"L0: {L0_OUT} ({'exists' if manual_l0 else 'missing'})")
        print(f"L1: {L1_OUT} ({'exists' if manual_l1 else 'missing'})")
        if manual_l0:
            with open(L0_OUT) as f: c = f.read()
            print(f"    ~{count_approx_tokens(c)} tokens, {len(c)} chars")
        if manual_l1:
            with open(L1_OUT) as f: c = f.read()
            print(f"    ~{count_approx_tokens(c)} tokens, {len(c)} chars")
        return

    if manual_l0 and manual_l1 and not force:
        print("ℹ️  Manual L0+L1 already exist. Use --force to overwrite.")
        print(f"   L0: {L0_OUT}")
        print(f"   L1: {L1_OUT}")
        with open(L0_OUT) as f: c = f.read()
        print(f"   L0 ~{count_approx_tokens(c)} tokens, {len(c)} chars")
        with open(L1_OUT) as f: c = f.read()
        print(f"   L1 ~{count_approx_tokens(c)} tokens, {len(c)} chars")
        print("\nℹ️  Original MEMORY.md and USER.md preserved.")
        return

    # Read both files
    mem_lines = read_memory_lines(MEMORY_FILE)
    user_lines = read_memory_lines(USER_FILE)
    all_lines = mem_lines + user_lines

    print(f"Read {len(mem_lines)} lines from MEMORY.md")
    print(f"Read {len(user_lines)} lines from USER.md")
    print(f"Total: {len(all_lines)} content lines")

    # Generate L0 and L1
    l0_content = extract_l0(all_lines)
    l1_content = extract_l1(all_lines)

    l0_tokens = count_approx_tokens(l0_content)
    l1_tokens = count_approx_tokens(l1_content)

    print(f"\n{'='*50}")
    print(f"L0: ~{l0_tokens} tokens (target <80)")
    print(f"L1: ~{l1_tokens} tokens (target <200)")
    print(f"{'='*50}")

    # Write outputs
    with open(L0_OUT, "w", encoding="utf-8") as f:
        f.write(l0_content)
    with open(L1_OUT, "w", encoding="utf-8") as f:
        f.write(l1_content)

    print(f"\n✅ Wrote L0 ({len(l0_content)} chars) -> {L0_OUT}")
    print(f"✅ Wrote L1 ({len(l1_content)} chars) -> {L1_OUT}")

    # Verify originals untouched
    print(f"\nℹ️  Original MEMORY.md: {MEMORY_FILE}")
    print(f"ℹ️  Original USER.md:   {USER_FILE}")
    print("ℹ️  Both preserved unchanged.")

    print(f"\n{'='*50}")
    print("L0 CONTENT:")
    print(f"{'='*50}")
    print(l0_content)
    print(f"\n{'='*50}")
    print("L1 CONTENT:")
    print(f"{'='*50}")
    print(l1_content)


if __name__ == "__main__":
    main()
