# 品牌改名开发文档：私人书库(booknook) → booknook / 私人书库

> 本文档是本仓库重新品牌化（re-brand）的唯一执行规范。所有内容替换、镜像发布、飞牛打包、GitHub 上传均按本文档执行。改动前请先通读本表。所有「新文本」基于已核对的实际源码。

## 1. 目标与决策

| 决策项 | 结论 |
|--------|------|
| 新英文项目标识 / 仓库名 | `booknook` |
| 新中文产品名（替换「私人书库」） | `私人书库` |
| 改名彻底程度 | 彻底改（含 npm scope、移动端标识、运行时路径、fnOS 应用标识） |
| Docker 镜像 | `rubyfrost101/booknook` → `rubyfrost101/booknook`（自行构建推送，**仓库名统一为 `booknook`**） |
| 历史 release-notes | 清空重来，从 v0.1.0 开始 |
| 目标 GitHub 仓库 | `rubyfrost101/booknook`（重新 init 干净仓库、去除原作者历史与 submodule） |
| 移动端 bundle id | `com.rubyfrost101.booknook` → `com.rubyfrost101.booknook` |
| 移动端 App 显示名 | `私人书库` → `私人书库` |
| fnOS 应用标识 | `booknook` → `booknook`（appname + 用户/组/项目/导航名联动，见 §3.4） |
| fnOS 共享扫描目录 | `booknook.monitor` → `booknook.monitor` |
| commit 作者身份 | 统一为 `rubyfrost101`（现本地 git 身份为 appleAngels，需改） |
| 数据策略 | **全新识别，不迁旧数据**：数据库/数据目录/共享扫描目录全改新名，原飞牛上的识别记录、阅读进度、偏好不沿用；原始书文件保留，装新版后重新扫描识别 |

## 2. 命名映射表（全程唯一标准）

以下字符串替换按「先精确后笼统」顺序执行。**第 8 步是镜像仓库名的一致性保证，必须先于通用 `booknook` 兜底**，否则 compose 与 publish 生成的镜像名会不一致。

| 优先级 | 旧文本 | 新文本 | 说明 / 实际落点 |
|----|--------|--------|------|
| 1 | `rubyfrost101/booknook` | `rubyfrost101/booknook` | 完整镜像引用（compose、build-fnos、workflow、deploy README） |
| 2 | `rubyfrost101/booknook:develop` | `rubyfrost101/booknook:develop` | CI workflow（已被 #1 覆盖，可省略） |
| 3 | `com.rubyfrost101.booknook` | `com.rubyfrost101.booknook` | mobile app.json: ios bundleIdentifier / android package |
| 4 | `BookNook` | `BookNook` | HTTP User-Agent（organize_service.py） |
| 5 | `@booknook/` | `@booknook/` | npm workspace scope（packages 内 import 引用、lockfile） |
| 6 | `私人书库` | `私人书库` | mobile app.json `expo.name` |
| 7 | `booknook` | `booknook` | **镜像仓库名一致性**：publish-docker-hub.sh 里 `build_image "booknook"` 与 echo |
| 8 | `booknook` | `booknook` | mobile slug/scheme、expo-private-file-system.ts 私有根目录 |
| 9 | `booknook` | `booknook` | docker compose 容器名 |
| 10 | `booknook.sqlite3` | `booknook.sqlite3` | 数据库文件（新部署生效） |
| 11 | `--booknook-...` | `--booknook-...` | CSS 设计 token（reader-core 样式） |
| 12 | `booknook:locale` | `booknook:locale` | release-notes marker（历史清空；validate 脚本夹具保留该 token 值） |
| 13 | `rubyfrost101`（残余） | `rubyfrost101` | publish-docker-hub.sh `NAMESPACE` 默认值 `rubyfrost101` |
| 14 | `booknook` | `booknook` | 仓库标识（本地目录名除外，见 §边界） |
| 15 | `booknook` | `booknook` | compose 项目名、fnOS appname、打包目录名、.fpk 文件名、cmd/project label |
| 16 | `rubyfrost101` | `rubyfrost101` | 作者 GitHub 账号（URL、workflow filter） |
| 17 | `booknook.monitor` | `booknook.monitor` | fnOS 共享扫描目录（resource/wizard deploy README/build 断言） |
| 18 | `私人书库` | `私人书库` | 中文产品名（manifest/ui config/wizard/README/brand.ts/i18n） |
| 19 | `Ermao Books` / `20 cents` | `Private Library` | 英文文案字面量（i18n en-US） |
| 20 | `书库主`（残余） | `书库主`（按语境） | 用户名默认值 / 测试夹具 / Kindle 文案 |
| 21 | 兜底 `booknook` | `booknook` | 其余独立标识符（preference key、版本快照名等） |

