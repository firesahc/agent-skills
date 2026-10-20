#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
cb_scan.py —— Minecraft 命令方块链分析的确定性提取器

只做"数出来"的事：采集、聚合、提取、建图、跑审计规则。
一切需要语义判断的部分（阶段命名、plumbing/gameplay 分类、时钟识别）
交给模型，本脚本不猜。

产出 IR JSON，schema 见 references/ir-schema.md。

用法:
  python cb_scan.py --world <world根目录> --box x1,z1,x2,z2 \
                    [--functions <data/functions 目录>] \
                    [--world-editer-src <world_editer 的 src 目录>] \
                    [--out <输出 json 路径>]

约定:
  * 不向 stdout 打印任何非 ASCII 字符（Windows 控制台默认 GBK 会崩）
  * 不修改 world，只读
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 1.12 坐标轴: +X=东 +Y=上 +Z=南 -Z=北
# 所有"朝向"相关计算都依赖这个约定，见 references/version-facts-1.12.md §1

# ---------------------------------------------------------------- 1.12 钉板

# 命令方块三变体: id -> (变体名, 默认是否 always-active)
CMD_VARIANTS = {
    137: ("impulse", False),
    210: ("repeating", True),
    211: ("chain", True),
}

# 命令方块 data: facing(0=down 1=up 2=north 3=south 4=west 5=east), +8 = conditional
CB_FACING = {0: "down", 1: "up", 2: "north", 3: "south", 4: "west", 5: "east"}
CB_COND_OFFSET = 8

# 朝向 -> (dx, dy, dz)
FACING_DELTA = {
    "down":  (0, -1, 0),
    "up":    (0, 1, 0),
    "north": (0, 0, -1),
    "south": (0, 0, 1),
    "west":  (-1, 0, 0),
    "east":  (1, 0, 0),
}

# 红石元件 id -> 名称
REDSTONE_IDS = {
    55: "redstone_wire", 69: "lever", 70: "stone_pressure_plate",
    72: "wooden_pressure_plate", 75: "unlit_redstone_torch", 76: "redstone_torch",
    77: "stone_button", 93: "unpowered_repeater", 94: "powered_repeater",
    143: "wooden_button", 147: "light_weighted_pressure_plate",
    148: "heavy_weighted_pressure_plate", 149: "unpowered_comparator",
    150: "powered_comparator", 151: "daylight_detector", 152: "redstone_block",
    154: "hopper", 157: "activator_rail", 28: "detector_rail", 218: "observer",
}

# 能"持续供电"的元件（可作电源）
POWER_SOURCES = {152, 76, 69, 147, 148, 150, 151, 94, 157}

# 1.12 红石火把 metadata -> **附着侧**（火把挂靠的实心方块在哪一侧）
# 钉板 version-facts-1.12.md §3。火把**不给自己附着的方块**供电，其余 5 面供电。
# 交叉验证：恶毒地宫 277 个火把中 meta=1 唯一实心邻居恒为 W、2 恒为 E、3 恒为 N、4 恒为 S。
TORCH_ATTACH = {
    0: (0, 1, 0),    # 上
    1: (-1, 0, 0),   # 西
    2: (1, 0, 0),    # 东
    3: (0, 0, -1),   # 北
    4: (0, 0, 1),    # 南
    5: (0, -1, 0),   # 下
}

# 1.12 水平朝向索引（repeater bits2-3 / comparator bits0-1）
# 钉板 version-facts-1.12.md §3.1：**0=north 1=east 2=south 3=west**
# （原表 0=south 1=west 2=north 3=east 是 180° 反的，已修正）
FACING_H = {
    0: (0, 0, -1),   # north
    1: (1, 0, 0),    # east
    2: (0, 0, 1),    # south
    3: (-1, 0, 0),   # west
}

# 比较器的固有信号延迟（game tick）
COMPARATOR_DELAY = 2


# ---------------------------------------------------------------- 工具

def load_world_editer(src_hint: str | None):
    """import world_editer，路径可配置。返回 (region, nbt, tile, chunk) 模块。

    1.12 的 NBT 形态判别由 world_editer.nbt 统一负责（unwrap / as_compound /
    as_list / as_bytes），本脚本**不再自带**一份实现，避免两边分叉。
    """
    cands = []
    if src_hint:
        cands.append(Path(src_hint))
    env = os.environ.get("WORLD_EDITER_SRC")
    if env:
        cands.append(Path(env))
    cands.append(Path(r"D:\D\User Data\Documents\vscode Projects\world-editer\src"))
    # 同名包就近查找
    here = Path(__file__).resolve()
    for parent in here.parents:
        cands.append(parent / "src")
    cands.append(Path(__file__).resolve().parent)

    for c in cands:
        if (c / "world_editer" / "region.py").exists():
            sys.path.insert(0, str(c))
            from world_editer import region, nbt, tile, chunk  # noqa
            return region, nbt, tile, chunk
    raise SystemExit(
        "world_editer not found. Pass --world-editer-src or set WORLD_EDITER_SRC."
    )


