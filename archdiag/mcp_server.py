"""Minimal MCP (Model Context Protocol) server over stdio, no dependencies.

Lets Claude Desktop / Cursor / any MCP client call archdiag as a tool:

    {"mcpServers": {"archdiag": {"command": "python", "args": ["-m", "archdiag.mcp_server"],
                                 "cwd": "/path/to/repo"}}}

Tools: check_diagram(text) and render_diagram(text, out_path, direction?, theme?).
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import archdiag  # noqa: E402

TOOLS = [
    {"name": "check_diagram",
     "description": "检查架构图/流程图描述（mermaid 子集或 JSON）的语法，返回可直接改正的中文错误提示。",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "render_diagram",
     "description": "把架构图/流程图描述（mermaid 子集或 JSON）渲染成 PPTX / SVG / PNG 文件，自动排版并画好箭头。",
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string"},
         "out_path": {"type": "string", "description": "输出路径，扩展名决定格式：.pptx / .svg / .png"},
         "direction": {"type": "string", "enum": ["TB", "LR", "auto"]},
         "theme": {"type": "string", "enum": sorted(archdiag.THEMES)}},
         "required": ["text", "out_path"]}},
]


def handle(req: dict):
    method, params = req.get("method"), req.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "archdiag", "version": archdiag.__version__}}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            if name == "check_diagram":
                issues = archdiag.check(args["text"])
                text = "\n".join(str(i) for i in issues) or "OK: 没有发现问题"
            elif name == "render_diagram":
                g = archdiag.render(args["text"], args["out_path"], theme=args.get("theme"),
                                    direction=args.get("direction", "auto"))
                warn = "\n".join(str(i) for i in g.warnings)
                text = f"已生成 {args['out_path']}（{len(g.nodes)} 个节点，{len(g.edges)} 条边）" + ("\n" + warn if warn else "")
            else:
                return {"content": [{"type": "text", "text": f"未知工具 {name}"}], "isError": True}
            return {"content": [{"type": "text", "text": text}]}
        except Exception as e:  # noqa: BLE001
            return {"content": [{"type": "text", "text": f"失败: {e}"}], "isError": True}
    if method in ("notifications/initialized", "ping"):
        return {}
    return None


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = handle(req)
        if "id" not in req:
            continue
        resp = {"jsonrpc": "2.0", "id": req["id"]}
        if result is None:
            resp["error"] = {"code": -32601, "message": f"method not found: {req.get('method')}"}
        else:
            resp["result"] = result
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
