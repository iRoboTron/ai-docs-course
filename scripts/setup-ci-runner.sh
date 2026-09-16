#!/usr/bin/env bash
# Одноразовая настройка автодеплоя. Запускать со своей машины: нужны ssh-алиас pxhome
# и авторизованный gh. Скрипт идемпотентный — повторный запуск ничего не сломает.
#
# Что делает:
#   1. Разрешает CI-раннеру (CT 121) заходить по ssh в контейнер сайта (CT 109).
#   2. Ставит в CT 121 второй экземпляр GitHub-раннера для этого репозитория
#      с меткой ai9 и поднимает его как systemd-сервис.
#
# Существующий раннер репозитория web-agent не трогается: это отдельный каталог,
# отдельный сервис и отдельная регистрация.
set -euo pipefail

REPO="${REPO:-iRoboTron/ai-docs-course}"
RUNNER_CT="${RUNNER_CT:-121}"
SITE_CT="${SITE_CT:-109}"
LABEL="${LABEL:-ai-docs}"
RUNNER_DIR="${RUNNER_DIR:-/opt/actions-runner-ai-docs}"
RUNNER_NAME="${RUNNER_NAME:-ai-docs-pxhome}"

echo "== 1/3 Ключ раннера в контейнер сайта (CT $SITE_CT) =="
PUBKEY=$(ssh pxhome "pct exec $RUNNER_CT -- ssh-keygen -y -f /root/.ssh/id_ed25519")
[[ "$PUBKEY" == ssh-* ]] || { echo 'Не удалось получить публичный ключ раннера' >&2; exit 1; }

ssh pxhome "pct exec $SITE_CT -- bash -s" <<REMOTE
set -euo pipefail
mkdir -p /root/.ssh && chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
if grep -qF '$PUBKEY' /root/.ssh/authorized_keys; then
  echo '  ключ уже есть'
else
  echo '$PUBKEY' >> /root/.ssh/authorized_keys
  echo '  ключ добавлен'
fi
REMOTE

echo "== 2/3 Проверка ssh раннер -> сайт =="
ssh pxhome "pct exec $RUNNER_CT -- ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
  root@192.168.0.$SITE_CT 'echo \"  ok: \$(hostname)\"'"

echo "== 3/3 Регистрация раннера для $REPO =="
# Признак завершённой регистрации — .credentials: он появляется только после
# успешного config.sh. Файлы .runner / .runner_migrated могут остаться от копии
# соседнего раннера и о регистрации ничего не говорят.
if ssh pxhome "pct exec $RUNNER_CT -- test -f $RUNNER_DIR/.credentials" 2>/dev/null; then
  echo "  раннер уже зарегистрирован в $RUNNER_DIR — пропускаю"
else
  TOKEN=$(gh api -X POST "repos/$REPO/actions/runners/registration-token" -q '.token')
  [[ -n "$TOKEN" ]] || { echo 'Не удалось получить токен регистрации' >&2; exit 1; }

  ssh pxhome "pct exec $RUNNER_CT -- bash -s" <<REMOTE
set -euo pipefail
dir='$RUNNER_DIR'
mkdir -p "\$dir"
if [[ ! -f "\$dir/config.sh" ]]; then
  # Берём ту же версию раннера, что уже работает рядом, чтобы не тянуть новую.
  cp -a /opt/actions-runner/. "\$dir/"
fi
cd "\$dir"
# Следы чужой регистрации, скопированные вместе с каталогом. Без этого config.sh
# говорит "already configured": у свежих версий маркер — .runner_migrated,
# у старых — .runner, поэтому убираем оба.
rm -rf _work _diag .runner .runner_migrated .credentials .credentials_rsaparams .service

# У соседнего раннера bin и externals — АБСОЛЮТНЫЕ симлинки в /opt/actions-runner.
# После копирования они продолжают указывать туда же, поэтому запускались бы
# бинарники соседа, а он определяет свой каталог по расположению бинарника и
# видит ЧУЖУЮ регистрацию — отсюда "already configured". Переводим на свои копии.
for link in \$(find . -maxdepth 1 -type l); do
  target=\$(readlink "\$link")
  case "\$target" in
    /opt/actions-runner/*)
      local_target=\$(basename "\$target")
      [[ -e "\$local_target" ]] || { echo "нет своей копии \$local_target" >&2; exit 1; }
      ln -sfn "\$local_target" "\$link"
      echo "  \$link -> \$local_target (было \$target)"
      ;;
  esac
done
# config.sh не запускается от root без этого флага.
RUNNER_ALLOW_RUNASROOT=1 ./config.sh \
  --unattended --replace \
  --url 'https://github.com/$REPO' \
  --token '$TOKEN' \
  --name '$RUNNER_NAME' \
  --labels '$LABEL' \
  --work _work
./svc.sh install root
./svc.sh start
sleep 3
./svc.sh status | head -5
REMOTE
fi

echo
echo "Готово. Теперь push в main запускает проверки и публикацию."
echo "Раннеры репозитория: gh api repos/$REPO/actions/runners -q '.runners[].name'"