> **边界**：本地工作目录 `/Users/yueqian/Desktop/code_mine/fnOS/booknook` 目录名不改（改会影响运行中的 dev、storage 路径、IDE）；GitHub 仓库名由 `gh repo create` 定为 `booknook`，与本地目录名解耦。容器内 `/monitor`、`/kavita` 等挂载路径是技术路径，**不改**。

## 3. 变动文件清单（按能力域分类）

### 3.1 纯展示 / 品牌文案（低风险，量大）
- `apps/web/lib/brand.ts` — `PRODUCT_NAME`、`PRODUCT_DESCRIPTION`、`PRODUCT_TAGLINE` 重写（原 "和书库主一起，安静读书" → 建议 "存你所藏，随时可读"）
- `README.md` / `README.en.md` — 标题 `# 私人书库（booknook)` → `# 私人书库（booknook)`；安装说明镜像/项目名/容器名；`pnpm --filter @booknook/web` → `@booknook/web`；作者/维护者信息
- `apps/api-python/README.md` — 标题与正文「私人书库」→「私人书库」；`booknook.sqlite3`→`booknook.sqlite3`
- `.github/ISSUE_TEMPLATE/bug_report_zh.yml` — 「私人书库」→「私人书库」
- `apps/web/i18n/messages/en-US.json` — Kindle 邮件「私人书库」→「私人书库」、"Ermao Books"/"20 cents"→"Private Library"
- `apps/api-python/app/services/email_settings.py` — `fromName` 默认「私人书库」→「私人书库」
- `apps/api-python/app/services/kindle_queue.py` — 发件名称与文案「私人书库」→「私人书库」；en-US 分支判断字面量同步
- `apps/web/components/layout/app-shell.tsx` — 默认用户名「书库主」→「书库主」（与 §2#20 一致）

### 3.2 代码 / 部署标识（中风险，改了影响构建）
- `docker-compose.yml` / `docker-compose.prod.yml` — 项目名 `booknook`→`booknook`、镜像→`rubyfrost101/booknook`、容器名→`booknook`
- `.github/workflows/fnos-package.yml`、`.github/workflows/mobile.yml` — 镜像 tags/images、`@booknook/*` filter→`@booknook/*`
- `scripts/publish-docker-hub.sh` — 第 8 行 `NAMESPACE="${DOCKERHUB_NAMESPACE:-${IMAGE_NAMESPACE:-rubyfrost101}}"`、`--namespace`/usage 默认 `rubyfrost101`、`build_image "booknook"` 与两处 echo 的镜像名（统一 `booknook`）
- `scripts/build-fnos-package.sh` — `IMAGE_REFERENCE="rubyfrost101/booknook:${APP_VERSION}"`、`PACKAGE_DIR="$BUILD_ROOT/booknook"`、maintainer/distributor（六面体→rubyfrost101）、output `booknook-${APP_VERSION}-all.fpk`，以及**校验断言**（含 `/booknook.monitor`、`projects booknook`、`label=com.docker.compose.project=booknook` 等强断言的预期值同步为新名）
- `apps/api-python/app/services/organize_service.py` — User-Agent `BookNook/0.1`→`BookNook/0.1`、GMD 链接→新仓库
- `apps/mobile/app.json` — `expo.name`（私人书库→私人书库）、`slug`/`scheme`→`booknook`、`bundleIdentifier`/`package`→`com.rubyfrost101.booknook`
- `apps/mobile/src/shared/files/expo-private-file-system.ts` — `booknook`→`booknook`

