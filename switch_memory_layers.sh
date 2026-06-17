#!/bin/bash
# switch_memory_layers.sh — 切换 persona prompt 指向 L0+L1 而非原 MEMORY.md
# 用法:
#   ./switch_memory_layers.sh [enable|disable|status]
#
# enable:  在 config.yaml 的 system_prompt 或 persona 中插入 L0+L1 引用
# disable: 移除 L0+L1 引用, 恢复原 MEMORY.md
# status:  查看当前状态
#
# 注意: 此脚本不会删除原 MEMORY.md, 新旧可共存。

set -e

HERMES_DIR="$HOME/.hermes"
CONFIG="$HERMES_DIR/config.yaml"
LAYERS_DIR="$HERMES_DIR/memory_layers"
MARKER_BEGIN="# >>> L0+L1 MEMORY LAYERS (AAAK) >>>"
MARKER_END="# <<< L0+L1 MEMORY LAYERS <<<"

L0_FILE="$LAYERS_DIR/l0_identity.md"
L1_FILE="$LAYERS_DIR/l1_facts.aaak"

ensure_files() {
    if [ ! -f "$L0_FILE" ]; then
        echo "❌ L0 file not found: $L0_FILE"
        exit 1
    fi
    if [ ! -f "$L1_FILE" ]; then
        echo "❌ L1 file not found: $L1_FILE"
        exit 1
    fi
}

get_marker_status() {
    if grep -q "$MARKER_BEGIN" "$CONFIG" 2>/dev/null; then
        echo "enabled"
    else
        echo "disabled"
    fi
}

cmd_enable() {
    ensure_files
    local status
    status=$(get_marker_status)
    if [ "$status" = "enabled" ]; then
        echo "ℹ️  L0+L1 layers already enabled in config.yaml"
        return 0
    fi

    local l0_content l1_content
    l0_content=$(cat "$L0_FILE")
    l1_content=$(cat "$L1_FILE")

    # Escape for sed
    l0_escaped=$(printf '%s\n' "$l0_content" | sed 's/[\&/]/\\&/g')
    l1_escaped=$(printf '%s\n' "$l1_content" | sed 's/[\&/]/\\&/g')

    # Build the insertion block
    local block
    block=$(cat <<INSERT
$MARKER_BEGIN
# L0 Identity (core protocol, ~80 tokens):
$l0_content

# L1 Facts (AAAK compressed, ~200 tokens):
$l1_content

$MARKER_END
INSERT
)

    # Insert after system_prompt or before first tool section
    if grep -q "^system_prompt:" "$CONFIG"; then
        # Insert after system_prompt: line
        awk -v marker_begin="$MARKER_BEGIN" -v marker_end="$MARKER_END" -v block="$block" '
        /^system_prompt:/ { print; print block; next }
        { print }
        ' "$CONFIG" > "${CONFIG}.tmp" && mv "${CONFIG}.tmp" "$CONFIG"
    else
        # Append to end
        echo "" >> "$CONFIG"
        echo "$block" >> "$CONFIG"
    fi

    echo "✅ L0+L1 memory layers enabled in config.yaml"
    echo "   L0: $L0_FILE"
    echo "   L1: $L1_FILE"
    echo ""
    echo "ℹ️  Original MEMORY.md is untouched at: $HERMES_DIR/memories/MEMORY.md"
}

cmd_disable() {
    local status
    status=$(get_marker_status)
    if [ "$status" = "disabled" ]; then
        echo "ℹ️  L0+L1 layers already disabled"
        return 0
    fi

    # Remove block between markers (inclusive)
    sed -i "/$MARKER_BEGIN/,/$MARKER_END/d" "$CONFIG"

    echo "✅ L0+L1 memory layers removed from config.yaml"
    echo "ℹ️  Original MEMORY.md will be used again"
}

cmd_status() {
    local status
    status=$(get_marker_status)
    echo "L0+L1 Memory Layers status: $status"
    if [ "$status" = "enabled" ]; then
        echo ""
        echo "L0 file: $L0_FILE ($(wc -c < "$L0_FILE") bytes)"
        echo "L1 file: $L1_FILE ($(wc -c < "$L1_FILE") bytes)"
        echo ""
        echo "L0 content:"
        cat "$L0_FILE"
        echo ""
        echo "---"
        echo "L1 content:"
        cat "$L1_FILE"
    fi
    echo ""
    echo "Original files (always preserved):"
    echo "  $HERMES_DIR/memories/MEMORY.md"
    echo "  $HERMES_DIR/memories/USER.md"
}

case "${1:-status}" in
    enable)
        cmd_enable
        ;;
    disable)
        cmd_disable
        ;;
    status)
        cmd_status
        ;;
    *)
        echo "Usage: $0 {enable|disable|status}"
        exit 1
        ;;
esac
