#!/usr/bin/env bash
# Run on the Contabo VPS from deploy/contabo/
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "FAIL: missing .env (cp .env.example .env first)"
  exit 1
fi

# shellcheck disable=SC1091
set -a
# shellcheck source=/dev/null
source .env
set +a

echo "== compose ps =="
docker compose ps || true

echo
echo "== container securo-frontend =="
if ! docker inspect securo-frontend >/dev/null 2>&1; then
  echo "FAIL: container securo-frontend does not exist"
  echo "  → docker compose up -d --build"
  exit 1
fi
docker inspect securo-frontend --format 'status={{.State.Status}} networks={{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'

echo
echo "== CLOUDFLARE_TUNNEL_NETWORK={{CLOUDFLARE_TUNNEL_NETWORK:-unset}} =="
NET="${CLOUDFLARE_TUNNEL_NETWORK:-}"
if [[ -z "$NET" || "$NET" == change-me* ]]; then
  echo "FAIL: set CLOUDFLARE_TUNNEL_NETWORK in .env to the network cloudflared/n8n use"
  echo "  Hint:"
  echo "    docker inspect n8n --format '{{range \$k,\$v := .NetworkSettings.Networks}}{{println \$k}}{{end}}'"
  exit 1
fi

if ! docker network inspect "$NET" >/dev/null 2>&1; then
  echo "FAIL: docker network '$NET' not found"
  docker network ls
  exit 1
fi

ON_NET=$(docker inspect securo-frontend --format "{{index .NetworkSettings.Networks \"$NET\"}}" || true)
if [[ -z "$ON_NET" || "$ON_NET" == "<no value>" ]]; then
  echo "FAIL: securo-frontend is NOT attached to network '$NET'"
  echo "  → fix CLOUDFLARE_TUNNEL_NETWORK and: docker compose up -d"
  exit 1
fi
echo "OK: securo-frontend is on $NET"

echo
echo "== DNS from tunnel network → securo-frontend:8080 =="
if docker run --rm --network "$NET" curlimages/curl:8.5.0 -sS -o /dev/null -w "HTTP %{http_code}\n" --connect-timeout 5 "http://securo-frontend:8080/"; then
  :
else
  echo "FAIL: cannot reach http://securo-frontend:8080 from network $NET"
  echo "  Cloudflare will show Error 502 until this works."
  exit 1
fi

echo
echo "== backend health via frontend /api (optional) =="
docker run --rm --network "$NET" curlimages/curl:8.5.0 -sS -o /dev/null -w "HTTP %{http_code}\n" --connect-timeout 5 "http://securo-frontend:8080/api/health" || true

echo
echo "== Cloudflare checklist =="
echo "Public hostname financas.agromei.com.br must be:"
echo "  http://securo-frontend:8080"
echo "NOT http://agromonitor-edge:80"
echo
echo "All local checks OK. If browser still 502, wait ~30s after CF edit or check cloudflared logs:"
echo "  docker logs cloudflared --tail 100"
