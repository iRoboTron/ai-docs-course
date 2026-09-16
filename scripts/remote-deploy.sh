#!/usr/bin/env bash
# Выполняется ВНУТРИ контейнера с nginx. Разворачивает новый релиз и переключает
# симлинк docroot атомарно; при любой ошибке возвращает предыдущий релиз и vhost.
# Аргументы: <домен> <id релиза> <путь к архиву>
set -euo pipefail

site=$1 id=$2 archive=$3
docroot="/var/www/sites/$site"
release="/var/www/releases/$site/$id"
vhost="/etc/nginx/sites-enabled/$site"
backup="/tmp/$id.vhost-backup"
legacy="/var/www/releases/$site/legacy-$id"

old_target=''
old_vhost=0
switched=0
legacy_moved=0

[[ -L "$docroot" ]] && old_target=$(readlink "$docroot")
if [[ -e "$vhost" || -L "$vhost" ]]; then cp -a "$vhost" "$backup"; old_vhost=1; fi

rollback() {
  status=$?
  if [[ "$status" != 0 ]]; then
    [[ "$switched" == 1 ]] && rm -f "$docroot"
    if [[ "$legacy_moved" == 1 ]]; then
      mv "$legacy" "$docroot"
    elif [[ "$switched" == 1 && -n "$old_target" ]]; then
      ln -s "$old_target" "$docroot"
    fi
    rm -f "$vhost"
    [[ "$old_vhost" == 1 ]] && cp -a "$backup" "$vhost"
    nginx -t && systemctl reload nginx || true
    echo 'Деплой не удался: предыдущий релиз и vhost восстановлены.' >&2
  fi
  rm -f "$archive" "$backup" "$docroot.next-$id"
  exit "$status"
}
trap rollback EXIT

mkdir -p "$release" "$(dirname "$docroot")"
tar xzf "$archive" -C "$release"
find "$release" -type d -exec chmod 755 {} +
find "$release" -type f -exec chmod 644 {} +

# Пишем новый обычный файл: старый vhost может быть симлинком, его цель трогать нельзя.
# /api/ уходит в прослойку к OpenRouter (сервис ai9-proxy, ставится setup-proxy.sh):
# так у учеников один адрес и один сертификат на уроки и на обращения к модели.
rm -f "$vhost"
cat > "$vhost" <<VHOST
server {
 listen 80;
 server_name $site;
 root $docroot;
 index index.html;
 location / { try_files \$uri \$uri/ =404; }
 location /api/ {
  proxy_pass http://127.0.0.1:8099;
  proxy_set_header Host \$host;
  proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
  proxy_read_timeout 180s;
  # Потоковый ответ (тема 10): не копить куски у себя и передать дальше заголовок
  # X-Accel-Buffering от прослойки — иначе внешний прокси (NPM) соберёт весь ответ целиком.
  proxy_buffering off;
  proxy_pass_header X-Accel-Buffering;
 }
}
VHOST
nginx -t

ln -s "$release" "$docroot.next-$id"
if [[ -d "$docroot" && ! -L "$docroot" ]]; then mv "$docroot" "$legacy"; legacy_moved=1; fi
mv -Tf "$docroot.next-$id" "$docroot"
switched=1
systemctl reload nginx

# Старые релизы: держим последние 5, остальное убираем.
#
# Сортируем по ИМЕНИ (оно вида 20260911-062723, то есть само по себе дата), а не по
# времени изменения: tar восстанавливает каталогам их прежние даты, поэтому свежий
# релиз выглядит для `ls -t` самым старым — и однажды был удалён сразу после выкладки.
# Плюс отдельно исключаем текущий релиз: то, на что смотрит docroot, не удаляем никогда.
for old in $(ls -1d "/var/www/releases/$site"/*/ 2>/dev/null | sort -r | tail -n +6); do
  case "$(basename "$old")" in
    "$id") continue ;;
    *) rm -rf -- "$old" ;;
  esac
done

# Дымовые проверки: сайт должен реально отдавать ключевые файлы.
# reload у nginx асинхронный — старые воркеры доживают запросы ещё пару секунд
# и отдают 404 по старому docroot, поэтому каждый путь проверяем с повторами.
proverit() {
  local path=$1 code=''
  for _ in $(seq 1 15); do
    code=$(curl --silent --max-time 15 --output /dev/null \
                --write-out '%{http_code}' "http://127.0.0.1/$path" -H "Host: $site" || echo 000)
    [[ "$code" == 200 ]] && { echo "  $path: $code"; return 0; }
    sleep 1
  done
  echo "$path: ожидался 200, получен $code" >&2
  return 1
}

for path in index.html reader.html reader-links.js files.json \
            vendor/marked.min.js 01-llm-osnovy/book.md \
            labs/tema1-llm-osnovy/01_tokeny.py \
            labs/tema1-llm-osnovy/01_tokeny.ipynb; do
  proverit "$path"
done
