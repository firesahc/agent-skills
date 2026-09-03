---
name: git-commit-message
description: 基于代码变更生成规范 Git 提交信息的智能助手。当你完成代码修改需要提交时务必使用——包括功能开发、Bug 修复、重构、文档更新等场景。自动分析 git diff 变更内容，按照 Conventional Commits 规范生成结构化的 commit message，并自动执行提交。支持智能拆分：当暂存文件涉及多个不相关的变更时，自动拆分为多个独立提交。触发场景：「生成提交信息」「写commit message」「git提交」「commit规范」「提交代码」「生成git提交」「自动提交」。区别于代码审查、PR 创建、分支管理——此技能专注于根据实际代码修改生成符合规范的提交信息并自动提交。
---

# Git 智能提交信息生成

## 概述

此技能根据当前代码变更（git diff）自动生成符合 **Conventional Commits 规范** 的提交信息，并**直接执行提交**，无需用户确认。通过分析实际修改内容，提炼出准确的 `<type>`、`<scope>`、`<subject>` 和 `<body>`，确保提交历史清晰、可追溯、便于自动化处理。

**核心能力**：
1. **智能分组**：自动识别暂存文件的修改意图，将不相关的变更拆分为多个独立提交
2. **规范生成**：为每组变更生成符合 Conventional Commits 格式的提交信息
3. **自动执行**：直接执行 `git commit` 命令完成提交

**设计理念**：
- 提交信息必须**基于实际修改**，而非凭空臆造
- **一个提交只做一件事**，保持原子性
- GitHub 等平台链接作为可选增强
- **全自动流程**，无需人工干预


## 执行流程

### 阶段 1：获取变更内容

首先使用 git 命令查看当前修改：

```
1. git status                    # 查看修改文件列表及状态
2. git diff --staged --name-only # 列出所有已暂存的文件（核心）
3. git diff --staged             # 查看已暂存的详细变更内容
```

**关键原则**：
- **优先使用 `git diff --staged`**，因为暂存区是用户最终要提交的内容
- 如果暂存区为空，回退到 `git diff` 并提示用户暂存变更
- 记录变更涉及的文件路径和具体 diff 内容

**特殊场景**：
- 如果变更文件数量较少（≤3 个且逻辑关联），不拆分，作为单次提交
- 如果所有变更文件在同一个模块目录下，优先考虑合并为一次提交

### 阶段 2：智能分析与分组拆分

分析暂存文件列表，自动判断是否应该拆分为多个提交。

#### 2.1 分组判断逻辑

**拆分条件（满足任一即可视为独立分组）**：

| 判断维度 | 拆分条件 | 示例 |
| :--- | :--- | :--- |
| **文件路径** | 修改的文件位于完全不同的模块/目录 | `src/auth/` 和 `src/payment/` 同时有修改 |
| **变更类型** | 修改的性质不同（feat vs fix vs refactor vs docs） | 同时新增功能和修复 Bug |
| **功能独立性** | 修改的功能点之间没有依赖关系 | 修改 README 和修改核心业务逻辑 |
| **提交原子性** | 某个修改可以独立回滚而不影响其他修改 | 配置变更和代码变更可分 |

**合并条件（满足任一即应合并为一次提交）**：

| 判断维度 | 合并条件 | 示例 |
| :--- | :--- | :--- |
| **强关联性** | 多个文件修改服务于同一个功能点 | Controller + Service + Mapper 同时修改 |
| **依赖关系** | 修改 A 必须依赖修改 B 才能工作 | 接口定义和实现类同时修改 |
| **测试配套** | 功能代码和对应测试代码 | 业务逻辑 + 单元测试 |
| **修复闭环** | Bug 修复及其关联的测试用例 | 修复代码 + 回归测试 |

**分组优先级**：当拆分条件和合并条件同时满足时，按以下优先级决策：

```
合并条件（强关联/依赖/测试配套） > 拆分条件（文件路径/变更类型）
```

即：如果多个文件服务于同一功能（即使类型不同，如 feat + test），应合并；如果文件属于不同模块且无依赖，应拆分。

#### 2.2 分组流程

```
第一步：列出所有已暂存文件
         ↓
第二步：按文件路径推断所属模块
         ↓
第三步：分析每个文件的修改类型（feat/fix/refactor/docs...）
         ↓
第四步：检测是否存在多种变更类型
         ↓
第五步：根据相关性进行合并/拆分判断
         ↓
第六步：输出最终分组方案
```

