"""Markdown 后处理：对 docling 输出的扁平 md 做结构化增强。

docling 对无 Word 样式的 docx（如手写接口文档）只能输出扁平段落 md，
标题层级与代码块结构丢失。此处按接口文档常见模式补结构：

- 「N、xxx」编号行 → 二级标题
- 被逐行打散的 JSON / 对象块 → ```json 代码块（去除段间空行）

安全约束：
- 已在 ``` 围栏内的内容跳过，不破坏 docling 已结构化的 md
- 未闭合的对象块放弃处理，原样返回
- 仅作用于 docling 二进制路径（见 doc_upload_service._extract_binary）
"""

import re

_HEADING_RE = re.compile(r"^(\d+)、\s*(.+)$")
_FENCE_RE = re.compile(r"^\s*```")
_JSON_OPENERS = ("{", "[")


def enrich_markdown(text: str) -> str:
    """对扁平 md 补结构。空串原样返回。"""
    if not text:
        return text

    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    i = 0
    n = len(lines)

    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            out.append(raw)
            i += 1
            continue
        if in_fence:
            out.append(raw)
            i += 1
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            out.append(f"## {heading.group(1)}. {heading.group(2).strip()}")
            i += 1
            continue

        if stripped and stripped[0] in _JSON_OPENERS:
            block, next_i = _collect_json_block(lines, i)
            if block is not None:
                out.append("```json")
                out.extend(block)
                out.append("```")
                i = next_i
                continue

        out.append(raw)
        i += 1

    return "\n".join(out)


def _collect_json_block(lines: list[str], start: int) -> tuple[list[str] | None, int]:
    """从 start 行（{ 或 [ 开头）收集到括号平衡闭合，跳过空行。

    返回 (去空行后的行列表, 下一行索引)；未闭合返回 (None, start)。
    """
    block: list[str] = []
    depth = 0
    i = start
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        block.append(s)
        depth += s.count("{") + s.count("[")
        depth -= s.count("}") + s.count("]")
        if depth <= 0:
            return block, i + 1
        i += 1
    return None, start
