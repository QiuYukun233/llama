"""Tolerant parser for a Mermaid-flowchart subset (plus a JSON form).

Design goal: a small LLM should be able to produce valid input with almost
no effort, so the parser accepts many sloppy variants (``->``, ``→``,
Chinese IDs, missing ``graph TD`` header, code fences, ``A -> B: label`` …)
and reports problems in plain language that can be fed straight back to the
model for self-correction.
"""
from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from .model import Edge, Graph, Group, Issue, Node


class ParseError(Exception):
    pass


# ---------------------------------------------------------------------------
# Shapes: (opener, [closers], shape name) -- longest openers first.
# ---------------------------------------------------------------------------
SHAPE_SYNTAX = [
    ("([", ["])"], "stadium"),
    ("[(", [")]"], "cylinder"),
    ("[[", ["]]"], "subroutine"),
    ("[/", ["/]", "\\]"], "parallelogram"),
    ("[\\", ["\\]", "/]"], "parallelogram"),
    ("{{", ["}}"], "hexagon"),
    ("((", ["))"], "circle"),
    ("(", [")"], "round"),
    ("[", ["]"], "rect"),
    ("{", ["}"], "diamond"),
    (">", ["]"], "flag"),
]
SHAPE_OPEN_CHARS = "[({>"

# Arrow syntax.  Validity rules are checked in `match_arrow` because a lone
# "-" or "=" must *not* be treated as an arrow (they appear inside IDs).
_ARROW_RE = re.compile(
    r"(?P<tail><)?(?:"
    r"(?P<thick>=+)(?P<thick_head>>)?"
    r"|(?P<dashed>-\.+-?)(?P<dashed_head>>)?"
    r"|(?P<solid>-+)(?P<solid_head>>)?"
    r"|(?P<uni>[→⟶⇒⇨➔➜➝➞⇾])"
    r"|(?P<uni_bi>[↔⇔])"
    r"|(?P<uni_left>[←⟵⇐])"
    r")"
)

# "A -- text --> B"  →  "A -->|text| B"
_INLINE_TEXT_RE = re.compile(
    r"(?<![-=.])(--|-\.|==)\s+([^-=<>|\[\]{}()]+?)\s+(-->|---|->|\.->|\.-|==>|===|=>)"
)
# "A --> B: text"  →  "A -->|text| B"
_COLON_LABEL_RE = re.compile(
    r"^(.*(?:-+>|=+>|\.->|[→⇒↔]))\s*([^\s\[\]{}()|:：]+)\s*[:：]\s*([^\[\]{}()|]+?)\s*$"
)

_IGNORED_PREFIXES = (
    "style ", "classdef ", "class ", "linkstyle ", "click ", "direction ",
    "acctitle", "accdescr",
)
_HEADER_RE = re.compile(r"^(graph|flowchart)\b\s*(TD|TB|LR|RL|BT)?\s*;?\s*(.*)$", re.I)
_SUBGRAPH_RE = re.compile(r"^subgraph\b\s*(.*)$", re.I)
_TITLE_RE = re.compile(r"^title\s*[:：]?\s*(.+)$", re.I)

FULLWIDTH_MAP = str.maketrans({
    "－": "-", "＞": ">", "＜": "<", "｜": "|", "＆": "&", "；": ";",
    "　": " ",
})


