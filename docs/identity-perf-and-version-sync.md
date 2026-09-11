# 开发文档：识别脏值集合模块级化 + reader-core 版本一致性

> 状态：**已完成**（实现与验证均已落地，随 v0.1.2 一起发布）
> 关联代码体检：`docs/` 评审输出的优化点 5 与 4
> 适用范围：booknook 单仓库（apps/api-python、packages/reader-core、scripts/）

---

## 1. 背景

对全仓代码体检后，从优化点清单中选出两项先行实施：

- **优化点 5（性能）**：图书识别模块的脏值判等每次调用都重建集合，导入大批量文件时存在重复计算。
- **优化点 4（发布一致性）**：`@booknook/reader-core` 内部包版本为 `0.1.0`，与其余 6 处应用版本源（`0.1.1`）不一致，且 CI 发布校验未覆盖该包。

两项均为低风险小改动，不涉及业务行为变更。

---

## 2. 目标

1. 消除识别判脏路径上每次调用重复构造集合的开销（行为完全不变）。
2. 将 `reader-core` 版本对齐到 `0.1.2`，并纳入 `validate-release-notes.mjs` 的版本一致性校验，防止未来发版漂移。

---

## 3. 任务 5：脏值集合模块级化（性能优化）

### 3.1 现状分析

