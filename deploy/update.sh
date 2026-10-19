#!/bin/sh
# Бот ВК на своём сервере. Chat API и Redis остаются в своём Compose:
# события из Redis бот получает по WebSocket Chat API.
set -eu

cd "$(dirname "$0")/.."

if [ -z "${GIT_SHA:-}" ]; then
  echo "Не задан GIT_SHA." >&2
  exit 1
fi
if [ -z "${BOT_IMAGE:-}" ]; then
  echo "Не задан BOT_IMAGE." >&2
  exit 1
fi

git fetch origin "$GIT_SHA"
git checkout --detach --force "$GIT_SHA"

set_env() {
  key=$1
  value=$2
  tmp=$(mktemp)
  if [ -f .env ]; then
    grep -v "^${key}=" .env > "$tmp" || true
  else
    : > "$tmp"
  fi
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" .env
  chmod 600 .env
}

# Токены сообществ ВК из секрета ENV_FILE. Токены Telegram (123456:ABC...) пропускаются.
apply_secret_tokens() {
  secret_file=$(mktemp)
  vk_file=$(mktemp)
  if [ -n "${ENV_FILE_B64:-}" ]; then
    printf '%s' "$ENV_FILE_B64" | base64 -d | tr -d '\r' > "$secret_file"
  elif [ -n "${ENV_FILE:-}" ]; then
    printf '%s\n' "$ENV_FILE" | tr -d '\r' > "$secret_file"
  else
    rm -f "$secret_file" "$vk_file"
    return
  fi
  if [ ! -f .env ]; then
    : > .env
    chmod 600 .env
  fi
  while IFS= read -r line || [ -n "$line" ]; do
    line=$(printf '%s' "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    [ -z "$line" ] && continue
    case "$line" in
      \#*) continue ;;
      CHAT_API_SERVICE_TOKEN=*|CHAT_API_URL=*|CF_ACCESS_CLIENT_ID=*|CF_ACCESS_CLIENT_SECRET=*)
        key=${line%%=*}
        value=${line#*=}
        value=$(printf '%s' "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/^"//;s/"$//')
        [ -n "$value" ] && set_env "$key" "$value"
        continue
        ;;
    esac
    value=$line
    known=yes
    case "$line" in
      VK_TOKEN=*|VK_TOKENS=*)
        value=${line#*=}
        ;;
      *=*)
        value=${line#*=}
        known=no
        ;;
    esac
    old_ifs=$IFS
    IFS=',;'
    for part in $value; do
      token=$(printf '%s' "$part" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/^"//;s/"$//')
      [ -z "$token" ] && continue
      if printf '%s' "$token" | grep -Eq '^[0-9]{6,}:[A-Za-z0-9_-]{20,}$'; then
        continue
      fi
      if [ "$known" = yes ] || printf '%s' "$token" | grep -Eq '^vk[12]\.'; then
        printf '%s\n' "$token" >> "$vk_file"
      fi
    done
    IFS=$old_ifs
  done < "$secret_file"
  vk_sorted=$(mktemp)
  awk '!seen[$0]++' "$vk_file" > "$vk_sorted"
  vk_count=$(grep -c . "$vk_sorted" || true)
  echo "Из секрета: сообществ ВК ${vk_count}."
  if [ "$vk_count" -gt 0 ]; then
    first=$(sed -n '1p' "$vk_sorted")
    rest=$(sed -n '2,$p' "$vk_sorted" | paste -sd, -)
    set_env VK_TOKEN "$first"
    set_env VK_TOKENS "$rest"
  elif ! grep -qE '^VK_TOKEN=.+' .env 2>/dev/null; then
    echo "В секрете нет токена сообщества ВК, и в .env на сервере его тоже нет." >&2
    rm -f "$secret_file" "$vk_file" "$vk_sorted"
    exit 1
  else
    echo "В секрете нет токена ВК. Оставляю VK_TOKEN из .env на сервере."
  fi
  rm -f "$secret_file" "$vk_file" "$vk_sorted"
}

apply_secret_tokens

if ! grep -qE '^VK_TOKEN=.+' .env 2>/dev/null; then
  echo "Нет VK_TOKEN. Добавьте токен сообщества в секрет ENV_FILE." >&2
  exit 1
fi

if ! grep -qE '^CHAT_API_SERVICE_TOKEN=.+' .env 2>/dev/null; then
  echo "В секрете ENV_FILE нет CHAT_API_SERVICE_TOKEN." >&2
  exit 1
fi
if ! grep -qE '^CHAT_API_URL=.+' .env 2>/dev/null; then
  set_env CHAT_API_URL "https://api.chatwithyou.site"
fi
if grep -qE '^CHAT_API_URL=.*chatwithyou\.site' .env \
  && { ! grep -qE '^CF_ACCESS_CLIENT_ID=.+' .env || ! grep -qE '^CF_ACCESS_CLIENT_SECRET=.+' .env; }; then
  echo "Для https://api.chatwithyou.site в ENV_FILE нужны CF_ACCESS_CLIENT_ID и CF_ACCESS_CLIENT_SECRET." >&2
  exit 1
fi

set_env BOT_IMAGE "$BOT_IMAGE"

if [ -n "${DOCKERHUB_USERNAME:-}" ] && [ -n "${DOCKERHUB_TOKEN:-}" ]; then
  printf '%s' "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin
fi

docker compose pull bot
docker logout >/dev/null 2>&1 || true
# Старый контейнер принадлежал compose-проекту Chat API. Имя vk-bot занимаем здесь.
docker rm -f vk-bot >/dev/null 2>&1 || true
docker compose up -d --no-build --force-recreate bot

sleep 8
docker logs vk-bot --tail 80 2>&1 | grep -E "Токенов ВК|VK:|Chat API|WebSocket|пропущен|Нет доступа|Токен невалиден|Бот запущен|Ошибка запуска|VK Error|Traceback" || true

current_tag=${BOT_IMAGE##*:}
docker images --format '{{.Repository}}:{{.Tag}}' | grep '/dating-bot:' | grep -v ':local$' | grep -v ":${current_tag}\$" \
  | xargs -r docker rmi >/dev/null 2>&1 || true
