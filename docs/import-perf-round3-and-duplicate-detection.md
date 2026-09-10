# 开发文档：第三轮导入性能优化 + 图书查重/相似图书归档

> 状态：**已完成**（实现与验证均已落地，待发布）
> 适用范围：booknook 单仓库（apps/api-python、apps/web）

---

## 1. 背景

在 v0.1.2 的识别/分类优化之后，继续做两件事：

- **性能**：对导入管线做第三轮体检，消除高频路径上每次调用重复的 `resolve()` 系统调用、重复集合构造与字符串模式正则的 re 缓存查找。
- **功能**：用户书库中常出现同一本书的多份文件（不同大小的 PDF、PDF+EPUB 并存、不同版本、不同翻译），需要一个「图书查重 / 相似图书归档」能力来识别并合并这些重复作品。

两项均已完成并通过全量回归（972 passed / 5 skipped）。

---

## 2. 目标

1. 消除导入/识别热路径上的冗余计算，行为完全不变。
2. 新增四层模糊查重算法，识别「同书多格式 / 不同版本 / 不同翻译」的重复作品，并接入「重复作品治理」面板供合并归档。

---

## 3. 任务 A：导入管线性能优化（第三轮）

前两轮已处理：判脏集合模块级化（identity_resolution.py）、`list_sibling_files` 去重复 `resolve()`、`work_grouping` 去重复 `strip()`/`resolve()`。

### 3.1 本轮新增优化点

| 文件 | 位置 | 问题 | 优化 |
|---|---|---|---|
| `import_audio.py` | 分组循环（L195-243） | 每个音轨 × 每个分组重复 `path.resolve()`（系统调用）并重建 `set(group.files)`，O(N×G) | 预计算 `resolved_items` 与每组 `frozenset`，循环内纯集合查找 |
| `book_identity.py` | `_clean_author` / `_clean_title` / `_is_volume_only` / `_looks_like_download_source` / `_clean_download_title` | 每次调用 `re.compile` 或字符串模式 `re.sub` | 8 个模式提到模块级常量（`_NORMALIZE_PUNCTUATION_RE`、`_LEADING_NATIONALITY_RE`、`_TRAILING_ROLE_WORD_RE`、`_ETC_TAIL_RE`、`_LEADING_PARENTHETICAL_RE`、`_TRAILING_EBOOK_EXT_RE`、`_WS_COLLAPSE_RE`、`_VOLUME_ONLY_LATIN/CJK_RE`） |
| `identity_policy.py` | `normalize_identity_part` / `_clean_title` / `_clean_author` / `normalize_directory_merge_title` | 同上 | `_NORMALIZE_PUNCTUATION_RE`、`_NUMBER_PLACEHOLDER_RE`、`_TRAILING_EBOOK_EXT_RE`、`_WS_COLLAPSE_RE`、`_LEADING_PARENTHETICAL_RE` |
| `identity_resolution.py` | `_identity_key`（每文件调用数万次）/ `_clean_value` | 字符串模式 `re.sub` 每次走 re 缓存 | `_IDENTITY_KEY_STRIP_RE`、`_WS_COLLAPSE_RE` |
| `import_support.py` | `_author_is_missing`（每本书导入） | 每次调用重建 3 元素集合并重复计算 `_normalize_key(未知作者)` | 模块级 `_MISSING_AUTHOR_KEYS` frozenset（置于 `_normalize_key` 定义之后） |

### 3.2 行为影响

- 所有优化均为纯机械等价改写：`resolve()` 对同一扫描路径幂等；`set`/`frozenset` 成员判断语义一致；正则预编译与字符串模式结果相同。
- 对外行为零变化。

### 3.3 验证

- `tests/test_book_identity.py`、`tests/unit/modules/imports`、有声书集成测试全过。
- 全量回归 972 passed / 5 skipped。

---

## 4. 任务 B：图书查重 / 相似图书归档

### 4.1 需求场景

- 同一本书多个 PDF，仅大小不同；
- 同一本书 PDF 与 EPUB 两种格式并存；
- 同一本书的不同版本（第 2 版 / 8th Edition / 修订版等）；
- 同一本书的不同翻译（书名核心相同、译者不同）。

### 4.2 四层查重算法