# ---------------------------------------------------------------- P0 采集

def scan_terrain(region, chunk, world: Path, box):
    """批量读地形方块。委托给 world_editer 的 chunk 层（每 chunk 只解压一次）。"""
    return chunk.scan_blocks(region, world, box)


def scan_tiles(tile, world: Path, box):
    """读范围内全部 TileEntity（含命令方块、比较器、告示牌、箱子…）。"""
    x0, z0, x1, z1 = box
    try:
        res = tile.tile_list(world, box=box, keyword=None)
    except Exception:
        res = []
    out = []
    for te in res:
        x, y, z = te.get("x"), te.get("y"), te.get("z")
        if x is None:
            continue
        if not (x0 <= x <= x1 and z0 <= z <= z1):
            continue
        out.append(te)
    return out


# ---------------------------------------------------------------- P2 节点

def decode_cmd_block(te, terrain):
    """从 TileEntity + 地形 meta 还原命令方块的变体 / facing / conditional。"""
    pos = (te.get("x"), te.get("y"), te.get("z"))
    bm = terrain.get(pos)
    if bm is None:
        return None
    bid, meta = bm
    variant, default_always = CMD_VARIANTS.get(bid, (None, None))
    if variant is None:
        return None
    facing = CB_FACING.get(meta & 0x7)
    conditional = bool(meta & CB_COND_OFFSET) if meta >= CB_COND_OFFSET else False
    # 交叉验证：conditionMet==0 只可能出现在 conditional 方块
    cond_met = te.get("conditionMet")
    if cond_met == 0 and not conditional:
        conditional = True          # meta 编码异常，以运行时证据为准
    if cond_met == 1 and conditional and meta < CB_COND_OFFSET:
        conditional = False
    return {
        "id": "cb:%d,%d,%d" % pos,
        "kind": "command_block",
        "pos": list(pos),
        "variant": variant,
        "block_id": bid,
        "meta": meta,
        "facing": facing,
        "conditional": conditional,
        "auto": te.get("auto"),
        "always_active_default": default_always,
        "condition_met_last": cond_met,
        "command": (te.get("Command") or "").strip(),
        "custom_name": te.get("CustomName"),
        "track_output": te.get("TrackOutput"),
    }


def cmd_verb(cmd: str) -> str:
    c = cmd.strip()
    if c.startswith("/"):
        c = c[1:]
    if not c:
        return ""
    return c.split()[0].split(":")[0].lower()


# ---------------------------------------------------------------- P4 边

RE_SETBLOCK = re.compile(
    r"^/?setblock\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(\S+)(.*)$", re.I)
RE_FILL = re.compile(r"^/?fill\s+", re.I)
RE_EXECUTE_SELECTOR = re.compile(r"^/?execute\s+@", re.I)
RE_SCORE = re.compile(
    r"^/?scoreboard\s+players\s+(\w+)\s+(\S+)\s+(\S+)(.*)$", re.I)
RE_FUNCTION = re.compile(r"^/?function\s+(\S+)", re.I)


def parse_setblock(cmd):
    """解析 setblock 的目标与方块名。返回 (pos, block_name, nbt_str) 或 None。"""
    m = RE_SETBLOCK.match(cmd.strip())
    if not m:
        return None
    x, y, z = int(m.group(1)), int(m.group(2)), int(m.group(3))
    block = m.group(4).lower()
    if block.startswith("minecraft:"):
        block = block[len("minecraft:"):]
    return (x, y, z), block, m.group(5)


# 相对 setblock：`setblock ~1 ~ ~ <block>` —— 落点相对于**执行方块**自己
RE_SETBLOCK_REL = re.compile(r"^/?setblock\s+(~[-+]?\d*)\s+(~[-+]?\d*)\s+(~[-+]?\d*)\s+(\S+)(.*)$", re.I)


