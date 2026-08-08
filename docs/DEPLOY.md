# Deployment

Pythia runs anywhere Docker runs. This document covers the part that is not
obvious: making the dashboard reachable without opening a port to the internet.

---

## Local

```bash
cp .env.example .env
docker compose up -d
curl -s localhost:8300/api/status | python3 -m json.tool
```

`PYTHIA_PORT` in `.env` changes the host port. The container always listens on
8000 internally.

### Kalshi credentials

Kalshi signs requests with RSA-PSS. Generate a keypair, register the public half
at kalshi.com → Settings → API, and place the private half where the container
can read it:

```bash
mkdir -p data
cp ~/kalshi_private.pem data/kalshi_private.pem
chmod 600 data/kalshi_private.pem
```

Then set `KALSHI_KEY_ID` in `.env`. The path already points at
`/data/kalshi_private.pem`, which is inside the mounted volume.

`data/` is git-ignored, as are `*.pem` and `*.key`. Verify before your first
push:

```bash
git status --porcelain --ignored | grep -E "\.pem|\.env$"
```

Those files must appear as ignored, never as staged.

---

## Cloudflare tunnel

The dashboard has no authentication of its own. Do not publish it by forwarding
a port. A tunnel makes the outbound connection instead, so no inbound port is
open, and Cloudflare Access handles authentication in front of it.

### 1. Create the tunnel

```bash
cloudflared tunnel login
cloudflared tunnel create pythia
cloudflared tunnel route dns pythia pythia.example.com
```

### 2. Configuration

`cloudflared/config.yml`:

```yaml
tunnel: <tunnel-uuid>
credentials-file: /etc/cloudflared/<tunnel-uuid>.json

ingress:
  - hostname: pythia.example.com
    service: http://pythia-api:8000
  - service: http_status:404
```

`pythia-api` resolves inside the compose network — the port never touches the
host.

### 3. Run it alongside

Add to `docker-compose.yml`:

```yaml
  tunnel:
    image: cloudflare/cloudflared:latest
    container_name: pythia-tunnel
    restart: unless-stopped
    command: ["tunnel", "--no-autoupdate", "run"]
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on:
      api:
        condition: service_healthy
```

and `CLOUDFLARE_TUNNEL_TOKEN=` to `.env`. With the token form, no config file or
credentials file is needed — the token carries both.

### 4. Put Access in front of it

In Cloudflare Zero Trust → Access → Applications, add a self-hosted application
for `pythia.example.com` and set a policy (email address, one-time PIN, or an
identity provider).

**Without this step the dashboard is public.** The tunnel hides the port, not
the content.

### Service tokens for automation

For machine access — a monitoring job, a second host — create a service token
under Access → Service Auth and add a policy accepting it. Service tokens are
credentials: keep them in a password manager or a secrets file outside the
repository, never in chat, a ticket, or a commit.

Rotate them the moment one is exposed. Rotation is immediate; the old token
stops working on the next request.

---

## Operating it

### Is it alive?

```bash
curl -s localhost:8300/api/status
```

`juengste_zeile_alter_sek` is the number to watch. Below 5,400 seconds is
healthy, and `frisch` reports the same as a boolean.

Do not rely on the container being "up". On 6 August 2026 the containers were up
and healthy and writing nothing for 29 hours, because the collector depended on
a host cron entry that had been commented out. That is why the scheduler now
lives inside the container and why the status endpoint reports data age rather
than a green tick.

### Watchdog

The compose file uses `restart: unless-stopped`, which does not help if the
Docker daemon itself does not come back after a reboot. On a workstation, ensure
Docker starts at login. On a server, ensure the daemon is enabled:

```bash
sudo systemctl enable docker
```

For an additional check that also notices a *silent* stall:

```bash
*/5 * * * * curl -sf localhost:8300/api/status | grep -q '"frisch": true' \
  || docker compose -f /path/to/pythia/docker-compose.yml up -d
```

### Backups

Everything lives in `data/pythia.db`. It is append-only, so a copy is a
consistent snapshot as long as no write lands mid-copy:

```bash
docker exec pythia-api python -c \
  "import sqlite3;sqlite3.connect('/data/pythia.db').backup(sqlite3.connect('/data/backup.db'))"
```

### Budget

The Odds API free tier is 500 credits per month; one call per sport costs two.
Four collection windows across four sports consumed 85 credits per day and would
have run out mid-month. Two windows across three sports run at about 33.

`/api/status` reports `abrufeinheiten_uebrig`. Watch it — the sports side goes
silent without an error when the quota is gone.

Weather costs nothing.

---

## Updating

```bash
git pull
docker compose build
docker compose up -d
```

The database survives; the schema migrates itself on start. Older schema
versions are retained as evidence and excluded from evaluation by version rather
than deleted.
