#!/usr/bin/env bash
# Публикация курса на Proxmox (CT 109, nginx).
#
# Два режима доступа:
#   VIA=host   (по умолчанию) — ssh на хост pxhome, дальше pct push/exec в контейнер.
#                               Так удобно с ноутбука: доступ к контейнеру не нужен.
#   VIA=direct                 — ssh прямо в контейнер по LAN. Так работает CI-раннер.
#
# Примеры:
#   ./deploy-pxhome.sh                       # с ноутбука через хост
#   VIA=direct ./deploy-pxhome.sh            # из CI (раннер в CT 121)
#   ./deploy-pxhome.sh --build-only          # только собрать, никуда не выкладывать
set -euo pipefail

CTID="${CTID:-109}"
SITE_DIR="${SITE_DIR:-ai9.adelfos.ru}"
SSH_HOST="${SSH_HOST:-pxhome}"          # для VIA=host
CT_SSH="${CT_SSH:-root@192.168.0.109}"  # для VIA=direct
VIA="${VIA:-host}"
CHECK="${CHECK:-1}"                     # CHECK=0 — пропустить проверки (не рекомендуется)

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
[[ "$CTID" =~ ^[0-9]+$ ]] || { echo 'Некорректный CTID' >&2; exit 2; }
[[ "$SITE_DIR" =~ ^[a-z0-9]+([.-][a-z0-9]+)+$ ]] || { echo 'Некорректный SITE_DIR' >&2; exit 2; }

STAGE=$(mktemp -d -t ai9.XXXXXXXX)
REMOTE_STAGE=''
cleanup() {
  rm -rf -- "$STAGE"
  if [[ -n "$REMOTE_STAGE" ]]; then
    case "$VIA" in
      host) ssh "$SSH_HOST" "rm -rf -- '$REMOTE_STAGE'" || true ;;
      direct) ssh "$CT_SSH" "rm -rf -- '$REMOTE_STAGE'" || true ;;
    esac
  fi
}
trap cleanup EXIT

cd "$ROOT_DIR"
[[ "$CHECK" == 1 ]] && python3 scripts/check_project.py

# Сборка: сайт — это ровно docs/books (уроки, читалка, лабы, vendor), без исходников репозитория.
mkdir -p "$STAGE/site"
tar -C docs/books --exclude='__pycache__' -cf - . | tar -C "$STAGE/site" -xf -
echo "Собрано файлов: $(find "$STAGE/site" -type f | wc -l)"

if [[ "${1:-}" == '--build-only' ]]; then
  [[ -n "${BUILD_DIR:-}" && ! -e "$BUILD_DIR" ]] || { echo 'Задай BUILD_DIR — новый пустой каталог' >&2; exit 2; }
  cp -r "$STAGE/site" "$BUILD_DIR"
  echo "Собрано в $BUILD_DIR; ничего не выложено."
  exit 0
fi
[[ $# == 0 ]] || { echo 'Использование: ./deploy-pxhome.sh [--build-only]' >&2; exit 2; }

tar czf "$STAGE/site.tar.gz" -C "$STAGE/site" .
RELEASE_ID="$(date -u +%Y%m%d-%H%M%S)"

case "$VIA" in
  host)
    REMOTE_STAGE=$(ssh "$SSH_HOST" 'mktemp -d -t ai9.XXXXXXXX')
    [[ "$REMOTE_STAGE" =~ ^/tmp/ai9\.[a-zA-Z0-9]+$ ]] || { echo 'Неожиданный каталог на хосте' >&2; exit 2; }
    scp -q "$STAGE/site.tar.gz" "$SSH_HOST:$REMOTE_STAGE/site.tar.gz"
    scp -q scripts/remote-deploy.sh "$SSH_HOST:$REMOTE_STAGE/remote-deploy.sh"
    ssh "$SSH_HOST" "bash -s -- '$CTID' '$SITE_DIR' '$RELEASE_ID' '$REMOTE_STAGE'" <<'HOST'
set -euo pipefail
ct=$1 site=$2 id=$3 stage=$4
pct push "$ct" "$stage/site.tar.gz" "/tmp/$id.tar.gz"
pct push "$ct" "$stage/remote-deploy.sh" "/tmp/$id-deploy.sh"
pct exec "$ct" -- bash "/tmp/$id-deploy.sh" "$site" "$id" "/tmp/$id.tar.gz"
pct exec "$ct" -- rm -f "/tmp/$id-deploy.sh"
HOST
    ;;
  direct)
    REMOTE_STAGE=$(ssh "$CT_SSH" 'mktemp -d -t ai9.XXXXXXXX')
    [[ "$REMOTE_STAGE" =~ ^/tmp/ai9\.[a-zA-Z0-9]+$ ]] || { echo 'Неожиданный каталог в контейнере' >&2; exit 2; }
    scp -q "$STAGE/site.tar.gz" "$CT_SSH:$REMOTE_STAGE/site.tar.gz"
    scp -q scripts/remote-deploy.sh "$CT_SSH:$REMOTE_STAGE/remote-deploy.sh"
    ssh "$CT_SSH" "bash '$REMOTE_STAGE/remote-deploy.sh' '$SITE_DIR' '$RELEASE_ID' '$REMOTE_STAGE/site.tar.gz'"
    ;;
  *) echo "Неизвестный VIA=$VIA (ожидается host или direct)" >&2; exit 2 ;;
esac

# Публичный HTTPS — отдельная проверка: успех по LAN не доказывает, что настроены DNS и сертификат.
if curl --fail --silent --show-error --max-time 20 --output /dev/null "https://$SITE_DIR/files.json"; then
  echo "Опубликовано: https://$SITE_DIR (CT $CTID, релиз $RELEASE_ID)."
else
  echo "Контейнер отдаёт сайт, но https://$SITE_DIR снаружи недоступен." >&2
  echo "Проверь DNS-запись и proxy host в Nginx Proxy Manager (CT 101) — см. README." >&2
fi
