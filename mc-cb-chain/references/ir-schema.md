# IR Schema —— 命令方块链分析中间表示

IR 是本方法论的**产品形态**。同一份 IR 可以支撑：单区域分析、两个副本对比、跨世界对比、
迁移前后 diff、自动生成执行流图。

版本化约定：schema 变更时递增 `schema_version`，旧版 IR 仍可被读。

---

## 顶层

```jsonc
{
  "schema_version": 1,
  "meta": {
    "tool": "cb_scan.py",
    "world": "绝对路径",
    "box": [x0, z0, x1, z1],          // 注意是 4 元组 (x1,z1,x2,z2)，不是 6 维
    "functions": "data/functions 目录或 null",
    "version_facts": "1.12",           // 所用的版本事实钉板
    "counts": { "terrain_blocks": 0, "tile_entities": 0, "command_blocks": 0,
                "nodes": 0, "edges": 0, "bridges": 0, "findings": 0 }
  },
  "nodes":   [ Node ],
  "edges":   [ Edge ],
  "dataflow": { "<objective>": { "<holder>": { "readers": [], "writers": [] } } },
  "bridges": [ Bridge ],
  "audit":   [ Finding ]
}
```

---

## Node

一个命令方块 = 一个 Node。

```jsonc
{
  "id": "cb:-2711,9,-973",
  "kind": "command_block",
  "pos": [-2711, 9, -973],

  // ---- 变体（从 block id 得出）----
  "variant": "chain",          // impulse | chain | repeating
  "block_id": 211,             // 137=impulse 210=repeating 211=chain

  // ---- 模式（从 Data 半字节译码）----
  "meta": 10,
  "facing": "north",           // down|up|north|south|west|east
  "conditional": true,         // bits: facing + 8

  // ---- 运行时状态（TileEntity）----
  "auto": 1,                   // 1=always active  0=needs redstone
  "always_active_default": true,
  "condition_met_last": 1,     // 无条件方块恒为 1
  "command": "/scoreboard players set ...",
  "custom_name": null,
  "track_output": 1
}
```

> `conditional` 的译码见 `version-facts-1.12.md` §2.2。若 `condition_met_last == 0` 而
> meta 判为无条件，以运行时证据为准（meta 编码异常），此情形应记入 audit。

---

## Edge

六类边。每条边都带 `evidence`，保证可人工审计。

| type | 含义 | from | to | delay_ticks |
|---|---|---|---|---|
| `chain` | chain 方块**朝向**的目标（链的下一环） | chain 节点 | 前方节点 | 0 |
| `conditional` | conditional 方块**背后**的前驱 | 背后节点 | conditional 节点 | 0 |
| `redstone` | 红石供电 | null（电源是地形） | 受电节点 | 0~4 或 null |
| `handoff` | `setblock <红石块>` 建立的电源交接 | 建方块的节点 | 26 邻域内的节点 | 1 |
| `comparator` | 比较器读成功计数 / 输出供电 | 被读取的节点 | 被供电的节点 | 0 |
| `event` | 玩家进入选择器 box 触发 | 节点 | null | 0 |

```jsonc
{
  "id": "e12",
  "type": "conditional",
  "from": "cb:-2711,9,-972",
  "to": "cb:-2711,9,-973",
  "at": [-2711, 9, -972],         // 背后格坐标
  "delay_ticks": 0,
  "resolved": true,                // from/to 是否命中命令方块
  "in_scope": true,                // 是否在 box 内
  "evidence": "facing=north -> behind cell [-2711, 9, -972]"
}
```

`redstone` 边额外带：

```jsonc
{
  "type": "redstone",
  "to": "cb:-2694,9,-943",
  "resolved": false,               // false = 接到粉网络但未在作用域内接到电源
  "delay_ticks": null,
  "sources": [
    { "at": [-2694, 9, -936], "id": 55, "name": "redstone_wire",
      "via": "dust_network", "network": [[...], [...]] }
  ],
  "dust_trace": [ { "dust_at": [...], "network_size": 7, "reaches_power": false } ]
}
```

`via` 取值：`direct`（6 面直接邻接电源）/ `repeater_front`（中继器正前方）/
`dust_network`（红石粉网络）。

---

## dataflow

按 **objective → holder** 两级组织。**不要**为每个状态变量新建 objective——1.12 的计分板
本就是"一个 objective 挂多个 holder"。

```jsonc
"dataflow": {
  "xz厄运岗哨": {
    "xz副本状态": { "readers": ["cb:..."], "writers": ["cb:..."] },
    "xz喽啰":     { "readers": [], "writers": ["cb:..."] }
  }
}
```

- `readers` 来自 `scoreboard players test` 与 `operation`（operation 既读又写）
- `writers` 来自 `set` / `add` / `remove` / `reset` / `operation` / `tag`
- **有 readers 无 writers** → 外部系统写入（audit R3）
- **有 writers 无 readers** → 死写，标为待清理

---

## bridges

命令方块里的 `function` 调用 = **桥接点**：方块侧给触发条件，函数侧给实现体。
世界（.mca）与 `data/functions` 是**两个独立存储**，必须双向走。

```jsonc
{
  "node": "cb:-2002,59,-2002",
  "at": [-2002, 59, -2002],
  "function": "main:main_1t",
  "resolved": true,
  "path": "/abs/path/data/functions/main/main_1t.mcfunction",
  "variant": "impulse",
  "auto": 1,
  "conditional": false,
  "facing": "north"
}
```

---

## audit / Finding

```jsonc
{
  "rule": "R2",
  "status": "violated",     // violated | external | pass | needs_manual_trace
                            // | chain_triggered | handoff_powered
                            // | comparator_powered | player_probe
  "target": "cb:-2703,1,-900",
  "detail": "auto=0 且既无 6 面电源、也无 chain/交接/玩家触发"
}
```

---

## 语义标注层（由模型补写，不由脚本产出）

IR 是纯机械事实。**语义层**单独存放，字段名带 `sem_` 前缀以示区分：

```jsonc
"sem": {
  "phases": [
    { "id": "P0", "name": "入场门禁",
      "nodes": ["cb:..."], "entry": "cb:-2707,1,-911", "exit": "cb:-2713,9,-933",
      "kind": "chain", "trigger": "player_probe", "duration_ticks": null }
  ],
  "clocks": [
    { "holder": "抽奖", "objective": "几率", "period_ticks": 33,
      "kind": "deterministic", "evidence": "set0+add1+test33 三件套" }
  ],
  "setblock_roles": [
    { "at": [-2700, 9, -933], "block": "minecraft:redstone_block",
      "role": "plumbing", "reason": "用于激活相邻命令方块，非玩法效果" }
  ]
}
```

**`setblock_roles` 的 plumbing/gameplay 区分是迁移前的必做判定**，判错会直接导致副本
跑不起来或行为变形。
