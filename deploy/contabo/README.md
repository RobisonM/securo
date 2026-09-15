# Securo na Contabo (Docker)

Deploy do **Securo Brasil V1** (`feature/finance-br`) na mesma VPS que suas outras stacks Docker.

- Build a partir deste repositório (não usa `ghcr.io/securo-finance/*` — essas imagens ainda não têm o código BR).
- Frontend só em `127.0.0.1:<FRONTEND_PORT>` para não brigar com NPM/Traefik/Caddy nas portas 80/443.
- Backend, Postgres e Redis ficam só na rede interna do Compose.
- Agents/MCP desligados por padrão (menos RAM).

## Pré-requisitos na VPS

- Docker Engine + Docker Compose v2
- Reverse proxy já rodando (Nginx Proxy Manager, Traefik, Caddy, etc.)
- Domínio DNS apontando para o IP da Contabo
- Git

## 1. Clone

```bash
sudo mkdir -p /opt/apps
cd /opt/apps
git clone -b feature/finance-br https://github.com/RobisonM/securo.git
cd securo
mkdir -p secrets
cd deploy/contabo
```

## 2. Ambiente

```bash
cp .env.example .env
nano .env   # ou vim
```

Obrigatório ajustar:

| Variável | Exemplo |
|----------|---------|
| `SECRET_KEY` | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | `openssl rand -hex 24` |
| `FRONTEND_URL` | `https://securo.seudominio.com` (sem barra final) |
| `FRONTEND_PORT` | `3132` (livre no host; só loopback) |

`TRUSTED_PROXY_HOPS=2` assume: **Internet → NPM/Traefik → nginx do frontend → backend**.  
Se o TLS terminar direto no container frontend, use `1`.

## 3. Subir

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f backend
```

Aguarde `alembic upgrade head` e o Uvicorn no backend. O frontend escuta em `127.0.0.1:3132` (ou a porta do `.env`).

## 4. Reverse proxy

### Nginx Proxy Manager

1. **Hosts → Proxy Hosts → Add Proxy Host**
2. **Domain:** `securo.seudominio.com`
3. **Scheme:** `http`
4. **Forward Hostname / IP:** `127.0.0.1` (ou `host.docker.internal` / IP da bridge do host, se o NPM estiver em outro container sem `network_mode: host`)
5. **Forward Port:** `3132` (seu `FRONTEND_PORT`)
6. **SSL:** Let’s Encrypt, force SSL
7. Websockets: ligado (recomendado)

Se o NPM não alcançar `127.0.0.1` do host (container isolado), use o IP do gateway Docker do host (ex.: `172.17.0.1`) ou coloque o NPM na mesma rede externa e publique o frontend nessa rede — o padrão deste compose é loopback no host.

### Traefik (labels)

Este compose não adiciona labels Traefik por padrão (mantém o stack simples). Opções:

1. Proxy no Traefik apontando para `http://127.0.0.1:3132`, ou
2. Adicione um `docker-compose.override.yml` local com labels no serviço `frontend` e uma rede externa `traefik` (não versionar secrets).

### Caddy

Exemplo no `Caddyfile` do host:

```caddy
securo.seudominio.com {
  reverse_proxy 127.0.0.1:3132
}
```

## 5. Validação

1. Abra `https://securo.seudominio.com`
2. Crie conta / workspace
3. Confirme dashboard vazio (CTA de import) e depois um import sintético

```bash
curl -sI http://127.0.0.1:3132 | head -n 5
docker compose exec backend alembic current
```

## 6. Atualizar

```bash
cd /opt/apps/securo
git fetch origin
git checkout feature/finance-br
git pull --ff-only origin feature/finance-br
cd deploy/contabo
docker compose up -d --build
```

Volumes (`pgdata`, `attachments`) são preservados.

## 7. Backup rápido

```bash
# Postgres
docker compose exec -T db pg_dump -U postgres securo | gzip > securo-$(date +%F).sql.gz

# Anexos (volume Docker)
docker run --rm -v securo_attachments:/data -v "$PWD":/backup alpine \
  tar czf /backup/securo-attachments-$(date +%F).tar.gz -C /data .
```

O nome do volume pode incluir o project name (`securo_attachments`). Confira com `docker volume ls | grep securo`.

## 8. Parar / remover (cuidado)

```bash
docker compose down          # mantém volumes
docker compose down -v       # APAGA banco e anexos
```

## Layout de portas

| Serviço | Host | Interno |
|---------|------|---------|
| frontend | `127.0.0.1:FRONTEND_PORT` | 8080 |
| backend | — | 8000 |
| db | — | 5432 |
| redis | — | 6379 |
| celery | — | — |

## Segurança

- Não commitar `.env` (já coberto pelo `.gitignore` raiz).
- Não publicar Postgres/backend em `0.0.0.0`.
- Troque `SECRET_KEY` e `POSTGRES_PASSWORD` antes do primeiro `up`.
- PEM Enable Banking (se usar): `../../secrets/enable_banking_private.pem`.

## Agents (opcional)

Só se a VPS tiver RAM de sobra:

```bash
# no .env
AGENTS_ENABLED=true
AGENTS_MCP_JWT_SECRET=$(openssl rand -hex 32)
COMPOSE_PROFILES=agents

docker compose --profile agents up -d --build
```
