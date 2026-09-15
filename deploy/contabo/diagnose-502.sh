#!/usr/bin/env bash
# Run on the Contabo VPS from deploy/contabo/
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "FAIL: missing .env (cp .env.example .env first)"
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

echo "== compose ps =="
docker compose ps -a || true

echo
echo "== find frontend container =="
FE=""
if docker inspect securo-frontend >/dev/null 2>&1; then
  FE=securo-frontend
elif docker inspect securo-frontend-1 >/dev/null 2>&1; then
  FE=securo-frontend-1
  echo "WARN: found $FE (Compose default name)."
  echo "      Pull latest deploy/contabo (container_name: securo-frontend) and recreate."
else
  echo "FAIL: neither securo-frontend nor securo-frontend-1 exists"
  echo "  → docker compose up -d --build"
  exit 1
fi
docker inspect "$FE" --format 'name={{.Name}} status={{.State.Status}} networks={{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'
docker inspect "$FE" --format 'ports={{json .NetworkSettings.Ports}}'

echo
echo "== discover likely tunnel network =="
echo "Looking for cloudflared / known app containers..."
for c in cloudflared cloudflared-1 tunnel Cloudflare-tunnel n8n n8n-1 fire-monitor-agro agromonitor-edge somosagro-web; do
  if docker inspect "$c" >/dev/null 2>&1; then
    echo "--- $c ---"
    docker inspect "$c" --format '{{range $k, $v := .NetworkSettings.Networks}}{{println $k}}{{end}}'
  fi
done
echo "All containers (name):"
docker ps --format '{{.Names}}' | head -40

echo
echo "== CLOUDFLARE_TUNNEL_NETWORK={{CLOUDFLARE_TUNNEL_NETWORK:-unset}} =="
NET="${CLOUDFLARE_TUNNEL_NETWORK:-}"
if [[ -z "$NET" || "$NET" == change-me* ]]; then
  echo "FAIL: .env still has placeholder CLOUDFLARE_TUNNEL_NETWORK"
  echo "  Pick a network shared with cloudflared from the list above, then:"
  echo "    nano .env   # set CLOUDFLARE_TUNNEL_NETWORK=..."
  echo "    docker compose up -d"
  exit 1
fi

if ! docker network inspect "$NET" >/dev/null 2>&1; then
  echo "FAIL: docker network '$NET' not found"
  docker network ls
  exit 1
fi

ON_NET=$(docker inspect "$FE" --format "{{index .NetworkSettings.Networks \"$NET\"}}" || true)
if [[ -z "$ON_NET" || "$ON_NET" == "<no value>" ]]; then
  echo "FAIL: $FE is NOT attached to network '$NET'"
  echo "  Current networks:"
  docker inspect "$FE" --format '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}'
  echo "  → set CLOUDFLARE_TUNNEL_NETWORK correctly and: docker compose up -d --force-recreate frontend"
  exit 1
fi
echo "OK: $FE is on $NET"

echo
echo "== HTTP from tunnel network → ${FE}:8080 =="
if docker run --rm --network "$NET" curlimages/curl:8.5.0 -sS -o /dev/null -w "HTTP %{http_code}\n" --connect-timeout 5 "http://${FE}:8080/"; then
  :
else
  echo "FAIL: cannot reach http://${FE}:8080 from network $NET"
  exit 1
fi

echo
echo "== Cloudflare checklist =="
echo "Public hostname financas.agromei.com.br must be:"
echo "  http://securo-frontend:8080   (after recreate with container_name)"
echo "  OR temporarily: http://${FE}:8080"
echo "NOT http://agromonitor-edge:80"
echo
echo "Local checks OK for $FE on $NET."
