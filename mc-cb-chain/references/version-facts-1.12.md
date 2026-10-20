# 版本事实钉板 —— Minecraft Java 1.12.2

这是**按目标版本固化**的事实表。每条带三态标记：

| 标记 | 含义 |
|---|---|
| `documented` | 有公开权威出处（Wiki / 官方文档 / 变更日志） |
| `cross-validated` | 用被分析对象自身的数据统计交叉验证过 |
| `source-read` | 从 1.12.2 jar 源码读出 |

> **钉板原则**：外部数据源之间冲突时，以**被分析数据自身的统计特征**裁决，并写回本表。
> 实例：PrismarineJS 的 `blocks.json` 把命令方块 north/south 的 conditional 值写成 14/15，
> 而 Arqade 给出的是 10/11。用源世界 243 个命令方块做 `meta × conditionMet` 交叉表后
> 判定 Arqade 正确（meta∈{0,1,2,3,5} 的 `conditionMet` 恒为 1，从不为 0），
> 并将 10/11 写回本表。`cross-validated`

---

## 1. 坐标轴约定

`documented`

```
+X = 东 (East)      +Y = 上 (Up)      +Z = 南 (South)
-X = 西 (West)      -Y = 下 (Down)    -Z = 北 (North)
```

**"朝向北"= 箭头指向 -Z。"背后 (behind)"= 朝向的反方向 = +Z。**

---

## 2. 命令方块

### 2.1 三种变体的 block id

`cross-validated`

| id | name | 触发方式 | 备注 |
|---:|---|---|---|
| 137 | `minecraft:command_block` | 需红石（`auto=0`）或始终激活（`auto=1`） | impulse |
| 210 | `minecraft:repeating_command_block` | `auto=1` 时每 tick 执行 | repeating |
| 211 | `minecraft:chain_command_block` | 被"朝向它的命令方块"触发 | chain |

> ⚠️ 210 与 211 极易搞反。实测源副本：211×210、210×11、137×22。

### 2.2 data 半字节编码（1.12 旧格式，无 BlockStates）

`cross-validated`

```
facing : 0=down  1=up  2=north  3=south  4=west  5=east
conditional = 上述值 + 8
```

合法 meta 集合：`{0,1,2,3,4,5}` 无条件，`{8,9,10,11,12,13}` 有条件。

| meta | facing | conditional | | meta | facing | conditional |
|---:|---|---|---|---|---:|---|---|
| 0 | down | 否 | | 8 | down | 是 |
| 1 | up | 否 | | 9 | up | 是 |
| 2 | north | 否 | | 10 | north | 是 |
| 3 | south | 否 | | 11 | south | 是 |
| 4 | west | 否 | | 12 | west | 是 |
| 5 | east | 否 | | 13 | east | 是 |

**判别 conditional 的第二种手段**：TileEntity 的 `conditionMet` 语义是
*"True if not a conditional command block"* —— 无条件方块该字段**恒为 1**。
若某 meta 出现过 `conditionMet=0`，则该 meta 必为 conditional。

### 2.3 `conditional` 的前驱是"背后"邻格

`documented` + `cross-validated`

> *"Behind it" in the sense of **opposite to the direction the command block is facing**,
> regardless of chain direction or even if chaining is occurring.*

- 前驱格 = `pos - facing_delta`（即朝向的反方向邻格）
- **不是**坐标排序的前一个，**不是**链上的前一个
- 实测：源副本 111 个 conditional 方块，其背后格 **111/111 精确命中另一个命令方块**

### 2.4 chain 的串联方向

`documented`

- 一个命令方块**朝向**某个 chain 方块 → 触发它
- chain 方块被触发后 → 触发**它所朝向**的那个 chain 方块
- 即 chain 流向 = **朝向方向**；条件判定 = **朝向反方向**
- 1.12（17w16a）起：**一条链在同一 tick 内全部执行完**，不再排到下一 tick
  （1.12 前是排到下一 tick）

