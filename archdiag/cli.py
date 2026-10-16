"""Command line: python -m archdiag INPUT -o OUT.pptx [--check] [--svg ...]"""
from __future__ import annotations

import argparse
import sys

from . import THEMES, check, render, __version__


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="archdiag",
        description="把 Mermaid 风格的框图描述渲染成 PPTX / SVG / PNG，箭头与布局由程序自动完成。")
    ap.add_argument("input", help="输入文件（.mmd / .txt / .json），用 - 表示从标准输入读取")
    ap.add_argument("-o", "--out", action="append", default=[],
                    help="输出文件，可多次给出（按扩展名决定格式：pptx / svg / png / json）")
    ap.add_argument("--check", action="store_true", help="只检查语法，不渲染；错误以文字返回，便于喂回给模型")
    ap.add_argument("--dir", choices=["TB", "TD", "LR", "RL", "BT", "auto"],
                    help="覆盖图中的方向；auto 会在 TB/LR 里选更适合 16:9 页面的一个")
    ap.add_argument("--theme", choices=sorted(THEMES), default="blue")
    ap.add_argument("--font", help="PPTX 中使用的字体名，如 '微软雅黑'")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    text = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    issues = check(text)
    for i in issues:
        print(i, file=sys.stderr)
    errors = [i for i in issues if i.level == "error"]
    if args.check:
        print("OK: 语法检查通过" if not errors else f"FAIL: {len(errors)} 个错误", file=sys.stderr)
        return 1 if errors else 0
    if errors:
        print(f"有 {len(errors)} 个错误，未渲染。请按提示修改后重试。", file=sys.stderr)
        return 1
    outs = args.out or [(args.input.rsplit(".", 1)[0] if args.input != "-" else "diagram") + ".pptx"]
    for out in outs:
        kw = {"font_name": args.font} if (args.font and out.lower().endswith(".pptx")) else {}
        render(text, out, theme=args.theme, direction=args.dir, **kw)
        print(f"已生成 {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
