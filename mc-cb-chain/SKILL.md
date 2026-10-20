---
name: mc-cb-chain
description: 分析 Minecraft Java 1.12 世界中命令方块链的执行流程与时序——把"一堆命令方块 + 红石元件 + functions"还原成可读的程序：变体与朝向解码、条件链前驱解析、红石供电追踪、跨 tick 交接判定、状态变量读写图、审计规则。只要用户提到命令方块链/命令方块执行顺序/条件方块 conditional/红石电路触发顺序/命令方块时序/副本流程还原/命令方块迁移，或要分析某个区域里的命令方块到底怎么跑，就用这个技能。也适用于"这个副本的触发逻辑是什么""这些命令方块的先后顺序""这个条件链是怎么串起来的"这类问题。
---

# Minecraft 命令方块链分析

把命令方块世界**还原成一个程序**：谁触发谁、什么顺序、什么状态、什么频率、哪些是管道哪些是玩法。

## 何时调用

- 用户要弄清某个区域里的命令方块**怎么跑**、**什么顺序**、**怎么互相触发**
- 用户要分析**条件方块（conditional）**的前驱是谁、为什么某段逻辑不执行
- 用户要判断**红石电路**给命令方块供电的路径
- 用户要把一个**命令方块副本迁移**到函数包，需要先还原执行流
- 用户问"这个副本的阶段是怎么推进的"

## 何时不用

- 只是**读/改**某个命令方块的命令文本或 NBT → 用 `world-editer` 技能
- 只是**写**函数包内容，不关心原地图怎么跑 → 直接写

## 核心认知（先读这个，否则整个分析会错）

**1.12 的命令方块不是程序，没有跳转。** 所谓"控制流"由三样东西涌现：
**触发关系**（什么条件下会执行）、**同拍序**（同一 tick 内的先后）、**数据依赖**（读的状态是谁写的）。
还原一条链必须分别重建这三张图，不能追一条序列。

### 1. `conditional` 的前驱 = 朝向反方向的邻格

**不是**坐标排序的前一个，**不是**链上的前一个。
Wiki 原文：*"Behind it" in the sense of opposite to the direction the command block is facing,
regardless of chain direction or even if chaining is occurring.*

于是：**朝向前方 = 链的下一环（chain 变体）；朝向后方 = 条件判定的对象**。

### 2. 1.12 的 facing / conditional 存在 Data 半字节里

1.12 没有 `BlockStates`。`facing`：`0=下 1=上 2=北 3=南 4=西 5=东`；`conditional` = **+8**。
合法 meta：`{0..5}` 无条件、`{8..13}` 有条件。

**`world-editer` 的 `BLOCKS_1_12` 表是错的**（中继器写成 55 实为 93、缺比较器 149、缺三种命令方块）。
用 `references/version-facts-1.12.md` 里的钉板，不要用工具自带的表。

### 3. 三种变体的 id

`137` = impulse（需红石/玩家触发）· `210` = repeating（每 tick）· `211` = chain（被朝向它的方块触发）。
**210 与 211 极易搞反**，务必用钉板。

### 4. 链在 1.12 同 tick 内跑完

17w16a 起 chain 不再排到下一 tick。跨 tick 的只有**红石路径**。
`setblock` 造的红石块在 TE 相位生效 → 目标命令方块在**下一 tick** 执行 → **交接延迟 = 1 tick**。

### 5. 1.12 没有的东西

`execute if @e`（1.13+）、`execute store`（1.17+）、实体死亡事件回调、函数 `return`。
`function ... if <selector>` **不中断父函数**。

### 6. 计分板 holder 在前、objective 在后

`scoreboard players <sub> <holder> <objective>`。写反不报错，只静默失败。
一个 objective 下挂多个 holder 是正常用法，别为每项状态新建 objective。

## 工具

**`scripts/cb_scan.py` 是唯一的机械提取器**——它只做"数出来"的事，产出 IR JSON。

```bash
python scripts/cb_scan.py \
  -w <world根目录> \
  --box x1,z1,x2,z2 \
  [--functions <data/functions目录>] \
  [--world-editer-src <world_editer的src目录>] \
  --out <输出.json>
```

- 依赖 `world_editer`（提供 NBT/chunk 解析）。路径查找顺序：`--world-editer-src` →
  环境变量 `WORLD_EDITER_SRC` → 默认路径 → 脚本同级的 `src/`。**不要自己重写 NBT 读取器。**
- 地形方块扫描走 `world_editer.chunk.scan_blocks`（每 chunk 只解压一次）。
  **不要逐点调 `read_block`**——那是 O(n²)。
- 1.12 的 NBT 形态判别（裸 dict 的 Section、双层 byte array、异构 list）
  由 `world_editer.nbt` 的 `unwrap` / `as_compound` / `as_list` / `as_bytes` 统一负责。
- **只读**，不修改 world。
- 输出 stdout 只有 ASCII（Windows 控制台默认 GBK，打印中文会崩）。
- `--box` 是 **4 元组** `(x1, z1, x2, z2)`，不是 6 维。

IR 的字段定义见 `references/ir-schema.md`。

**脚本只负责事实，不负责判断。** 阶段命名、plumbing/gameplay 分类、时钟识别——这些是模型的事。

