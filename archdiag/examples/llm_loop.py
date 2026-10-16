"""End-to-end demo: a small local model writes the diagram, archdiag checks and renders it.

Works with any OpenAI-compatible chat endpoint (Ollama, vLLM, LM Studio, llama.cpp server ...):

    ollama run qwen2.5:7b          # for example
    python archdiag/examples/llm_loop.py "画一个短视频平台的推荐系统架构图" -o rec.pptx

Environment variables: LLM_BASE_URL (default http://localhost:11434/v1), LLM_MODEL (default qwen2.5:7b), LLM_API_KEY.
"""
import argparse
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import archdiag  # noqa: E402

HERE = os.path.dirname(__file__)
SYSTEM_PROMPT = re.search(r"```text\n(.*?)\n```\n\n---", open(os.path.join(HERE, "..", "PROMPT.md"), encoding="utf-8").read(),
                          re.S).group(1)


def chat(messages):
    base = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = json.dumps({"model": os.environ.get("LLM_MODEL", "qwen2.5:7b"), "messages": messages,
                       "temperature": 0.2}).encode()
    req = urllib.request.Request(base + "/chat/completions", data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ.get("LLM_API_KEY", "none")})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def extract_block(text):
    m = re.search(r"```(?:mermaid)?\s*\n(.*?)```", text, re.S)
    return m.group(1) if m else text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("request", help="用自然语言描述想画什么")
    ap.add_argument("-o", "--out", default="diagram.pptx")
    ap.add_argument("--retries", type=int, default=3)
    args = ap.parse_args()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": args.request}]
    for attempt in range(args.retries + 1):
        reply = chat(messages)
        src = extract_block(reply)
        issues = archdiag.check(src)
        errors = [i for i in issues if i.level == "error"]
        print(f"--- 第 {attempt + 1} 次输出 ---\n{src}\n", file=sys.stderr)
        for i in issues:
            print(i, file=sys.stderr)
        if not errors:
            archdiag.render(src, args.out, direction="auto")
            print(f"已生成 {args.out}")
            return 0
        messages += [{"role": "assistant", "content": reply},
                     {"role": "user", "content": "程序检查报错如下，请只修正错误并重新输出完整的 mermaid 代码块，不要解释：\n"
                                                + "\n".join(str(i) for i in errors)}]
    print("多次修正仍有错误，放弃。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
