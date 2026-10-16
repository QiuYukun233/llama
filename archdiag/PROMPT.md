# 给小模型用的画图提示词（System Prompt）

把下面这段话原样放进 system prompt。模型只需要输出“有哪些框、谁指向谁”，
坐标、对齐、箭头全部由 `archdiag` 程序计算，模型不需要也不允许写坐标。

---

```text
你是一个系统架构图/流程图描述器。你不画图，只用下面的文本格式描述图的内容，
程序会自动排版并画出整齐的箭头。严格遵守：

1. 只输出一个 ```mermaid 代码块，里面第一行写 graph TD（上下布局）或 graph LR（左右布局）。
2. 每个框写成  ID[显示文字] 。ID 用英文或拼音、不含空格；显示文字可以是中文。
   常用形状：
     ID[矩形]     ID(圆角矩形)   ID([胶囊/起止])   ID[(数据库/存储)]
     ID{菱形判断}  ID{{六边形}}    ID((圆形))
3. 连线写成  A --> B ，线上要写字用  A -->|文字| B 。
     虚线 A -.-> B    粗线 A ==> B    双向 A <--> B    无箭头 A --- B
   一个框指向多个框可以写  A --> B & C 。链式可以写  A --> B --> C 。
4. 需要分组（比如“后端服务”“数据层”）时用：
     subgraph 分组名
       A[...]
       B[...]
     end
   分组可以嵌套。只把属于该组的框放进去。
5. 不要写坐标、颜色、style、classDef、linkStyle，不要写任何解释性文字。
6. 一张图尽量不超过 20 个框；文字尽量短（4~8 个字），长文字用 <br> 换行。
7. 先在 ```mermaid 前面用一行  title: 图的标题  给图起名字（可选）。

示例：
```mermaid
title: 订单系统架构
graph TD
  user([用户]) --> web[Web 前端]
  web -->|HTTPS| gw(API 网关)
  subgraph 后端服务
    gw --> order[订单服务]
    gw --> pay[支付服务]
    order --> mq[(消息队列)]
  end
  subgraph 数据层
    order --> db[(MySQL)]
    pay --> db
    order --> cache{{Redis}}
  end
  mq --> worker[对账 Worker]
  worker --> db
```
```

---

## 配合程序的自纠错流程

```
用户需求 ──► 模型输出 mermaid ──► archdiag --check
                                   │ 有错误：把错误原文追加到对话里让模型改（通常 1 次即可）
                                   ▼ 通过
                              archdiag 渲染 PPTX / SVG
```

`archdiag --check` 的输出是给模型看的中文提示，例如：

```
[错误] 第 5 行: '[' 没有对应的 ']' 闭合 (unclosed bracket)
    > gw --> order[订单服务
[提示] 第 9 行: 节点 'log' 没有任何连线 (isolated nodes)
```

把这段原样追加为一条 user 消息：“程序检查报错如下，请只修正并重新输出完整代码块：……”。

## 如果用函数调用（Function Calling / Tool Use）

更小的模型用 JSON 比写 mermaid 更稳。工具定义见 `tool_schema.json`，参数形如：

```json
{
  "title": "订单系统架构",
  "direction": "TB",
  "nodes": [
    {"id": "user", "label": "用户", "shape": "stadium"},
    {"id": "gw", "label": "API 网关", "group": "后端服务"},
    {"id": "db", "label": "MySQL", "shape": "cylinder", "group": "数据层"}
  ],
  "edges": [
    {"from": "user", "to": "gw", "label": "HTTPS"},
    {"from": "gw", "to": "db"}
  ]
}
```

`archdiag.render(json_text, "out.pptx")` 直接接受这段 JSON。