def parse_setblock_rel(cmd, origin):
    """解析相对 setblock。返回 ((dx,dy,dz), block_name, nbt_str) 或 None。"""
    m = RE_SETBLOCK_REL.match(cmd.strip())
    if not m:
        return None
    def off(tok):
        t = tok.strip()
        if t == "~":
            return 0
        return int(t.replace("~", "") or 0)
    block = m.group(4).lower()
    if block.startswith("minecraft:"):
        block = block[len("minecraft:"):]
    return (off(m.group(1)), off(m.group(2)), off(m.group(3))), block, m.group(5)


def build_nodes(cbs, terrain):
    nodes = {}
    for te in cbs:
        n = decode_cmd_block(te, terrain)
        if n:
            nodes[n["id"]] = n
    return nodes


def build_edges(nodes, terrain, scope_box):
    """构造四类边。每条边都带 evidence，便于人工审计。"""
    edges = []
    eid = 0
    x0, z0, x1, z1 = scope_box

    def in_scope(p):
        return x0 <= p[0] <= x1 and z0 <= p[2] <= z1

    for n in nodes.values():
        pos = tuple(n["pos"])
        facing = n["facing"]
        d = FACING_DELTA.get(facing)

        # --- 条件依赖：背后格 ---
        if n["conditional"] and d:
            behind = (pos[0] - d[0], pos[1] - d[1], pos[2] - d[2])
            tgt = nodes.get("cb:%d,%d,%d" % behind)
            edges.append({
                "id": "e%d" % eid, "type": "conditional",
                "from": tgt["id"] if tgt else None,
                "to": n["id"],
                "at": list(behind),
                "delay_ticks": 0,
                "resolved": bool(tgt),
                "in_scope": in_scope(behind),
                "evidence": "facing=%s -> behind cell %s" % (
                    facing, list(behind)),
            })
            eid += 1

        # --- chain 串联：它所朝向的方块 ---
        if n["variant"] == "chain" and d:
            front = (pos[0] + d[0], pos[1] + d[1], pos[2] + d[2])
            tgt = nodes.get("cb:%d,%d,%d" % front)
            edges.append({
                "id": "e%d" % eid, "type": "chain",
                "from": n["id"],
                "to": tgt["id"] if tgt else None,
                "at": list(front),
                "delay_ticks": 0,
                "resolved": bool(tgt),
                "in_scope": in_scope(front),
                "evidence": "chain faces %s -> %s" % (facing, list(front)),
            })
            eid += 1

        # --- 红石交接：命令本身建红石块 ---
        sb = parse_setblock(n["command"])
        rel = None
        if sb is None:
            rel = parse_setblock_rel(n["command"], pos)
        if sb or rel:
            if rel is not None:
                d, block, nbtstr = rel
                tpos = (pos[0] + d[0], pos[1] + d[1], pos[2] + d[2])
            else:
                tpos, block, nbtstr = sb
            if block in ("redstone_block", "redstone_torch",
                         "unlit_redstone_torch", "redstone_wire",
                         "unpowered_repeater", "unpowered_comparator"):
                # 目标点 26 邻域内的命令方块 = 被供电者
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for dz in (-1, 0, 1):
                            if dx == dy == dz == 0:
                                continue
                            nb = (tpos[0] + dx, tpos[1] + dy, tpos[2] + dz)
                            tgt = nodes.get("cb:%d,%d,%d" % nb)
                            if tgt:
                                edges.append({
                                    "id": "e%d" % eid, "type": "handoff",
                                    "from": n["id"],
                                    "to": tgt["id"],
                                    "at": list(nb),
                                    "power_at": list(tpos),
                                    "delay_ticks": 1,
                                    "resolved": True,
                                    "in_scope": in_scope(nb),
                                    "evidence": "setblock %s %s -> powers %s" % (
                                        list(tpos), block, list(nb)),
                                })
                                eid += 1

    return edges


