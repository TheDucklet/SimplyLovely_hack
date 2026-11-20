#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'TEXT'
Выкладка стенда ГеоСтарт одной командой.

  scripts/deploy_stand.sh [--tag main] [--data архив.zip] [--images архив.tar.gz] [--no-pull]

  --tag      тег образов в ghcr.io/theducklet/geostart-api и -web, по умолчанию main
  --data     архив данных из python -m geostart.release package, распаковывается в data/
  --images   архив образов из docker save вместо реестра
  --no-pull  взять образы, уже загруженные на сервер

Переменные: GEOSTART_COMPOSE (compose.vps.yml), GEOSTART_VPS_PORT (8081),
GEOSTART_IMAGE_PREFIX (ghcr.io/theducklet/geostart), PYTHON (python3).
TEXT
}

TAG=main
DATA_ARCHIVE=""
IMAGES_ARCHIVE=""
PULL=1
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG="$2"; shift 2 ;;
    --data) DATA_ARCHIVE="$2"; shift 2 ;;
    --images) IMAGES_ARCHIVE="$2"; PULL=0; shift 2 ;;
    --no-pull) PULL=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Неизвестный параметр $1" >&2; usage >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
COMPOSE_FILE="${GEOSTART_COMPOSE:-compose.vps.yml}"
PORT="${GEOSTART_VPS_PORT:-8081}"
PREFIX="${GEOSTART_IMAGE_PREFIX:-ghcr.io/theducklet/geostart}"
PYTHON="${PYTHON:-python3}"
BASE="http://127.0.0.1:${PORT}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DATA_BACKUP=""

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

step() {
  echo "==> $*"
}

if [ -n "$IMAGES_ARCHIVE" ]; then
  step "Загрузка образов из $IMAGES_ARCHIVE"
  gunzip -c "$IMAGES_ARCHIVE" | docker load
fi

if [ "$PULL" -eq 1 ]; then
  export GEOSTART_API_IMAGE="${PREFIX}-api:${TAG}"
  export GEOSTART_WEB_IMAGE="${PREFIX}-web:${TAG}"
  step "Загрузка образов ${GEOSTART_API_IMAGE} и ${GEOSTART_WEB_IMAGE}"
  docker pull "$GEOSTART_API_IMAGE"
  docker pull "$GEOSTART_WEB_IMAGE"
else
  export GEOSTART_API_IMAGE="${GEOSTART_API_IMAGE:-geostart-demo-api}"
  export GEOSTART_WEB_IMAGE="${GEOSTART_WEB_IMAGE:-geostart-demo-web}"
fi
docker image inspect protomaps/go-pmtiles:v1.31.2 >/dev/null 2>&1 || docker pull protomaps/go-pmtiles:v1.31.2

remember_running() {
  local service="$1"
  local container
  container="$(compose ps -q "$service" 2>/dev/null || true)"
  if [ -n "$container" ]; then
    docker tag "$(docker inspect --format '{{.Image}}' "$container")" "geostart-rollback-${service}:latest"
    echo "geostart-rollback-${service}:latest"
  fi
}

ROLLBACK_API="$(remember_running api)"
ROLLBACK_WEB="$(remember_running web)"

rollback() {
  echo "Выкладка не прошла проверку, возврат прежней версии" >&2
  compose logs --tail 40 api >&2 || true
  if [ -n "$DATA_BACKUP" ]; then
    for item in processed scores manifest.json; do
      if [ -e "$DATA_BACKUP/$item" ]; then
        rm -rf "data/$item"
        cp -a "$DATA_BACKUP/$item" "data/$item"
      fi
    done
  fi
  if [ -n "$ROLLBACK_API" ] && [ -n "$ROLLBACK_WEB" ]; then
    GEOSTART_API_IMAGE="$ROLLBACK_API" GEOSTART_WEB_IMAGE="$ROLLBACK_WEB" \
      docker compose -f "$COMPOSE_FILE" up -d --wait --wait-timeout 300 || true
  fi
  exit 1
}

if [ -n "$DATA_ARCHIVE" ]; then
  if [ -f "${DATA_ARCHIVE}.sha256" ]; then
    step "Проверка контрольной суммы архива данных"
    expected="$(cut -d' ' -f1 "${DATA_ARCHIVE}.sha256" | tr -d '\r')"
    actual="$(sha256sum < "$DATA_ARCHIVE" | cut -d' ' -f1)"
    if [ "$expected" != "$actual" ]; then
      echo "Контрольная сумма архива не совпадает, выкладка остановлена" >&2
      exit 1
    fi
  fi
  DATA_BACKUP="data/releases/stand-backup-${STAMP}"
  step "Резервная копия данных в ${DATA_BACKUP}"
  mkdir -p "$DATA_BACKUP"
  for item in processed scores manifest.json; do
    if [ -e "data/$item" ]; then
      cp -a "data/$item" "$DATA_BACKUP/"
    fi
  done
  step "Распаковка $DATA_ARCHIVE"
  "$PYTHON" -m zipfile -e "$DATA_ARCHIVE" .
  step "Сверка файлов данных с манифестом"
  compose run --rm --no-deps --entrypoint python api -m geostart.release verify || rollback
fi

step "Запуск стенда из $COMPOSE_FILE"
compose up -d --wait --wait-timeout 300 || rollback

expect() {
  local name="$1" url="$2" allowed="$3" code attempt
  for attempt in $(seq 1 "${GEOSTART_CHECK_ATTEMPTS:-15}"); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "$url" || true)"
    case " $allowed " in
      *" $code "*) echo "  $name: $code"; return 0 ;;
    esac
    sleep 2
  done
  echo "  $name: $code, ожидался $allowed" >&2
  return 1
}

step "Проверка стенда на $BASE"
expect "страница" "$BASE/" "200" || rollback
expect "API" "$BASE/api/v1/health" "200" || rollback
expect "данные" "$BASE/api/v1/cities" "200 401" || rollback
expect "подложка" "$BASE/basemap/tiles/geostart/10/618/320.mvt" "200" || rollback
expect "вход" "$BASE/api/auth/login" "303 307" || rollback
echo "  версия данных: $(curl -s "$BASE/api/v1/health")"
step "Стенд обновлён, образы ${GEOSTART_API_IMAGE} и ${GEOSTART_WEB_IMAGE}"