### 2.5 TileEntity 字段

`documented`

| 字段 | 含义 |
|---|---|
| `auto` | 1=始终激活(always active)，0=需红石(needs redstone) |
| `conditionMet` | 上次执行时条件是否满足；**无条件方块恒为 1** |
| `powered` | 是否已被触发 |
| `Command` | 命令原文（可带前导 `/`） |
| `TrackOutput` / `LastOutput` | 输出记录；`LastOutput` 是内嵌 JSON 的字符串，尾部可能带 `"}` |
| `LastExecution` | 上次执行的 tick |

---

## 3. 红石元件

`documented`（数据源：PrismarineJS minecraft-data `data/pc/1.12/blocks.json` 的 `variations` 字段）

| id | name | data 编码 |
|---:|---|---|
| 55 | `minecraft:redstone_wire` | **信号强度 0-15**（连接形状不入库，由邻居规则推导） |
| 69 | `minecraft:lever` | bits0-2 = 朝向/附着；bit3 = 已激活 |
| 70 | `minecraft:stone_pressure_plate` | 0=未激活, 1=已激活 |
| 72 | `minecraft:wooden_pressure_plate` | 0=未激活, 1=已激活 |
| 75 | `minecraft:unlit_redstone_torch` | 0=东(附着西侧), 1=西, 2=南, 3=北, 4=上(附着下方) |
| 76 | `minecraft:redstone_torch` | 同上 |
| 77 | `minecraft:stone_button` | 同木按钮 |
| 93 | `minecraft:unpowered_repeater` | bits0-1 = 延迟-1（0→1tick … 3→4tick）；bits2-3 = 朝向 |
| 94 | `minecraft:powered_repeater` | 同上 |
| 143 | `minecraft:wooden_button` | 0=下,1=东,2=西,3=南,4=北,5=上；+8 = 已按下 |
| 147 | `minecraft:light_weighted_pressure_plate` | 信号强度 0-15 |
| 148 | `minecraft:heavy_weighted_pressure_plate` | 信号强度 0-15 |
| 149 | `minecraft:unpowered_comparator` | bits0-1 = 朝向；bit2 = 减法模式 |
| 150 | `minecraft:powered_comparator` | 同上 |
| 151 | `minecraft:daylight_detector` | 信号强度 0-15 |
| 152 | `minecraft:redstone_block` | 无 meta |
| 154 | `minecraft:hopper` | 0=下, 2=北, 3=南, 4=西, 5=东 |
| 157 | `minecraft:activator_rail` | 0-5 形状；+8 已激活 |
| 28 | `minecraft:detector_rail` | 0-5 形状；+8 已激活 |
| 218 | `minecraft:observer` | 0=下 … 5=东 |

### 3.1 水平朝向索引（repeater / comparator 共用）

`documented`

```
0 = south   1 = west   2 = north   3 = east
```

### 3.2 供电规则要点

`documented`

- 红石块：给 6 面供电，强度 15
- 火把：给除附着面外的所有邻格供电；附着在方块上时是**反相器**
- 中继器：只给**正前方**的方块供电；延迟 1-4 tick
- 比较器：给**正前方**供电；比较模式取两侧最大值，减法模式 = 背后 - 前面
- 红石粉：连接正交相邻的粉/电源/受电方块；不向斜向供电
- 中继器/比较器/火把的 on-off 发生在 **TT 相位**

---

## 4. Tick 相位模型

`documented`（来源：techmc.wiki intra-tick timing + Minecraft Wiki Tick）

单 tick 内的相位顺序：

```
AT  玩家动作
TT  计划刻（scheduled tick）：命令方块执行命令、中继器/比较器/火把 on-off
TE  方块实体更新：方块放置"落地"、方块移除生效
BE  方块事件：活塞伸缩、箱子开合
EU  实体更新
```

**推论（关键）：**