## 工作流

### P-1 确认版本事实

读 `references/version-facts-1.12.md`。若目标版本不是 1.12，**这份钉板整体失效**，
需要先换版本再分析（1.13+ 用 palette + BlockStates，1.12 用 id + Data 半字节）。

**外部数据源可能出错。** 钉板里的每条都带 `documented` / `cross-validated` / `source-read` 标记；
遇到与本世界数据矛盾时，用**被分析数据自身的统计特征**裁决，并写回钉板。

### P0 采集 → P2 节点

跑 `cb_scan.py`，拿到 nodes / edges / dataflow / bridges / audit。

若脚本报 `nodes` 远小于命令方块总数，说明 `facing` 译码失败——回去核对版本钉板，
**不要绕过脚本手写提取代码**。

### P1 空间索引（脚本已内建）

`cb_scan.py` 已按 chunk 批量读地形方块（逐点 `read_block` 是 O(n²)，不要那么做），
并对每个 `auto=0` 节点做 6 面扫描 + 中继器朝向检查 + 红石粉网络 BFS。

### P3 触发分类

对每个 `auto=0` 节点，按 `references/redstone-grammar.md` §1 的顺序穷举五种来源：
玩家探针 → chain 触发 → 比较器供电 → 红石直接/间接 → setblock 交接。
**先排除前三种再谈红石**，否则会把大量 chain 触发误报成"缺电源"。

### P4 建图

脚本已产出六类边：`chain` / `conditional` / `redstone` / `handoff` / `comparator` / `event`。
每条边带 `evidence`，可人工审计。

### P5 时序层序

三张图要分开呈现：

| 尺度 | 决定因素 |
|---|---|
| 同 tick 内 | chain 的朝向串联 + conditional 的背后格 |
| 跨 tick | 红石延迟（交接 1 tick，中继器 1~4 tick） |
| 事件驱动 | 玩家进入 box / 按键 |

**`delay_ticks` 允许为 `null`（未知）。宁可显式写"未知"，也不要填一个看起来合理的默认值**——
一个错的延迟会污染整张时序图。

### P6 数据流

按 objective → holder 两级组织。**有 readers 无 writers = 外部依赖**（audit R3），
这类盲区必须显式暴露，不能让报告看起来完整却其实错误。

### P7 语义解读（模型做）

- 从 chain 图的实际走法切分**执行阶段**
- 识别**时钟**：确定性（`add` + 阈值 `set 0` + `test`）/ 概率（`set` 随机值 + 分段 `test`）/
  状态机（`set` 一次 + 分阶段 `add`）。**概率触发器不是时钟。**
- 判定每个 `setblock` 的角色：**plumbing**（时序管道，迁移时删除）还是
  **gameplay**（玩法效果，迁移时保留）。判错的后果：删掉 gameplay → 副本门常开；
  保留 plumbing → 每 tick 重复触发。
- 区分"**局部链**"与"**全局条件链**"：1.12 的 conditional 前驱是局部邻格，天然不会跨副本；
  会跨的是**数据依赖**。

### P8 报告

用 `assets/report-template.md`。**每节末尾必须有结论**，写不出结论说明这节没分析透。
全文用 `[推导]` / `[实测]` / `[假设]` 三态标注每条结论的知识状态。

## 审计规则

跑完脚本后必须逐条解释 `violated`。规则定义见 `references/audit-rules.md`。
写"已忽略"不算解释。

几条最容易踩的：

| 规则 | 坑 |
|---|---|
| R1 | 背后格不是命令方块 → 条件恒不满足，链在这一环断掉 |
| R2 | 只做 6 面扫描会把 chain 触发误报成"缺电源" |
| R3 | 外部写入的计分板是分析盲区，必须显式标出 |
| R4 | `setblock 红石块` 没有配对的 `setblock air` → 电源常驻，下游时序全变 |
| R5 | 检测环要用三色 DFS；带全局 `state` 的递归会误报 |

## 别做

- 别用 `world-editer` 自带的 `BLOCKS_1_12` 表译码 facing——它是错的
- 别把 `conditionMet` 当成"是否 conditional"——它只是**上次执行结果**；
  无条件方块恒为 1
- 别用坐标排序推条件链——1.12 的前驱是**背后邻格**
- 别逐点调 `read_block` 扫区域——走 chunk 批读
- 别往 stdout 打中文——写 UTF-8 文件
- 别在报告里用未经验证的延迟值填 `delay_ticks`
- 别把探测/清理类的 `setblock` 一次性全删——先判 plumbing vs gameplay
- 别用 `stats entity ... set` 每 tick 重复配置——那是一次性配置

## 参考文件

| 文件 | 什么时候读 |
|---|---|
| `references/version-facts-1.12.md` | **每次都读**。版本事实钉板 |
| `references/ir-schema.md` | 读/写 IR，或扩展脚本输出时 |
| `references/redstone-grammar.md` | 做 P3 触发分类、P5 时序层序时 |
| `references/audit-rules.md` | 解释审计结果时 |
| `assets/report-template.md` | 写报告时 |

## 配套技能

`world-editer` —— 读写 .mca / NBT。本技能只读，且只关心命令方块的**执行语义**。
需要改命令方块内容时用那个。