def _clean_label(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    s = s.replace("#quot;", '"').replace("&quot;", '"')
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = s.replace("\\n", "\n")
    s = re.sub(r"</?[a-zA-Z][^>]*>", "", s)       # strip stray html tags
    return s.strip()


def match_arrow(s: str, pos: int) -> Optional[Tuple[int, dict]]:
    """Try to read an arrow at `pos`; return (end_pos, props) or None."""
    m = _ARROW_RE.match(s, pos)
    if not m:
        return None
    tail = bool(m.group("tail"))
    props = {"style": "solid", "head": True, "tail": False, "reverse": False}
    if m.group("thick") is not None:
        n, head = len(m.group("thick")), bool(m.group("thick_head"))
        if not head and n < 2:
            return None
        if head and n < 1:
            return None
        props.update(style="thick", head=head)
    elif m.group("dashed") is not None:
        head = bool(m.group("dashed_head"))
        if not head and not m.group("dashed").endswith("-"):
            return None
        props.update(style="dashed", head=head)
    elif m.group("solid") is not None:
        n, head = len(m.group("solid")), bool(m.group("solid_head"))
        if not head and n < 2:
            return None          # a single "-" inside an id, not an arrow
        props.update(head=head)
    elif m.group("uni") is not None:
        pass
    elif m.group("uni_bi") is not None:
        props.update(tail=True)
    elif m.group("uni_left") is not None:
        props.update(reverse=True)
    if tail:
        if props["head"]:
            props["tail"] = True          # <-->
        else:
            props.update(head=True, reverse=True)   # <--  (points left)
    return m.end(), props


def _parse_shape(s: str, i: int) -> Tuple[str, str, int]:
    """Parse ``[label]``-style shape starting at s[i]; return (label, shape, end)."""
    for opener, closers, shape in SHAPE_SYNTAX:
        if s.startswith(opener, i):
            j = i + len(opener)
            # quoted labels may contain brackets
            if j < len(s) and s[j] == '"':
                k = s.find('"', j + 1)
                if k < 0:
                    raise ParseError("引号没有闭合 (unclosed quote)")
                for c in closers:
                    if s.startswith(c, k + 1):
                        return _clean_label(s[j:k + 1]), shape, k + 1 + len(c)
                raise ParseError(f"节点文字后面缺少 '{closers[0]}' (missing closing bracket)")
            best = None
            for c in closers:
                k = s.find(c, j)
                if k >= 0 and (best is None or k < best[0]):
                    best = (k, c)
            if best is None:
                raise ParseError(
                    f"'{opener}' 没有对应的 '{closers[0]}' 闭合 (unclosed bracket)")
            k, c = best
            return _clean_label(s[j:k]), shape, k + len(c)
    raise ParseError(f"无法识别的符号 '{s[i]}' (unexpected character)")


def tokenize(stmt: str) -> List[tuple]:
    """Split one statement into node / arrow / '&' tokens."""
    tokens: List[tuple] = []
    i, n = 0, len(stmt)
    while i < n:
        c = stmt[i]
        if c.isspace():
            i += 1
            continue
        if c == "&":
            tokens.append(("amp",))
            i += 1
            continue
        if c == "|":
            raise ParseError("边上的文字应紧跟在箭头后面，如 A -->|文字| B (misplaced '|')")
        arrow = match_arrow(stmt, i)
        if arrow:
            end, props = arrow
            j = end
            while j < n and stmt[j].isspace():
                j += 1
            if j < n and stmt[j] == "|":
                k = stmt.find("|", j + 1)
                if k < 0:
                    raise ParseError("边上的文字 |...| 没有闭合 (unclosed edge label)")
                props["label"] = _clean_label(stmt[j + 1:k])
                end = k + 1
            tokens.append(("arrow", props))
            i = end
            continue
        if c == '"':
            k = stmt.find('"', i + 1)
            if k < 0:
                raise ParseError("引号没有闭合 (unclosed quote)")
            label = _clean_label(stmt[i + 1:k])
            tokens.append(("node", label, label, "rect", True))
            i = k + 1
            continue
        if c in SHAPE_OPEN_CHARS:
            raise ParseError(
                f"'{c}' 前面缺少节点 ID，应写成 ID{c}文字...  (shape bracket without node id)")
        j = i
        while (j < n and not stmt[j].isspace() and stmt[j] not in "&|"
               and stmt[j] not in SHAPE_OPEN_CHARS and not match_arrow(stmt, j)):
            j += 1
        if j == i:
            raise ParseError(f"无法识别的符号 '{stmt[i]}' (unexpected character)")
        nid = stmt[i:j]
        i = j
        if i < n and stmt[i] in SHAPE_OPEN_CHARS:
            label, shape, i = _parse_shape(stmt, i)
            tokens.append(("node", nid, label, shape, True))
        else:
            tokens.append(("node", nid, None, None, False))
    return tokens


def _split_statements(line: str) -> List[str]:
    """Split on ';' outside of quotes/brackets."""
    out, buf, depth, quote = [], [], 0, False
    for ch in line:
        if ch == '"':
            quote = not quote
        elif not quote and ch in "[({":
            depth += 1
        elif not quote and ch in "])}":
            depth = max(0, depth - 1)
        if ch == ";" and depth == 0 and not quote:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [s for s in (x.strip() for x in out) if s]


def _strip_comment(line: str) -> str:
    quote = False
    for i, ch in enumerate(line):
        if ch == '"':
            quote = not quote
        elif not quote and line.startswith("%%", i):
            return line[:i]
    return line


def _preprocess(text: str) -> List[Tuple[int, str]]:
    """Remove fences / frontmatter, normalise full-width symbols.

    Returns (line_no, text) pairs keeping original line numbers.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: List[Tuple[int, str]] = []
    in_front, front_done = False, False
    for idx, raw in enumerate(lines, 1):
        line = raw.translate(FULLWIDTH_MAP)
        stripped = line.strip()
        if stripped.startswith("```"):
            continue
        if stripped == "---" and not front_done and (in_front or not out):
            in_front = not in_front
            if not in_front:
                front_done = True
            continue
        if in_front:
            m = _TITLE_RE.match(stripped)
            if m:
                out.append((idx, "title: " + m.group(1)))
            continue
        line = _strip_comment(line)
        if line.strip():
            out.append((idx, line))
    return out


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def parse(text: str) -> Graph:
    text = text.strip()
    if text.startswith("{"):
        return parse_json(text)
    g = Graph()
    counter = {"n": 0}
    stack: List[str] = []          # open subgraphs
    group_counter = {"n": 0}

    def issue(level, msg, line_no=0, line=""):
        g.issues.append(Issue(level, msg, line_no, line))

    def ensure_node(nid, label=None, shape=None, defined=False, line_no=0):
        nid = nid.strip()
        node = g.nodes.get(nid)
        if node is None:
            node = Node(id=nid, label=label if label is not None else nid,
                        shape=shape or "rect", order=counter["n"])
            counter["n"] += 1
            g.nodes[nid] = node
        elif defined:
            if label is not None:
                node.label = label
            if shape:
                node.shape = shape
        if stack:
            current = stack[-1]
            # adopt the node if it is not yet in a group, or if the current
            # subgraph is nested deeper than its current group
            if node.group is None or current in g.ancestors(node.group) and current != node.group:
                pass
            if node.group is None or node.group in g.ancestors(current):
                node.group = current
        return node

    def add_edge(a, b, props, line_no, line):
        if props.get("reverse"):
            a, b = b, a
        if a == b:
            issue("warning", f"节点 '{a}' 指向自己的边已忽略 (self-loop ignored)", line_no, line)
            return
        for e in g.edges:
            if e.src == a and e.dst == b and e.label == props.get("label", ""):
                issue("warning", f"重复的边 {a} -> {b} 已合并 (duplicate edge)", line_no, line)
                return
        g.edges.append(Edge(src=a, dst=b, label=props.get("label", ""),
                            style=props["style"], head=props["head"],
                            tail=props["tail"], line_no=line_no))

    def handle_statement(stmt, line_no, line):
        low = stmt.lower()
        m = _HEADER_RE.match(stmt)
        if m:
            d = (m.group(2) or "TB").upper()
            g.direction = "TB" if d == "TD" else d
            rest = m.group(3).strip()
            if rest:
                handle_statement(rest, line_no, line)
            return
        m = _TITLE_RE.match(stmt)
        if m and not match_arrow(stmt, 0) and "-->" not in stmt and "->" not in stmt:
            g.title = _clean_label(m.group(1))
            return
        if low == "end":
            if not stack:
                issue("error", "多余的 end：前面没有对应的 subgraph (unmatched end)", line_no, line)
            else:
                stack.pop()
            return
        m = _SUBGRAPH_RE.match(stmt)
        if m:
            spec = m.group(1).strip()
            gid, label = None, None
            if spec:
                k = next((i for i, ch in enumerate(spec) if ch in SHAPE_OPEN_CHARS), -1)
                if k > 0:
                    gid = spec[:k].strip()
                    try:
                        label, _, _ = _parse_shape(spec, k)
                    except ParseError as e:
                        issue("error", str(e), line_no, line)
                        label = spec[k + 1:].strip("[]() \"")
                else:
                    label = _clean_label(spec)
                    gid = label
            if not spec:
                group_counter["n"] += 1
                gid = label = f"组{group_counter['n']}"
                issue("warning", "subgraph 没有名字，已自动命名 (unnamed subgraph)", line_no, line)
            if gid in g.groups:
                base = gid
                k = 2
                while gid in g.groups:
                    gid = f"{base}_{k}"
                    k += 1
            if gid in g.nodes:
                issue("error", f"'{gid}' 既是节点又是 subgraph 名字，请改名 (id used for node and subgraph)", line_no, line)
            parent = stack[-1] if stack else None
            g.groups[gid] = Group(id=gid, label=label or gid, parent=parent, order=len(g.groups))
            stack.append(gid)
            return
        if any(low.startswith(p) for p in _IGNORED_PREFIXES):
            return
        # --- normalise sugar ---
        stmt = _INLINE_TEXT_RE.sub(
            lambda mm: {"--": mm.group(3) if mm.group(3) not in ("->",) else "-->",
                        "-.": "-" + mm.group(3) if mm.group(3).startswith(".") else "-.->",
                        "==": mm.group(3) if mm.group(3) not in ("=>",) else "==>"}[mm.group(1)]
            + "|" + mm.group(2).strip() + "|", stmt)
        mc = _COLON_LABEL_RE.match(stmt)
        if mc and "|" not in stmt:
            stmt = f"{mc.group(1).rstrip()}|{mc.group(3).strip()}| {mc.group(2)}"
        try:
            tokens = tokenize(stmt)
        except ParseError as e:
            issue("error", str(e), line_no, line)
            return
        if not tokens:
            return
        # grammar: group (arrow group)*   where group = node (& node)*
        groups: List[List[str]] = []
        arrows: List[dict] = []
        cur: List[str] = []
        expect_node = True
        for tok in tokens:
            if tok[0] == "node":
                if not expect_node:
                    issue("error",
                          f"节点 '{tok[1]}' 前面缺少箭头，节点之间请用 --> 连接，ID 里不要有空格 (missing arrow between nodes)",
                          line_no, line)
                    return
                _, nid, label, shape, defined = tok
                ensure_node(nid, label, shape, defined, line_no)
                cur.append(nid.strip())
                expect_node = False
            elif tok[0] == "amp":
                if expect_node:
                    issue("error", "'&' 两边都要有节点 (dangling &)", line_no, line)
                    return
                expect_node = True
            else:
                if expect_node:
                    issue("error", "箭头前面缺少节点 (arrow without source node)", line_no, line)
                    return
                groups.append(cur)
                cur = []
                arrows.append(tok[1])
                expect_node = True
        if expect_node:
            issue("error", "这一行以箭头或 & 结尾，后面缺少目标节点 (arrow without target node)", line_no, line)
            return
        groups.append(cur)
        for k, props in enumerate(arrows):
            for a in groups[k]:
                for b in groups[k + 1]:
                    add_edge(a, b, props, line_no, line)

    for line_no, line in _preprocess(text):
        for stmt in _split_statements(line):
            handle_statement(stmt, line_no, line)

    if stack:
        issue("error", f"subgraph '{stack[-1]}' 没有用 end 结束 (subgraph not closed)")
    _post_validate(g)
    return g


def parse_json(text: str) -> Graph:
    """JSON form, convenient for function-calling APIs::

        {"direction": "TB", "title": "...",
         "nodes": [{"id": "web", "label": "Web", "shape": "rect", "group": "前端"}, "db"],
         "edges": [{"from": "web", "to": "api", "label": "HTTPS"}, "api -> db"],
         "groups": [{"id": "前端", "label": "前端层", "members": ["web"], "parent": null}]}
    """
    g = Graph()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        g.issues.append(Issue("error", f"JSON 无法解析: {e.msg} (invalid JSON)", e.lineno))
        return g
    d = str(data.get("direction", "TB")).upper()
    g.direction = "TB" if d == "TD" else d if d in ("TB", "LR", "RL", "BT") else "TB"
    g.title = str(data.get("title", "") or "")

    def add_group(spec, parent=None):
        if isinstance(spec, str):
            spec = {"id": spec}
        gid = str(spec.get("id") or spec.get("label") or f"组{len(g.groups) + 1}")
        g.groups[gid] = Group(id=gid, label=str(spec.get("label", gid)), parent=parent, order=len(g.groups))
        for m in spec.get("members", []) or []:
            mid = m if isinstance(m, str) else str(m.get("id"))
            if mid not in g.nodes:
                add_node(m)
            g.nodes[mid].group = gid
        for sub in spec.get("groups", []) or []:
            add_group(sub, gid)

    def add_node(spec):
        if isinstance(spec, str):
            spec = {"id": spec}
        nid = str(spec.get("id") or spec.get("label"))
        if not nid:
            g.issues.append(Issue("error", "节点缺少 id (node without id)"))
            return
        if nid not in g.nodes:
            g.nodes[nid] = Node(id=nid, label=str(spec.get("label", nid)),
                                shape=spec.get("shape", "rect") or "rect", order=len(g.nodes))
        n = g.nodes[nid]
        if spec.get("label"):
            n.label = str(spec["label"])
        if spec.get("shape"):
            n.shape = spec["shape"]
        if spec.get("group"):
            gid = str(spec["group"])
            if gid not in g.groups:
                g.groups[gid] = Group(id=gid, label=gid, order=len(g.groups))
            n.group = gid

    nodes = data.get("nodes", [])
    if isinstance(nodes, dict):
        nodes = [dict(v, id=k) if isinstance(v, dict) else {"id": k, "label": v} for k, v in nodes.items()]
    for spec in nodes:
        add_node(spec)
    for spec in data.get("groups", []) or []:
        add_group(spec)
    for spec in data.get("edges", []) or []:
        if isinstance(spec, str):
            sub = parse("graph TB\n" + spec)
            g.issues.extend(sub.issues)
            for nid, n in sub.nodes.items():
                if nid not in g.nodes:
                    g.nodes[nid] = Node(id=nid, label=n.label, shape=n.shape, order=len(g.nodes))
            g.edges.extend(sub.edges)
            continue
        if isinstance(spec, (list, tuple)):
            spec = {"from": spec[0], "to": spec[1], "label": spec[2] if len(spec) > 2 else ""}
        a = str(spec.get("from") or spec.get("source") or spec.get("src") or "")
        b = str(spec.get("to") or spec.get("target") or spec.get("dst") or "")
        if not a or not b:
            g.issues.append(Issue("error", f"边缺少 from/to: {spec} (edge without endpoints)"))
            continue
        for nid in (a, b):
            if nid not in g.nodes:
                g.nodes[nid] = Node(id=nid, label=nid, order=len(g.nodes))
        if a == b:
            g.issues.append(Issue("warning", f"节点 '{a}' 指向自己的边已忽略 (self-loop ignored)"))
            continue
        g.edges.append(Edge(src=a, dst=b, label=str(spec.get("label", "") or ""),
                            style=spec.get("style", "solid") or "solid",
                            head=spec.get("head", True),
                            tail=bool(spec.get("bidirectional") or spec.get("tail"))))
    _post_validate(g)
    return g


def _post_validate(g: Graph) -> None:
    if not g.nodes:
        if not g.errors:
            g.issues.append(Issue("error", "没有找到任何节点，请至少写一行 A --> B (empty diagram)"))
        return
    for n in g.nodes.values():
        if n.shape not in ("rect", "round", "stadium", "cylinder", "diamond", "hexagon",
                           "circle", "subroutine", "parallelogram", "flag"):
            g.issues.append(Issue("warning", f"节点 '{n.id}' 的形状 '{n.shape}' 未知，按矩形处理"))
            n.shape = "rect"
        if n.group is not None and n.group not in g.groups:
            g.groups[n.group] = Group(id=n.group, label=n.group, order=len(g.groups))
        longest = max((len(x) for x in n.label.split("\n")), default=0)
        if longest > 24:
            g.issues.append(Issue(
                "warning", f"节点 '{n.id}' 的文字较长，会自动换行；可用 <br> 手动分行 (long label)"))
    # group cycles
    for gid in g.groups:
        seen = set()
        cur = gid
        while cur is not None:
            if cur in seen:
                g.issues.append(Issue("error", f"subgraph '{gid}' 的嵌套形成了循环 (group nesting cycle)"))
                g.groups[gid].parent = None
                break
            seen.add(cur)
            cur = g.groups[cur].parent if cur in g.groups else None
    connected = {e.src for e in g.edges} | {e.dst for e in g.edges}
    lonely = [n.id for n in g.nodes.values() if n.id not in connected]
    if lonely and g.edges:
        g.issues.append(Issue("warning", f"节点 {', '.join(lonely[:6])} 没有任何连线 (isolated nodes)"))
    if len(g.nodes) > 40:
        g.issues.append(Issue("warning", f"节点有 {len(g.nodes)} 个，一页 PPT 会很拥挤，建议拆成多张图 (too many nodes)"))
