#!/usr/bin/env bash
# 一隅书架（booknook）Docker 部署一键升级
#
# 原理：
#   生产 compose 引用浮动镜像 "kylenge/booknook:prod"，且 pull_policy: always，
#   因此升级只需拉取最新镜像并重建容器，数据（/app/storage、/monitor）全部保留，
#   无需卸载、无需重新打包 fpk。
#
# 用法：
#   scripts/upgrade-docker.sh                      # 在 compose 文件目录运行
#   scripts/upgrade-docker.sh -f /path/to/docker-compose.prod.yml
#   scripts/upgrade-docker.sh --stack-name booknook
#
# 可选环境变量：
#   COMPOSE_FILE    compose 文件路径（默认 ./docker-compose.prod.yml）
#   STACK_NAME      compose 项目名（默认 booknook）

set -Eeuo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
STACK_NAME="${STACK_NAME:-booknook}"

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "未找到 compose 文件：$COMPOSE_FILE" >&2
  echo "请先进入包含 docker-compose.prod.yml 的目录，或设置 COMPOSE_FILE。" >&2
  exit 1
fi

echo "==> 拉取镜像 kylenge/booknook:prod"
docker compose -f "$COMPOSE_FILE" -p "$STACK_NAME" pull web

echo "==> 重建容器（数据卷保留）"
docker compose -f "$COMPOSE_FILE" -p "$STACK_NAME" up -d --no-deps web

echo "==> 等待健康检查…"
docker compose -f "$COMPOSE_FILE" -p "$STACK_NAME" ps

echo "升级完成。请打开 http://<NAS地址>:${WEB_PORT:-7209} 访问。"