### 3.3 npm workspace scope（仅 3 个包，已核实）
- `apps/mobile/package.json` — `@booknook/mobile`→`@booknook/mobile`
- `apps/web/package.json` — `@booknook/web`→`@booknook/web`
- `packages/reader-core/package.json` — `@booknook/reader-core`→`@booknook/reader-core`
- 三者相互 `@booknook/...` 依赖引用同步；改后执行 `pnpm install` 重新生成 `pnpm-lock.yaml`

### 3.4 fnOS 打包（强联动，全部要一起改才过构建）
`appname=booknook` → `booknook` 会连带以下**同值**同步，缺一打包失败：
- `deploy/fnos/manifest` — `appname=booknook`→`booknook`、`display_name=私人书库`→`私人书库`、`maintainer/distributor=六面体`→`rubyfrost101`、`maintainer_url/distributor_url`→`github.com/rubyfrost101/booknook`、`desktop_applaunchname=booknook.main`→`booknook.main`、`desc` 与 `changelog` 中「私人书库」+B站/QQ群文案替换
- `deploy/fnos/config/privilege` — `username`/`groupname` `booknook`→`booknook`
- `deploy/fnos/config/resource` — `name: "booknook"`→`"booknook"`；共享目录 `name: "booknook.monitor"`→`"booknook.monitor"`（若保留旧共享目录名，则 #17 不改但 `booknook` 破残留，建议彻底改）
- `deploy/fnos/app/ui/config` — 桌面图标 key `booknook.main`→`booknook.main`、`title` 私人书库→私人书库
- `deploy/fnos/cmd/main` — `--filter "label=com.docker.compose.project=booknook"`→`...project=booknook`
- `deploy/fnos/wizard/install`、`wizard/upgrade` — 「初始化/升级私人书库」→私人书库；「/booknook.monitor」→「/booknook.monitor」（3 个 JSON 均为严格 JSON，**无注释**）
- `deploy/fnos/README.md` — 文中「私人书库」「六面体/ＧＭＤ」「rubyfrost101」镜像、「booknook.monitor」全部同步

### 3.5 历史 release（按决策清空）
- 删除 `release-notes/v0.1.25.md ~ v0.5.1.md`
- 重建 `release-notes/index.json` 为单条初始记录（repository → `rubyfrost101/booknook`、versions 空或 v0.1.0 占位）

### 3.6 需人工改写（非纯替换）
- `brand.ts` 的 `TAGLINE`（重新创作）
- README「功能介绍 / 交流群 / 作者」段落——移除原作者 QQ 群 `154560969`、署名「六面体」，改为你本人
- 中文文案残余「书库主」（按语境改「书库主」或删）
- `release-notes/guides/release-changelog-guide.md` 这类编排说明中的归属

## 4. 执行步骤（顺序）

1. **停 dev server**（避免改名期间热重载干扰）。
2. **批量机械替换**：按 §2 优先级对全仓库文本文件执行 perl（排除 `.git`、`node_modules`、`.venv`、`storage`、`*.png/jpg/sqlite3/fpk/lock`）。
3. **改 npm scope**：更新 3 个 `package.json` 的 `name`/依赖 → `@booknook/*`，然后 `pnpm install` 重新生成 `pnpm-lock.yaml`。
4. **手工改写**：`brand.ts`、README 作者/群信息、`validate-release-notes.*` 断言、i18n en-US。
5. **清空 release-notes**（按 §3.5）。
6. **更新 fnOS 打包**：manifest + config(privilege/resource) + app/ui/config + cmd/main + wizard + deploy README + `build-fnos-package.sh` 全联动（§3.4）。
7. **更新镜像与 CI**：compose / workflow / `publish-docker-hub.sh`（§3.2）。
8. **验证**：参考 §5。
9. **重新 init 干净 git 仓库**，移除 `.git` 历史与 `.gitmodules`（submodule wiki），设 `origin` 指向 `git@github.com:rubyfrost101/booknook.git`，以 `rubyfrost101` 身份首次提交「Initial commit: rebrand to booknook / private library」。
10. **用 `gh repo create` 建 `rubyfrost101/booknook`**（private 或 public，你定）并推送。

