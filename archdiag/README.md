# archdiag — 让小参数 LLM 也能画对系统架构图

> 问题：LLM 直接写 python-pptx / 画坐标时，框摆不齐、箭头乱飞、连接点错位。
> 解法：**模型只说"有什么、谁连谁"，位置和箭头全部由程序算。**

模型输出它本来就熟悉的 Mermaid 子集（或一段 JSON），`archdiag` 负责：

- 分层布局（谁在上、谁在下）、减少交叉、同一列对齐到网格
- 分组（subgraph）变成真正的方框，嵌套、绝不圈进别人的节点
- 箭头全部正交走线：从框的边缘出发、进入目标边缘、多条线自动错开、不穿过任何框
- 输出 **PPTX**（真实形状和连线，可继续在 PowerPoint 里编辑）、**SVG**、**PNG**
- 语法错了给出中文提示，喂回模型即可自我修正

## 安装

```bash
pip install python-pptx        # 唯一的第三方依赖（PNG 输出可选装 cairosvg）
```

在仓库根目录直接用 `python -m archdiag`，或把 `archdiag/` 目录拷到你的项目里。

## 用法

### 命令行

```bash
python -m archdiag archdiag/examples/web_arch.mmd -o web.pptx            # 生成 PPT
python -m archdiag diagram.mmd -o a.svg -o a.png --dir auto --theme gray   # 多种输出，自动选横/竖
python -m archdiag diagram.mmd --check                                     # 只检查语法，结果可直接喂回模型
echo 'graph LR; A[Web] --> B[API] --> C[(DB)]' | python -m archdiag - -o x.pptx
```

### Python

```python
import archdiag

text = """
graph TD
  user([用户]) --> gw(API 网关)
  subgraph 后端
    gw --> order[订单服务] & pay[支付服务]
  end
  order --> db[(MySQL)]
"""
archdiag.render(text, "arch.pptx", direction="auto")   # .pptx / .svg / .png / .json 按扩展名

# 放进你自己正在生成的 PPT 里（和 python-pptx 一起用）
from pptx import Presentation
from pptx.util import Inches
prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[6])
archdiag.add_to_slide(slide, text, Inches(0.5), Inches(1), Inches(9), Inches(5.5))
prs.save("deck.pptx")

# 先检查再渲染（给模型的自纠错循环）
for issue in archdiag.check(text):
    print(issue)          # [错误] 第 3 行: '[' 没有对应的 ']' 闭合 ...
```

### 给模型的提示词 / 工具定义

- `PROMPT.md`：直接可用的 system prompt（含示例与自纠错流程）
- `tool_schema.json`：Function Calling 用的 JSON Schema，模型只填 nodes / edges
- `examples/llm_loop.py`：接 Ollama / vLLM 等 OpenAI 兼容接口的完整循环：生成 → 检查 → 让模型改 → 渲染
- `mcp_server.py`：零依赖的 MCP 服务器，Claude Desktop / Cursor 可直接把它当工具调用

## 输入格式速查（Mermaid 子集，很宽容）

```
title: 标题                       可选，也支持 --- title: x --- 头部
graph TD | LR                     上下 / 左右（也接受 TB、BT、RL；缺省 TD）
A[矩形]  B(圆角)  C([胶囊])  D[(数据库)]  E{菱形}  F{{六边形}}  G((圆))  H[[子程序]]
A --> B           A -->|文字| B        A -- 文字 --> B
A -.-> B 虚线     A ==> B 粗线        A <--> B 双向      A --- B 无箭头
A --> B & C       A --> B --> C        A -> B: 文字       A → B      （以上都能识别）
subgraph 分组名 ... end            可嵌套
%% 注释、style/classDef/linkStyle 会被忽略，```mermaid 围栏可带可不带
```

也接受 JSON：`{"direction":"TB","nodes":[{"id":"a","label":"A","shape":"cylinder","group":"数据层"}],"edges":[{"from":"a","to":"b","label":"x"}]}`。

## 它是怎么保证箭头画对的

1. **分层**：按连线方向拓扑分层（有环时自动反转回边），孤立/源节点贴近它的邻居，同组的末端节点对齐到同一行，分组框因此紧凑。
2. **排序**：重心法多轮扫描减少交叉，同组节点保持相邻。
3. **分组带（band）**：每个分组在父级里独占一段横向区间，子节点行在区间内居中并向邻居靠拢，并吸附到半列网格，所以同一条链上的框严格对齐。
4. **走线**：边从底边出、顶边入（向上的边反之，同行相邻的边走左右边）；每个框每条边上的多个出入口自动分散；跨多层的边在列与列之间的空廊道里竖直通过，并绕开它不属于的分组框；同一通道里的平行线错开到不同轨道。
5. **输出**：PPTX 里两点直线用 connector，折线用 freeform 多段线并写入箭头端点 — 坐标显式给出，不依赖 PowerPoint 的 flip/rotate 语义（LLM 最常出错的地方）。

`tests/` 里用 300 个随机图校验这些不变量：框不重叠、分组只包含自己的成员、每条边都正交且端点落在框边缘、不穿过任何框。

```bash
python -m pytest archdiag/tests -q
```

## 已知限制

- 节点统一尺寸（这是刻意的，架构图整齐优先）；超长文字自动换行，建议模型用 `<br>` 控制。
- 不做曲线、不做斜线；同行之间非相邻的边会从上方通道绕行。
- `style` / 颜色类指令被忽略，颜色由 `--theme`（blue / gray / green / warm / dark）统一控制。
- 超过 ~40 个节点会提示拆图；一页 PPT 本来也放不下。