**分组示例**：

| 暂存文件 | 模块 | 类型 | 判断 |
| :--- | :--- | :--- | :--- |
| `src/auth/LoginService.java` | auth | feat | → 第一组（认证功能） |
| `src/auth/LoginController.java` | auth | feat | → 第一组（同一功能，合并） |
| `src/payment/OrderService.java` | payment | fix | → 第二组（不同模块，拆分） |
| `README.md` | docs | docs | → 第三组（文档独立，拆分） |
| `src/payment/OrderServiceTest.java` | payment | test | → 第二组（测试配套，合并） |

### 阶段 3：为每组生成提交信息

对分组后的每组变更，按照以下规范分别生成提交信息。

#### 3.1 确定每组 `<type>`（变更类型）

**每组的 type 独立判断**，根据该组内所有文件的变更特征确定。

**判断规则**：

| 变更特征 | type |
| :--- | :--- |
| 新增文件（`new file mode`）、新增函数、新增配置项 | `feat` |
| 修改逻辑（`if` 条件、边界值、异常处理）、修正返回值 | `fix` |
| 仅修改 `.md` 文件、注释（`/* */`、`//`） | `docs` |
| 调整缩进/空格/换行，无逻辑变化 | `style` |
| 重命名变量/方法、提取公共函数、调整代码结构 | `refactor` |
| 优化算法、添加缓存、减少资源占用 | `perf` |
| 新增/修改测试文件（`*Test.java`、`*Spec.kt`） | `test` |
| 修改 `build.gradle`、`pom.xml`、`package.json`、CI 配置 | `chore` |
| diff 显示为 `Revert "xxx"` 格式 | `revert` |

**多文件同组时的 type 决策**：

- 如果组内所有文件 type 相同 → 使用该 type
- 如果组内包含功能代码（feat/fix/refactor）及其配套测试（test）→ 使用功能代码的 type
- 如果组内包含功能代码（feat/fix）和重构（refactor）混在一起 → **不应在同一组**，需拆分为不同提交

#### 3.2 确定 `<scope>`（影响范围）

从变更涉及的文件路径中提取模块名：

1. 列出该组所有变更文件的目录路径
2. 提取公共父目录或模块名（如 `src/auth/` → `auth`）
3. 若跨多个不相关目录，省略 scope 或使用 `*`

#### 3.3 提炼 `<subject>`（核心摘要）

**编写规则**：
- 以动词开头，使用中文动词（如 `添加`、`修复`、`更新`，而非 `添加了`、`已修复`）
- 结尾不加句号
- 严格 ≤ 50 字符
- 指明具体修改对象（函数名、配置项、字段名等）

**从 diff 提炼的三步法**：
1. 找到该组 diff 中**改动最大**的代码块
2. 识别该代码块的**功能角色**（函数/类/配置）
3. 用 `动词 + 对象` 格式概括

**常用动词与适用场景（中文）**：

| 动词 | diff 中的典型表现 |
| :--- | :--- |
| `添加` | 新增文件（`new file`）、新增函数、新增参数 |
| `移除` | 删除文件（`deleted file`）、删除代码块 |
| `修复` | 修改 `if` 条件、异常处理、返回值 |
| `更新` | 修改版本号、常量值、文案内容 |
| `更改` | 修改函数签名、数据结构字段 |
| `重命名` | 重命名文件、变量、方法（diff 显示 `rename`） |
| `移动` | 移动文件位置（diff 显示文件路径变更） |
| `重构` | 提取方法、调整结构（无功能变化） |
| `优化` | 修改循环、SQL、缓存策略 |
| `修正` | 修改错别字、注释、日志输出 |

#### 3.4 编写 `<body>`（详细说明）—— 建议每组都编写

**格式要求**：
```
<type>(<scope>): <subject>    ← 第一行：subject
                               ← 第二行：空行（必须）
<body>                         ← 第三行开始：body 详细说明
```

- body 每行 ≤ 72 字符
- 使用中文编写
- 内容应包含以下要素（按需组合）：
  - **修改背景**：为什么需要这次修改？
  - **实现方式**：如何实现的？（关键逻辑说明）
  - **影响范围**：涉及哪些模块？调用方需要注意什么？

### 阶段 4（可选）：GitHub 平台增强