## 5. 验证门禁

```bash
# 残留名称检查（应接近 0；目录名与已生成产物除外）
grep -rn --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv \
  -e "rubyfrost101" -e "rubyfrost101" -e "ermao" -e "@booknook" -e "书库主" -e "私人书库" \
  apps packages deploy scripts docker-compose*.yml 2>/dev/null

# JS/TS 质量门禁
pnpm --filter @booknook/web lint
pnpm --filter @booknook/web typecheck
pnpm --filter @booknook/web test
(cd apps/web && pnpm i18n:check)   # i18n:check 须在 apps/web 目录运行
pnpm test

# Python 门禁
cd apps/api-python && uv run ruff format --check . && uv run ruff check . && uv run mypy app

# 应用可启动（若你需要本地复验）
cd apps/api-python && STORAGE_ROOT=... uv run python -m app.db.bootstrap
# 统一网关健康
curl -s http://localhost:3000/api/health    # {"ok":true}
```

> 无残留但 `grep` 全量时 `pnpm-lock.yaml` 可能仍含旧 `@booknook` 字符串片段 —— 应以 `pnpm install` 重新生成后的 lock 为准（能用即视为通过）。

## 6. 新仓库起点

- **保留**：业务代码、`apps/*`、`packages/*`、`deploy/fnos`、`docs` 工程文档、`test-data`
- **移除**：`.git` 历史、`release-notes` 历史、`.gitmodules` + `booknook.wiki*`、原作者 GitHub 链接 / 群号码 / 「六面体」署名残留
- **LICENSE**：保留 **GPL-3.0**（fork 应保留原版权声明，避免法律问题；若你决定以 fork 方式自有署名，请自行确认）

## 7. 镜像自行构建与发布（部署前必做）

镜像已改为 `rubyfrost101/booknook`，NAS 部署前需先构建并推送一次：

```bash
# 方式 A（走项目脚本，namespace 默认已改为 rubyfrost101）
DOCKERHUB_USERNAME=rubyfrost101 DOCKERHUB_TOKEN=**** ./scripts/publish-docker-hub.sh --tag prod

# 方式 B（手动 build + push）
docker build -t rubyfrost101/booknook:latest .
docker push rubyfrost101/booknook:latest
```

> 镜像未推送前 `docker-compose up` 会拉取失败；本地开发走 `pnpm dev:test`（不用 Docker）不受影响。

## 8. 重新打包飞牛应用

```bash
pnpm fnos:build      # 或 scripts/build-fnos-package.sh，内部已用新 IMAGE_REFERENCE 与新断言
```
产物 `.fpk` 上传飞牛「应用中心 → 手动安装」。

## 9. 最终验收清单

- [ ] `grep` 残留旧名（rubyfrost101/GMD/ermao/@booknook/书库主/私人书库）无业务代码命中
- [ ] `docker-compose*.yml`、`.github/workflows/*`、`scripts/*`、`deploy/fnos/*` 全部指向新名
- [ ] **publish 推送的镜像名（booknook）与 compose 拉取的一致**
- [ ] fnOS 打包 5 处 `booknook` 联动（manifest/privilege/resource/ui/config/cmd/main）、`booknook.monitor→booknook.monitor`、build 脚本断言同步
- [ ] `pnpm install` 后 lockfile 无旧 `@booknook` 报错；`pnpm lint / typecheck / i18n:check` 通过
- [ ] mobile app.json：`name=私人书库`、`slug/scheme=booknook`、`bundle/package=com.rubyfrost101.booknook`
- [ ] `release-notes` 清空，index 指向 `rubyfrost101/booknook`
- [ ] git 为干净仓库（无原作者历史/submodule），commit 作者为 rubyfrost101，已推送 `rubyfrost101/booknook`
- [ ] README 作者/群/链接已替换为你本人，LICENSE 保留 GPL-3.0