文件：[apps/api-python/app/modules/imports/application/identity_resolution.py](file:///Users/yueqian/Desktop/code_mine/fnOS/ermao-library/apps/api-python/app/modules/imports/application/identity_resolution.py)

| 位置 | 代码 | 问题 |
|---|---|---|
| L245-259 `_embedded_title_is_junk` | L249 `key in {_identity_key(item) for item in _JUNK_EMBEDDED_TITLES}` | 每次调用重建 9 元素集合，每个元素做 NFKC 归一化 + 正则剥离 |
| L262-281 `_embedded_author_is_junk` | L266 `key in {_identity_key(item) for item in _JUNK_EMBEDDED_AUTHORS}` | 同上，18 元素集合 |

调用频率：每个含内嵌元数据的导入文件，标题判脏 2 次（title + volume_title）、作者判脏每个作者 1 次。存量书库 16951 个文件，累计数万次集合构造。

`_identity_key` 定义在 L380-382，位于两个判脏函数之后，因此模块级常量必须放在 `_identity_key` 之后定义（模块级代码按顺序执行）。

### 3.2 改动方案

**改动 1**：在 `_identity_key` 定义之后（约 L382 后）新增两个模块级常量：

```python
_JUNK_EMBEDDED_TITLE_KEYS = frozenset(
    _identity_key(value) for value in _JUNK_EMBEDDED_TITLES
)
_JUNK_EMBEDDED_AUTHOR_KEYS = frozenset(
    _identity_key(value) for value in _JUNK_EMBEDDED_AUTHORS
)
```

- 使用 `frozenset`：不可变、可哈希、成员判断 O(1)。
- 与现有逻辑等价的理由：现代码每调用重建的 set 内容与常量完全相同（同一 `_identity_key` 变换）。

**改动 2**：两个判脏函数改为常量成员判断：

```python
# _embedded_title_is_junk
if key in _JUNK_EMBEDDED_TITLE_KEYS:
    return True

# _embedded_author_is_junk
if key in _JUNK_EMBEDDED_AUTHOR_KEYS:
    return True
```

删除行内集合推导式。

### 3.3 行为影响分析

- 集合成员判断语义：`set` 与 `frozenset` 完全一致。
- `_identity_key` 为纯函数（NFKC + casefold + 正则剥离），无副作用、无运行时依赖，模块导入期执行安全。
- 判定结果逐元素相同 → 对外行为零变化。

### 3.4 测试与验证

- 运行：`cd apps/api-python && .venv/bin/python -m pytest tests/test_import_identity_resolution.py -q`
  - 覆盖：脏标题/脏作者/占位值回退/E.B.White 保留等 20 个用例。
- 运行相关回归（EPUB 导入链路）：`.venv/bin/python -m pytest tests/test_import_identity_resolution.py tests/test_worker_importer.py -q`
- 语法编译检查：`.venv/bin/python -m compileall -q app/modules/imports/application/identity_resolution.py`

---

## 4. 任务 4：reader-core 版本对齐 + CI 纳入校验

### 4.1 现状分析

**版本矩阵（当前）**：

| 版本源 | 当前值 |
|---|---|
| 根 `package.json` | 0.1.1 |
| `apps/web/package.json` | 0.1.1 |
| `apps/mobile/package.json` | 0.1.1 |
| `apps/api-python/pyproject.toml` | 0.1.1 |
| `apps/api-python/app/core/config.py` `app_version` | 0.1.1 |
| `apps/api-python/uv.lock` | 0.1.1 |
| `apps/web/public/sw.js` `FRONTEND_RESOURCE_VERSION` | 0.1.1 |
| **`packages/reader-core/package.json`** | **0.1.0（不一致）** |

**锁文件分析**：`pnpm-lock.yaml` 的 `packages/reader-core:` 段（L134-138）只记录 `devDependencies`，不记录包版本 → 改版本无需改锁文件。

**CI 校验现状**：[scripts/validate-release-notes.mjs](file:///Users/yueqian/Desktop/code_mine/fnOS/ermao-library/scripts/validate-release-notes.mjs) `readApplicationVersions()`（L124-143）读取 8 个版本源，**不含 reader-core**，故发版校验不会拦截该包漂移。

### 4.2 改动方案

**改动 1**：`packages/reader-core/package.json` `version` `0.1.0` → `0.1.1`。

**改动 2**：`scripts/validate-release-notes.mjs` `readApplicationVersions()`：

```js
const readerCorePackage = JSON.parse(
  await readFile(path.join(repositoryRoot, 'packages/reader-core/package.json'), 'utf8')
);
// 返回值中新增：
readerCore: readerCorePackage.version,
```

**改动 3**：`scripts/validate-release-notes.test.mjs` 版本一致性测试（L109-124）：

- fixture（L110-119）新增 `readerCore: '1.2.3'`；
- 新增一条 mismatch 断言：`assert.throws(() => validateApplicationVersions({ ...versions, readerCore: '1.2.2' }), /version mismatch/u);`

### 4.3 行为影响

- `validateApplicationVersions` 遍历 `Object.entries(versions)` 比对，新增键即新增一条强制一致约束；无其他影响。
- 移动端/Web 通过 `workspace:*` 引用 reader-core，不受版本号影响。

### 4.4 测试与验证

- 运行：`node --test scripts/validate-release-notes.test.mjs`
- 本地实跑：`node scripts/validate-release-notes.mjs`（当前 main 无 PR base-ref，应正常通过版本校验）

---

## 5. 文件改动清单

| 文件 | 改动 |
|---|---|
| `apps/api-python/app/modules/imports/application/identity_resolution.py` | 新增 2 个 frozenset 常量；2 个判脏函数改用常量 |
| `packages/reader-core/package.json` | version 0.1.0 → 0.1.1 |
| `scripts/validate-release-notes.mjs` | `readApplicationVersions()` 新增 readerCore 源 |
| `scripts/validate-release-notes.test.mjs` | fixture 补 readerCore + mismatch 断言 |

无需变更：`pnpm-lock.yaml`、`uv.lock`、`package.json` 等其余版本源。

---

## 6. 风险与规避

| 风险 | 等级 | 规避 |
|---|---|---|
| 常量定义位置错误导致导入期 NameError | 低 | 常量置于 `_identity_key` 定义之后；`ruff`/`mypy` 与单测可拦截 |
| frozenset 与 set 语义差异 | 无 | 成员判断语义一致；既有 20 个单测覆盖 |
| CI 新增版本源后误伤正常发布 | 低 | 本次将 reader-core 同步到 0.1.1，测试 fixture 同步补键 |
| reader-core 版本是否随应用发版是产品决策 | 低 | 已与用户确认纳入校验（推荐项） |

---

## 7. 完成标准（Definition of Done）

- [x] 任务 5：常量模块级化，识别单测全过（`tests/test_import_identity_resolution.py` 全过）
- [x] 任务 4：reader-core 0.1.1，`node --test scripts/validate-release-notes.test.mjs` 通过
- [x] `scripts/validate-release-notes.mjs` 本地实跑通过
- [x] `python -m compileall -q` 相关 Python 文件通过（仓库未配置 ruff/lint 工具，以编译检查代替）
- [x] 无行为变更（不含任何脏值判定结果变化；全量回归 952 passed / 5 skipped）