- 命令方块在 **TT 相位**执行
- `setblock` 放置的红石块在 **TE 相位**生效 → 目标命令方块在**下一 tick 的 TT 相位**执行
  → **红石交接边延迟 = 1 tick**
- 红石粉状态变化是**即时**的（instant），不经 TE
- 若命令方块由中继器供电，延迟 = 中继器延迟（1-4 tick），且中继器本身在 TT 相位动作

---

## 5. 1.12 指令边界

`documented`

| 事项 | 1.12 现状 | 后果 |
|---|---|---|
| `execute if @e[...]` | **不存在**（1.13+） | 1.12 只能用 `testfor` / `testforblock` / `testforblocks` |
| `execute store` | **不存在**（1.17+） | 取指令结果只能靠 `stats` |
| `function ... if <selector>` | **不中断父函数**，且无 `return` | 条件逻辑必须写成嵌套守卫函数 |
| `scoreboard players <sub> <holder> <objective>` | **holder 在前、objective 在后** | 写反不报错，只静默失败 |
| `stats entity <e> set <类型> <holder> <objective>` | **一次性配置**，记录该实体**最后执行的那条命令**的结果 | 同一实体上不同类型互相覆盖 → 一器一类型；配置后不可省略 |
| `stats` 的 `SuccessCount` | 记录该实体**成功执行命令的次数**（0/1 判定用） | 与命令方块自身的"成功计数"是两回事：后者是**该方块最后一条命令是否成功**，可被比较器读取 |
| `scoreboard players test <holder> <objective> <min> [max]` | 区间**含端点**；省略 max 则到上限 | `test X 1 1` 才是精确等于 1 |
| `scoreboard` 的 objective 维度 | 一个 objective 下可挂多个 holder | 状态变量应按 holder 区分，不要为每项新建 objective |
| 实体死亡事件 | **无原生回调** | 无法做"死亡时计数-1"；只能用 `testfor` 判空 / 代理盔甲架 / 击杀增量 |
| `maxCommandChainLength` | gamerule，默认 65536 | 单 tick 链长上限 |

---

## 6. 1.12 chunk 存储形态

`cross-validated`

- **无 `BlockStates`**：1.12 用 `Blocks`（id 字节数组）+ `Data`（meta 半字节数组）
- `Sections[]` 的元素是**裸 dict**（不是 `(10, dict)` 元组）
- `Blocks` 的值形如 `(7, ('bytearray', b'...'))` —— **双层嵌套**，需递归解包
- 半字节索引：`idx = si >> 1`，低半字节在前：`meta = (db[idx] >> ((si & 1) << 2)) & 0x0F`
- 位置索引：`si = ((y & 15) << 8) | ((z & 15) << 4) | (x & 15)`
- 1.13+ 才是 palette + `BlockStates`；若目标版本 ≥1.13，本表全部失效，需换版钉板

> **形态判别的唯一实现**在 `world_editer.nbt`：`unwrap` / `as_compound` / `as_list` / `as_bytes`。
> 业务代码不要自己写判别——历史上 `block.read_block` 就因为写错而恒返回空气。
> `mc-cb-chain` 通过 `world_editer.chunk` 层消费这些能力，不再自带一份实现。

---

## 7. 其它被本项目实测纠正的常见错误

`cross-validated`

- `world-editer` 的 `BLOCKS_1_12` 表把**中继器写成 55**（实为 93）、**缺比较器 149**、**缺三种命令方块 137/210/211**
- 1.12 命令方块**没有** `BlockStates`，`facing`/`conditional` 在 Data 半字节里
- `conditionMet` 是**上次执行结果**，不是"是否 conditional"；用它反推模式需配合 2.2 的判别法
- 控制台默认 GBK：Python `print` 中文会 `UnicodeEncodeError` → 一律写 UTF-8 文件再读回
- 正则匹配中文 objective/holder 用 Unicode 转义（如 `抽奖` = `\u62a9\u734e`），不依赖 shell 编码