新模块：[duplicate_detection.py](file:///Users/yueqian/Desktop/code_mine/fnOS/ermao-library/apps/api-python/app/modules/library/application/duplicate_detection.py)

输入全部可见作品的 `(id, title, author, normalized_title, normalized_author)`，按置信度从高到低分五组（Tier 1/3/2/4a/4b），每本书只归入命中且未被更高层占用的第一个分组：

| 层 | 置信度 | 判据 | 识别场景 |
|---|---|---|---|
| Tier 1 | 0.98 | normalized title + author 完全相同 | 同书多格式/多文件 |
| Tier 3 | 0.90 | 去版本/来源标记后键相同（第N版、th Edition、Z-Library、修订版等） | 不同版本 |
| Tier 2 | 0.82 | 标题相同、作者记录不同（标题 ≥ 4 字） | 不同翻译/版本 |
| Tier 4a | 0.72 | 同作者桶内标题相似度 ≥ 85%（并查集合并，桶上限 300） | 重复文件/近似版本 |
| Tier 4b | 0.70 | 共享书名核心（≥ 5 字中文片段，剔除出版社/国家后缀） | 不同翻译 |

### 4.3 边界处理（测试驱动修复）

- **尾部数字括号 = 卷号非副本**：`数理化自学丛书第2版 化学 (2)` 与 `(5)` 是不同分册 → Tier 3 键不同（`化学2` vs `化学5`），且 Tier 4a 增加尾部数字括号比对，不同则跳过。
- **`第2版` 句中剥离**：`duplicate_title_key` 对第N版全位置剥离（不同版次是同一本书）；`丛书/系列/全集` 仅允许结尾剥离，避免拆坏「数理化自学丛书」这类丛书名。
- **短中文标题**：`_MIN_TIER2_TITLE` 由 5 降到 4，支持「星海列车」这类 4 字标题进入同标题异作者层；仍拦截 2 字通用名（数学/英语）。
- **副本序号后缀**：`Economics in One Lesson (1)` 与原名归为一组（仅一侧有数字括号时正常合并）。

### 4.4 API 与前端接入

- [library_management.py](file:///Users/yueqian/Desktop/code_mine/fnOS/ermao-library/apps/api-python/app/services/library_management.py) `duplicate_groups_page`：全量加载可见作品 → `build_duplicate_groups` 分组 → Python 分页 → `list_works_by_ids` 批量加载详情（分页后仅查当页作品 ID）。
- [works.py](file:///Users/yueqian/Desktop/code_mine/fnOS/ermao-library/apps/api-python/app/modules/library/infrastructure/works.py) 新增 `list_works_by_ids`：按输入顺序批量返回可见作品，缺 ID 静默丢弃。
- 前端「重复作品治理」面板描述文案更新，i18n（zh-CN / en-US）同步。

### 4.5 测试

新增 [test_duplicate_detection.py](file:///Users/yueqian/Desktop/code_mine/fnOS/ermao-library/apps/api-python/tests/test_duplicate_detection.py) 共 15 个用例：

- Tier 1 需标题+作者同时相同；Tier 2 同标题异作者（含短标题、通用名拦截）；
- Tier 3 去版本标记（th Edition、尾部第2版、纯数字括号保留为卷号）；
- Tier 4a 副本序号合并、不同卷号不合并；Tier 4b 不同翻译共享书名核心、出版社片段不误判；
- `duplicate_title_key` 辅助函数（第2版句中剥离、Z-Library 剥离等）。

---

## 5. 文件改动清单

| 文件 | 改动 |
|---|---|
| `apps/api-python/app/modules/imports/infrastructure/orchestration_services.py` | `list_sibling_files` 去重复 `resolve()` |
| `apps/api-python/app/modules/imports/application/work_grouping.py` | 去重复 `strip()`/`resolve()`；修复函数缩进 |
| `apps/api-python/app/modules/imports/application/import_audio.py` | 分组循环预计算 `resolved_items` + frozenset |
| `apps/api-python/app/services/book_identity.py` | 8 个正则模块级化 |
| `apps/api-python/app/modules/imports/application/identity_policy.py` | 5 个正则模块级化 |
| `apps/api-python/app/modules/imports/application/identity_resolution.py` | `_identity_key`/`_clean_value` 正则模块级化 |
| `apps/api-python/app/modules/imports/application/import_support.py` | `_MISSING_AUTHOR_KEYS` frozenset |
| `apps/api-python/app/modules/library/application/duplicate_detection.py` | **新增** 四层查重算法 |
| `apps/api-python/app/modules/library/infrastructure/works.py` | **新增** `list_works_by_ids` 批量查询 |
| `apps/api-python/app/services/library_management.py` | `duplicate_groups_page` 接入四层查重 |
| `apps/api-python/tests/test_duplicate_detection.py` | **新增** 15 个查重用例 |
| `apps/web/features/organize/duplicate-management-panel.tsx` | 面板描述文案 |
| `apps/web/i18n/messages/zh-CN.json` / `en-US.json` | 查重面板文案翻译 |

---

## 6. 风险与规避

| 风险 | 等级 | 规避 |
|---|---|---|
| 查重分组内存占用（全量加载） | 低 | 100k 作品规模下分组算法为线性和有界分桶（桶上限 300），集成测试 `test_management_query_scaling.py` 覆盖分页有界 |
| 模糊匹配误并（不同分册） | 低 | 尾部数字括号卷号比对 + 书名核心剔除出版社/国家片段 + 15 个定向用例 |
| 正则预编译与字符串模式差异 | 无 | 编译后正则行为等价；全量回归通过 |
| 常量定义顺序 NameError | 低 | `_MISSING_AUTHOR_KEYS` 置于 `_normalize_key` 之后；单测与编译检查拦截 |

---

## 7. 完成标准（Definition of Done）

- [x] 任务 A：导入管线 7 处热路径优化，行为不变（全量回归 972 passed / 5 skipped）
- [x] 任务 B：四层查重算法 + API 接入 + 前端文案 + 15 个测试用例
- [x] i18n 目录生成检查通过（`node scripts/generate-i18n-catalog.mjs`）
- [x] 无业务行为变更（性能项）；查重面板按新算法返回分组与置信度