如果检测到用户工作在 GitHub 环境（通过 `git remote -v` 检测），可自动添加以下可选信息。**注意：这些不改变核心提交内容，仅作为附加链接。**

#### 4.1 自动链接引用

在 body 或 footer 中键入以下格式，GitHub 会自动转换为可点击链接：

| 引用类型 | 格式 | 效果 |
| :--- | :--- | :--- |
| 提交 SHA | 完整 40 位或前 7 位哈希 | 链接到该提交，悬停显示信息 |
| Issue / PR | `#编号` 或 `GH-编号` | 链接到 Issue/PR，悬停预览 |
| 跨仓库 Issue | `owner/repo#编号` | 链接到其他仓库 |
| 用户提及 | `@用户名` | 链接到用户主页 |

#### 4.2 自动关闭 Issue（仅合并时生效）

在 footer 中使用关键词：

```
Closes #123
Fixes #456
Resolves #789
```

### 阶段 5：自动执行提交

生成提交信息后，**直接执行 `git commit` 命令**，无需用户确认。

#### 5.1 单组提交

直接执行：

```bash
git commit -m "type(scope): subject" -m "body"
```

#### 5.2 多组拆分提交

按分组顺序逐个提交，每组独立执行：

```bash
# 提交 1
git commit -m "feat(auth): 添加用户登录认证功能" \
  -m "实现 LoginService..."

# 提交 2
git commit -m "fix(payment): 修复订单支付状态更新失败" \
  -m "修复支付回调处理逻辑..."

# 提交 3
git commit -m "docs: 更新 README 部署说明" \
  -m "修正部署命令示例"
```

**多组提交执行逻辑**：
- 按分组顺序逐个执行 `git commit`
- 每组提交完成后，继续下一组
- 如果某组提交失败，终止后续提交并报告错误

#### 5.3 执行结果反馈

提交完成后，输出执行结果：

```
✅ 提交完成！

共执行 3 次提交：
  [1/3] feat(auth): 添加用户登录认证功能
  [2/3] fix(payment): 修复订单支付状态更新失败
  [3/3] docs: 更新 README 部署说明

查看提交历史：git log --oneline -3
```


## 完整示例

### 示例 1：多类型混合 → 自动拆分

**暂存文件列表**：
```
src/auth/LoginService.java      (新增)
src/auth/LoginController.java   (新增)
src/payment/OrderService.java   (修改，修复状态更新)
README.md                       (修改)
```

**分组分析**：

| 文件 | 模块 | 类型 | 判断 |
| :--- | :--- | :--- | :--- |
| LoginService.java | auth | feat | → 第一组：认证功能（feat） |
| LoginController.java | auth | feat | → 第一组（同一功能，合并） |
| OrderService.java | payment | fix | → 第二组：支付修复（fix） |
| README.md | docs | docs | → 第三组：文档更新（docs） |

**执行提交**：

```bash
# 提交 1
git commit -m "feat(auth): 添加用户登录认证服务" \
  -m "实现基于 JWT 的用户登录认证功能，包含 Service 层和 Controller 层。"

# 提交 2
git commit -m "fix(payment): 修复订单支付状态更新逻辑" \
  -m "修复支付回调时状态更新不一致的问题，新增状态机校验。"

# 提交 3
git commit -m "docs: 更新 README 中的快速启动说明" \
  -m "修正环境变量配置示例，补充本地运行步骤。"
```

### 示例 2：功能 + 配套测试 → 合并（不拆分）

**暂存文件列表**：
```
src/auth/LoginService.java      (修改)
src/auth/LoginServiceTest.java  (新增)
src/auth/LoginController.java   (修改)
src/auth/LoginControllerTest.java (新增)
```

**分组分析**：
- 所有文件都在 `src/auth/` 下
- Service 和 Controller 协同完成同一个功能
- Test 文件为配套测试

**判断**：不应拆分，合并为一次提交。

**执行提交**：

```bash
git commit -m "feat(auth): 完善用户登录认证模块" \
  -m "新增 LoginService 和 LoginController 的完整实现，包含单元测试覆盖。

核心功能：
- 用户名/密码登录认证
- JWT token 生成与校验
- 登录失败次数限制（5 次锁定 30 分钟）

测试覆盖：
- 正常登录流程测试
- 密码错误锁定测试
- token 过期刷新测试"
```

### 示例 3：功能 + 重构混在一起 → 强制拆分