def build_power_edges(nodes, terrain, scope_box):
    """**impulse** 命令方块的供电来源。

    作用域限定：只有 impulse(137) 需要外部电源。repeating 每 tick 自跑、
    chain 被链触发，二者的 `auto` 字段没有语义（钉板 §2.5），
    因此**不能**用 `auto == 0` 来筛需要触发源的对象。

    分三级判定（逐级放宽）：
      L1 直接邻接  6 面内就有电源元件（红石块/火把/中继器输出/比较器输出…）
      L2 中继器    相邻中继器的**正前方**就是本方块
      L3 粉网络    相邻红石粉，沿粉网络 BFS，看网络里是否接到电源
    仍找不到的记为 needs_manual_trace —— 可能需要跨作用域或人工判读。
    """
    x0, z0, x1, z1 = scope_box
    out = []
    eid = 100000

    def is_power(bid):
        return bid in POWER_SOURCES

    def dust_network(start):
        """从 start 出发沿红石粉正交连通扩散，返回 (集合, 是否接到电源, 电源点)。"""
        seen = {start}
        stack = [start]
        powered_by = None
        while stack:
            cur = stack.pop()
            cx, cy, cz = cur
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                nb = (cx + dx, cy + dy, cz + dz)
                if nb in seen:
                    continue
                bm = terrain.get(nb)
                if bm is None:
                    continue
                bid = bm[0]
                if bid == 55:                     # 红石粉
                    seen.add(nb)
                    stack.append(nb)
                elif is_power(bid) and powered_by is None:
                    powered_by = {"at": list(nb), "id": bid,
                                  "name": REDSTONE_IDS.get(bid, "id=%d" % bid)}
        return seen, powered_by

    def directly_powered(mid, exclude):
        """mid 这块实心方块是否被**直接**供电（相邻元件给它电）。
        返回 (电源描述, 延迟) 或 (None, None)。排除 exclude 那个方块自身。

        这是"二级传导"的基础：被直接供电的实心方块会把电力传给相邻命令方块
        （钉板 §3.2 / redstone-grammar §2.1）。
        """
        mx, my, mz = mid
        for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                           (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            nb = (mx + dx, my + dy, mz + dz)
            if nb == exclude:
                continue
            bm = terrain.get(nb)
            if bm is None:
                continue
            bid, meta = bm
            if bid == 152:
                return ({"at": list(nb), "id": bid, "name": "redstone_block",
                         "meta": meta}, 0)
            if bid == 76:                     # 火把：除附着块外都供电
                att = TORCH_ATTACH.get(meta)
                if att is not None and (-dx, -dy, -dz) == att:
                    continue
                return ({"at": list(nb), "id": bid, "name": "redstone_torch",
                         "meta": meta}, 0)
            if bid in (69, 70, 72, 143, 77, 147, 148, 151, 157):
                return ({"at": list(nb), "id": bid,
                         "name": REDSTONE_IDS.get(bid, "id=%d" % bid),
                         "meta": meta}, 0)
            if bid in (149, 150):             # 比较器：正前方才有输出
                if (nb[0] + FACING_H[meta & 3][0],
                        nb[1] + FACING_H[meta & 3][1],
                        nb[2] + FACING_H[meta & 3][2]) == mid:
                    return ({"at": list(nb), "id": bid, "name": "comparator",
                             "meta": meta}, COMPARATOR_DELAY)
            if bid in (93, 94):               # 中继器：正前方才有输出
                if (nb[0] + FACING_H[(meta >> 2) & 3][0],
                        nb[1] + FACING_H[(meta >> 2) & 3][1],
                        nb[2] + FACING_H[(meta >> 2) & 3][2]) == mid:
                    return ({"at": list(nb), "id": bid, "name": "repeater",
                             "meta": meta}, (meta & 3) + 1)
            if bid == 55:                     # 红石粉：网络里接到电源即通电
                net, powered_by = dust_network(nb)
                if powered_by:
                    return ({"at": powered_by["at"], "id": powered_by["id"],
                             "name": powered_by["name"], "via": "dust_network",
                             "network": [list(c) for c in sorted(net)]}, 0)
        return (None, None)

    for n in nodes.values():
        if n["variant"] != "impulse":
            continue
        pos = tuple(n["pos"])
        sources = []
        trace = []
        for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                           (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            nb = (pos[0] + dx, pos[1] + dy, pos[2] + dz)
            bm = terrain.get(nb)
            if bm is None:
                continue
            bid, meta = bm
            if bid == 76:                     # 红石火把：除附着块外全部供电
                att = TORCH_ATTACH.get(meta)
                if att is not None and (-dx, -dy, -dz) == att:
                    continue                 # 该方块正是火把附着的块
                sources.append({"at": list(nb), "id": bid,
                                "name": "redstone_torch",
                                "meta": meta, "via": "direct"})
            elif bid in (149, 150):          # 比较器：只给正前方供电（延迟 2 tick）
                cdelta = FACING_H[meta & 3]
                if (nb[0] + cdelta[0], nb[1] + cdelta[1], nb[2] + cdelta[2]) == pos:
                    sources.append({"at": list(nb), "id": bid,
                                    "name": "comparator",
                                    "meta": meta, "via": "comparator_front",
                                    "delay_ticks": COMPARATOR_DELAY})
            elif bid in (93, 94):              # 中继器：正前方才有输出
                rdir = (meta >> 2) & 3          # 1.12: 0=north 1=east 2=south 3=west
                rdelta = FACING_H[rdir]
                if (nb[0] + rdelta[0], nb[1] + rdelta[1], nb[2] + rdelta[2]) == pos:
                    sources.append({"at": list(nb), "id": bid,
                                    "name": "repeater",
                                    "meta": meta, "via": "repeater_front",
                                    "delay_ticks": (meta & 3) + 1})
            elif bid in (152, 69, 143, 77, 147, 148, 151, 157):
                sources.append({"at": list(nb), "id": bid,
                                "name": REDSTONE_IDS.get(bid, "id=%d" % bid),
                                "meta": meta, "via": "direct"})
            elif bid == 55:                     # 红石粉：追网络
                net, powered_by = dust_network(nb)
                trace.append({"dust_at": list(nb), "network_size": len(net),
                              "reaches_power": bool(powered_by),
                              "power_at": powered_by["at"] if powered_by else None})
                if powered_by:
                    sources.append({"at": powered_by["at"], "id": powered_by["id"],
                                    "name": powered_by["name"],
                                    "via": "dust_network",
                                    "network": [list(c) for c in sorted(net)]})
        # L1.5 二级传导：6 面邻接的**实心方块**本身被直接供电 → 电力传给本方块
        #      （典型：压力板 → 混凝土 → 命令方块；火把 → 红石粉 → 标记块 → 命令方块）
        if not sources:
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                mid = (pos[0] + dx, pos[1] + dy, pos[2] + dz)
                bm = terrain.get(mid)
                if bm is None:
                    continue
                if bm[0] in (0, 55, 69, 70, 72, 75, 76, 77, 93, 94, 143,
                             147, 148, 149, 150, 151, 152, 157, 137, 210, 211):
                    continue                      # 非"实心导体方块"
                src, dly = directly_powered(mid, pos)
                if src:
                    src = dict(src)
                    src["via"] = "conductive_block"
                    src["mid_block"] = list(mid)
                    sources.append(src)
                    break
        # L1.6 动态电源：附近有命令方块会在运行时 setblock 出红石元件。
        #      该电源在存档里并不存在，静态看不到，只能标 needs_manual_trace。
        if not sources:
            for other in nodes.values():
                sb = parse_setblock(other["command"])
                if sb:
                    tpos, block, _ = sb
                else:
                    rel = parse_setblock_rel(other["command"], tuple(other["pos"]))
                    if not rel:
                        continue
                    d, block, _ = rel
                    op = other["pos"]
                    tpos = (op[0] + d[0], op[1] + d[1], op[2] + d[2])
                if block not in ("redstone_block", "redstone_torch",
                                 "unlit_redstone_torch", "redstone_wire"):
                    continue
                cheb = max(abs(tpos[0] - pos[0]), abs(tpos[1] - pos[1]),
                           abs(tpos[2] - pos[2]))
                if cheb <= 2:
                    sources.append({"at": list(tpos), "id": None,
                                    "name": "dynamic_%s" % block,
                                    "via": "dynamic_power",
                                    "set_by": other["id"],
                                    "delay_ticks": 1})
                    break
        if sources:
            out.append({
                "id": "p%d" % eid, "type": "redstone",
                "from": None, "to": n["id"],
                "at": list(pos), "delay_ticks": 0,
                # 只有"运行时才存在"的动态电源时不能算已解析
                "resolved": not all(s.get("via") == "dynamic_power"
                                    for s in sources),
                "in_scope": True,
                "sources": sources,
                "dust_trace": trace,
                "evidence": "power scan: %s" % ", ".join(
                    "%s@%s(%s)" % (s["name"], s["at"], s["via"]) for s in sources),
            })
            eid += 1
        elif trace:
            out.append({
                "id": "p%d" % eid, "type": "redstone",
                "from": None, "to": n["id"],
                "at": list(pos), "delay_ticks": None,
                "resolved": False, "in_scope": True,
                "sources": [], "dust_trace": trace,
                "evidence": "相邻红石粉网络未接到电源 -> 需人工追踪",
            })
            eid += 1
    return out


# ---------------------------------------------------------------- P6 数据流

def build_comparator_edges(nodes, terrain, scope_box):
    """比较器读取命令方块的成功计数（success count），并把信号送到正前方。

    1.12 比较器：bits0-1 = 供电方向（0=north 1=east 2=south 3=west）；bit2 = 减法模式
      meta 编码的是「正前 / 输出」方向，因此：
        位于 C、供电方向 F 的比较器 —— 读取 C - F（后端），供电 C + F（正前）
      读取端若是命令方块，则读到的是它的「成功计数」（0 / 1）。
      —— 1.12 里这是把「命令执行结果」变成红石信号的**唯一**手段。
    """
    x0, z0, x1, z1 = scope_box
    out = []
    eid = 200000
    for pos, (bid, meta) in terrain.items():
        if bid not in (149, 150):
            continue
        fidx = meta & 3
        fdelta = FACING_H[fidx]
        back = (pos[0] - fdelta[0], pos[1] - fdelta[1], pos[2] - fdelta[2])
        front = (pos[0] + fdelta[0], pos[1] + fdelta[1], pos[2] + fdelta[2])
        src = nodes.get("cb:%d,%d,%d" % back)
        dst = nodes.get("cb:%d,%d,%d" % front)
        if src is None and dst is None:
            continue
        out.append({
            "id": "c%d" % eid, "type": "comparator",
            "from": src["id"] if src else None,
            "to": dst["id"] if dst else None,
            "at": list(pos), "delay_ticks": COMPARATOR_DELAY,
            "resolved": bool(src or dst),
            "in_scope": (x0 <= front[0] <= x1 and z0 <= front[2] <= z1),
            "reads": list(back), "writes": list(front),
            "mode": "subtract" if (meta >> 2) & 1 else "compare",
            "evidence": "comparator@%s facing idx=%d reads %s -> powers %s"
                        % (list(pos), fidx, list(back), list(front)),
        })
        eid += 1
    return out


def build_dataflow(nodes):
    """scoreboard (holder, objective) 读写图。
       语法: scoreboard players <sub> <holder> <objective> [args]
       —— holder 在前、objective 在后，写反不报错只静默失败。"""
    reads = defaultdict(list)   # (holder, objective) -> [node ids]
    writes = defaultdict(list)
    for n in nodes.values():
        for m in re.finditer(
                r"scoreboard\s+players\s+(\w+)\s+(\S+)\s+(\S+)", n["command"]):
            sub, holder, obj = m.group(1), m.group(2), m.group(3)
            if sub in ("test",):
                reads[(holder, obj)].append(n["id"])
            elif sub in ("set", "add", "remove"):
                writes[(holder, obj)].append(n["id"])
            elif sub in ("operation",):
                reads[(holder, obj)].append(n["id"])
                writes[(holder, obj)].append(n["id"])
            elif sub in ("reset", "tag"):
                writes[(holder, obj)].append(n["id"])
    table = {}
    for key in set(list(reads.keys()) + list(writes.keys())):
        h, o = key
        table.setdefault(o, {})[h] = {
            "readers": sorted(set(reads.get(key, []))),
            "writers": sorted(set(writes.get(key, []))),
        }
    return table


def find_bridges(nodes, functions_dir):
    """命令方块里的 function 调用 = 桥接点：方块给触发条件，函数给实现体。"""
    out = []
    for n in nodes.values():
        m = RE_FUNCTION.match(n["command"])
        if not m:
            continue
        fname = m.group(1).strip()
        resolved, path = None, None
        if functions_dir:
            rel = fname.replace(":", "/") + ".mcfunction"
            cand = Path(functions_dir) / rel
            if cand.exists():
                resolved = True
                path = str(cand)
            else:
                resolved = False
        out.append({
            "node": n["id"], "at": n["pos"],
            "function": fname,
            "resolved": resolved, "path": path,
            "variant": n["variant"],
            "auto": n["auto"],
            "conditional": n["conditional"],
            "facing": n["facing"],
        })
    return out


# ---------------------------------------------------------------- 审计

def run_audit(nodes, edges, dataflow, terrain, scope_box):
    findings = []

    def add(rule, status, target, detail):
        findings.append({"rule": rule, "status": status,
                         "target": target, "detail": detail})

    by_id = nodes

    # R1 每个 conditional 节点的前驱必须解析出来
    cond_edges = [e for e in edges if e["type"] == "conditional"]
    for e in cond_edges:
        if not e["resolved"]:
            add("R1", "violated", e["to"],
                "behind cell %s 不是命令方块" % e["at"])
        elif not e["in_scope"]:
            add("R1", "external", e["to"],
                "前驱 %s 在作用域外" % e["at"])
    for n in nodes.values():
        if n["conditional"] and not any(
                e["type"] == "conditional" and e["to"] == n["id"] for e in edges):
            add("R1", "violated", n["id"], "conditional 但未找到背后格")

    # R2 每个 **impulse** 节点必须有触发来源
    #   作用域：只有 impulse(137) 需要外部电源。repeating 每 tick 自跑、chain 被链触发，
    #   二者的 `auto` 无语义（钉板 §2.5），用 auto==0 筛选会把 repeating 传感器全误报成"缺电源"。
    #   触发来源可能是：6 面红石元件 / 被 chain 触发 / 被 setblock 交接供电 / 玩家进入区域
    powered = {e["to"] for e in edges if e["type"] == "redstone"}
    unresolved_power = {e["to"] for e in edges
                        if e["type"] == "redstone" and not e.get("resolved")}
    chain_triggered = {e["to"] for e in edges
                       if e["type"] == "chain" and e.get("resolved")}
    handoff_powered = {e["to"] for e in edges if e["type"] == "handoff"}
    comparator_powered = {e["to"] for e in edges
                          if e["type"] == "comparator" and e.get("resolved")}
    for n in nodes.values():
        if n["variant"] != "impulse":
            continue
        nid = n["id"]
        if nid in powered:
            continue
        if nid in chain_triggered:
            add("R2", "chain_triggered", nid,
                "impulse 但由前置 chain 方块触发（非红石直接供电）")
        elif nid in handoff_powered:
            add("R2", "handoff_powered", nid,
                "impulse 由 setblock 建立的电源交接供电")
        elif nid in comparator_powered:
            add("R2", "comparator_powered", nid,
                "impulse 由比较器输出供电（比较器读取其后方命令方块的成功计数，延迟 2 tick）")
        elif nid in unresolved_power:
            dyn = [s for e in edges if e["type"] == "redstone" and e["to"] == nid
                   for s in e.get("sources", []) if s.get("via") == "dynamic_power"]
            if dyn:
                add("R2", "needs_manual_trace", nid,
                    "impulse 的电源是**运行时**由 %s setblock 出来的 %s（存档里不存在）"
                    " -> 静态只能标 needs_manual_trace，运行时可验证"
                    % (dyn[0].get("set_by"), dyn[0].get("name")))
            else:
                add("R2", "needs_manual_trace", nid,
                    "impulse，接到红石粉网络但网络未在作用域内接到电源 -> 需人工追踪")
        elif RE_EXECUTE_SELECTOR.match(n["command"]):
            add("R2", "player_probe", nid,
                "impulse 但命令是 execute @a[...] 空间选择器 -> 玩家触发")
        else:
            add("R2", "violated", nid,
                "impulse 且既无 6 面电源、也无 chain/交接/玩家触发")

    # R3 每个被读取的分数必须有写者
    for obj, holders in dataflow.items():
        for h, info in holders.items():
            if info["readers"] and not info["writers"]:
                add("R3", "external", "%s/%s" % (obj, h),
                    "有读者无写者 -> 外部系统写入")

    # R4 每个 setblock redstone_block 必须有同坐标的移除
    set_pos = {}
    for n in nodes.values():
        sb = parse_setblock(n["command"])
        if sb:
            tpos, block, _ = sb
        else:
            rel = parse_setblock_rel(n["command"], tuple(n["pos"]))
            if not rel:
                continue
            d, block, _ = rel
            tpos = (n["pos"][0] + d[0], n["pos"][1] + d[1], n["pos"][2] + d[2])
        if block == "redstone_block":
            set_pos[tpos] = n["id"]
    cleared = set()
    for n in nodes.values():
        sb = parse_setblock(n["command"])
        if sb:
            tpos, block, _ = sb
        else:
            rel = parse_setblock_rel(n["command"], tuple(n["pos"]))
            if not rel:
                continue
            d, block, _ = rel
            tpos = (n["pos"][0] + d[0], n["pos"][1] + d[1], n["pos"][2] + d[2])
        if block == "air":
            cleared.add(tpos)
    for tpos, nid in set_pos.items():
        if tpos not in cleared:
            add("R4", "violated", nid,
                "在 %s 建了红石块但作用域内无同坐标 setblock air -> 电源永久存在"
                % list(tpos))

    # R5 同拍链不得成环（用三色 DFS，避免状态残留造成误报）
    chain_adj = defaultdict(list)
    for e in edges:
        if e["type"] == "chain" and e["resolved"]:
            chain_adj[e["from"]].append(e["to"])

    WHITE, GREY, BLACK = 0, 1, 2
    color = {}

    def cyc(nid, path):
        """返回首个找到的环（列表），无环返回 None。"""
        color[nid] = GREY
        path.append(nid)
        for nxt in chain_adj.get(nid, []):
            c = color.get(nxt, WHITE)
            if c == GREY:
                return path[path.index(nxt):] + [nxt]
            if c == WHITE:
                r = cyc(nxt, path)
                if r:
                    return r
        path.pop()
        color[nid] = BLACK
        return None

    reported = False
    for nid in list(chain_adj):
        if color.get(nid, WHITE) == WHITE:
            c = cyc(nid, [])
            if c:
                add("R5", "violated", nid,
                    "chain 环: %s" % " -> ".join(x.split(":", 1)[1] for x in c))
                reported = True
                break
    if not reported:
        add("R5", "pass", "-", "chain 图无环")

    # R6 setblock 目标必须落在已加载 chunk 内
    x0, z0, x1, z1 = scope_box
    for n in nodes.values():
        sb = parse_setblock(n["command"])
        if sb:
            tpos, _, _ = sb
        else:
            rel = parse_setblock_rel(n["command"], tuple(n["pos"]))
            if not rel:
                continue
            d, _, _ = rel
            tpos = (n["pos"][0] + d[0], n["pos"][1] + d[1], n["pos"][2] + d[2])
        if not (x0 <= tpos[0] <= x1 and z0 <= tpos[2] <= z1):
            add("R6", "outside", n["id"],
                "setblock 目标 %s 在作用域外 -> 需确认该 chunk 已加载" % list(tpos))

    # R7 链结构内不得混用三种变体
    variant_by_id = {k: v["variant"] for k, v in nodes.items()}
    for e in edges:
        if e["type"] == "chain" and e["resolved"]:
            a, b = variant_by_id.get(e["from"]), variant_by_id.get(e["to"])
            if a and b and a != b:
                add("R7", "violated", e["from"],
                    "chain 相邻变体不同: %s(%s) -> %s(%s)" % (e["from"], a, e["to"], b))

    # R10 跨作用域条件前驱
    for e in cond_edges:
        if e["resolved"] and not e["in_scope"]:
            add("R10", "external", e["to"],
                "前驱 %s 跨出作用域" % e["at"])

    return findings


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="command block chain analyzer (1.12)")
    ap.add_argument("-w", "--world", required=True, help="world root")
    ap.add_argument("--box", required=True, help="x1,z1,x2,z2")
    ap.add_argument("--functions", default=None, help="data/functions dir")
    ap.add_argument("--world-editer-src", default=None)
    ap.add_argument("--out", required=True, help="output json path")
    args = ap.parse_args()

    parts = [int(p) for p in args.box.split(",")]
    if len(parts) != 4:
        raise SystemExit("--box must be x1,z1,x2,z2")
    box = (parts[0], parts[1], parts[2], parts[3])

    region, nbt, tile, chunk = load_world_editer(args.world_editer_src)
    world = Path(args.world).resolve()

    terrain = scan_terrain(region, chunk, world, box)
    tiles = scan_tiles(tile, world, box)
    cb_tiles = [t for t in tiles if "Command" in t]

    nodes = build_nodes(cb_tiles, terrain)
    edges = (build_edges(nodes, terrain, box)
             + build_power_edges(nodes, terrain, box)
             + build_comparator_edges(nodes, terrain, box))
    dataflow = build_dataflow(nodes)
    bridges = find_bridges(nodes, args.functions)
    findings = run_audit(nodes, edges, dataflow, terrain, box)

    ir = {
        "meta": {
            "tool": "cb_scan.py",
            "world": str(world),
            "box": list(box),
            "functions": args.functions,
            "version_facts": "1.12",
            "counts": {
                "terrain_blocks": len(terrain),
                "tile_entities": len(tiles),
                "command_blocks": len(cb_tiles),
                "nodes": len(nodes),
                "edges": len(edges),
                "bridges": len(bridges),
                "findings": len(findings),
            },
        },
        "nodes": list(nodes.values()),
        "edges": edges,
        "dataflow": dataflow,
        "bridges": bridges,
        "audit": findings,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(ir, f, ensure_ascii=False, indent=2)

    # stdout 只输出 ASCII
    c = ir["meta"]["counts"]
    print("OK -> %s" % out)
    print("terrain=%d tiles=%d cmdblocks=%d nodes=%d edges=%d bridges=%d findings=%d"
          % (c["terrain_blocks"], c["tile_entities"], c["command_blocks"],
             c["nodes"], c["edges"], c["bridges"], c["findings"]))
    vs = Counter(n["variant"] for n in nodes.values())
    print("variants: " + ", ".join("%s=%d" % kv for kv in sorted(vs.items())))
    st = Counter(f["status"] for f in findings)
    print("audit: " + (", ".join("%s=%d" % kv for kv in sorted(st.items())) or "clean"))


if __name__ == "__main__":
    main()