**暂存文件列表**：
```
src/auth/LoginService.java      (新增，新功能)
src/auth/PasswordEncoder.java   (重构，提取加密逻辑)
```

**分组分析**：
- LoginService.java → 新增功能（feat）
- PasswordEncoder.java → 代码重构（refactor），与 LoginService 功能无直接依赖

**判断**：应拆分为 2 组，因为重构和新功能是独立的变更。

**执行提交**：

```bash
# 提交 1
git commit -m "feat(auth): 添加用户登录认证服务" \
  -m "新增 LoginService，提供用户名/密码登录认证功能。"

# 提交 2
git commit -m "refactor(auth): 提取密码加密逻辑到独立类" \
  -m "将原有的密码加密方法从 LoginService 中抽离，
  新建 PasswordEncoder 类统一管理加密逻辑。
  
  影响范围：
  - LoginService 中的 encodePassword() 移至 PasswordEncoder
  - 调用方需注入 PasswordEncoder 使用"
```

### 示例 4：跨模块但功能相关 → 合并（不拆分）

**暂存文件列表**：
```
src/auth/UserService.java       (修改)
src/notification/EmailService.java (修改)
src/config/CacheConfig.java     (修改)
```

**分组分析**：
- UserService 修改用户状态时触发邮件通知
- EmailService 新增了状态变更通知模板
- CacheConfig 添加了用户状态缓存

**判断**：三者服务于"用户状态变更通知"同一个功能，不应拆分。

**执行提交**：

```bash
git commit -m "feat(user): 添加用户状态变更通知功能" \
  -m "用户账号被禁用/启用时，自动发送邮件通知。

涉及变更：
- UserService：状态变更时调用通知服务
- EmailService：新增状态变更邮件模板
- CacheConfig：增加用户状态缓存，减少重复查询"
```


## 注意事项

### 路径规范
- 执行 `git` 命令时，确保在正确的项目根目录
- 报告中的文件路径使用相对于项目根目录的路径

### 提交信息语言
- **默认使用中文**撰写 commit message
- type 和 scope 保留英文（符合 Conventional Commits 规范）
- subject 和 body 使用中文

### 反模式（不要做的事）

- **不要无脑拆分**：强关联的修改必须合并，避免破坏项目可运行状态
- **不要将功能 + 重构混在一起**：功能变更和重构应独立提交（示例 3）
- **不要凭空编造**：提交信息必须基于实际 diff 内容
- **不要忽略暂存区**：优先检查 `git diff --staged`
- **不要写模糊的 subject**：如 `更新`、`改动`、`修复 bug`
- **不要忘记空行**：subject 和 body 之间必须有空行

### 特别检查项（常见错误）

| 检查项 | 问题 | 正确做法 |
| :--- | :--- | :--- |
| 类型判断 | 选择"最主要"类型而忽略其他类型 | 不同类型应拆分为不同提交 |
| 拆分粒度 | 关联代码被拆散 | 合并到同一提交 |
| 拆分粒度 | 无关代码混在一起 | 拆分为多个提交 |
| Subject 长度 | 超过 50 字符 | 精简到 50 字符内 |
| 空行 | subject 和 body 之间没有空行 | 必须空一行 |
| 空泛描述 | `修复 bug` | 具体说明 `修复支付回调中的空指针异常` |


## 快速参考卡

```
流程：git diff --staged → 自动分组 → 生成信息 → git commit

格式：
<type>(<scope>): <subject>
                                    ← 此处必须空行
<body>

type: feat | fix | docs | style | refactor | perf | test | chore | revert
scope: 模块名（从文件路径提取）

subject: 中文动词开头 + 具体对象，≤50字符，不加句号
body: 中文详细说明，每行≤72字符，建议每组都编写

拆分判断：
  ✓ 不同模块 → 拆分
  ✓ 不同类型 → 拆分
  ✓ 无依赖关系 → 拆分
  ✗ 同一功能 → 合并
  ✗ 有依赖关系 → 合并
  ✗ 测试配套 → 合并

强制拆分场景：
  ✗ feat + refactor 混在同一组 → 必须拆分
  ✗ fix + refactor 混在同一组 → 必须拆分

GitHub 可选增强（自动识别并添加）：
  #123  → 链接 Issue/PR
  @user → 提及用户
  SHA   → 链接提交
  Closes #123 → 合并时关闭 Issue
```
