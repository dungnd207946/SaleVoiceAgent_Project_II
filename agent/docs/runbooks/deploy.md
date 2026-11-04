# Hotline Agent Deploy Runbook

Deploys the santa-hotline-agent stack on a fresh EC2 instance (Ubuntu 24.04).
Covers the full Option B (self-hosted LiveKit) topology.

## 1. Host prerequisites

```bash
# Docker + compose v2
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
# Nginx + Certbot
sudo apt install -y nginx python3-certbot-nginx
# GitLab runner (if this host runs CI deploys)
# https://docs.gitlab.com/runner/install/linux-repository.html
```

AWS security group must open:
- **22/TCP** — SSH
- **80/TCP, 443/TCP** — nginx HTTP/HTTPS
- **7881/TCP** — LiveKit RTC TCP fallback
- **52000–52049/UDP** — LiveKit ICE candidate range
- **8090/TCP** — AudioSocket from FreePBX (phase 7). Source: `<voip-public-ip>/32`

## 2. Shared infra (postgres/redis)

The app stack expects redis on `127.0.0.1:6379` and postgres on `5432`.
Reuse the existing `/home/ubuntu/services/docker-compose.yml` stack or
bring up fresh containers.

## 3. LiveKit server

```bash
# From the repo checkout (or a fresh clone)
mkdir -p ~/livekit
cp infra/livekit/docker-compose.yml          ~/livekit/
cp infra/livekit/livekit.example.yaml        ~/livekit/livekit.yaml

# Generate keys
KEY="noble_$(openssl rand -hex 8)"
SECRET="$(openssl rand -hex 32)"
sed -i "s|REPLACE_ME_API_KEY|${KEY}|"            ~/livekit/livekit.yaml
sed -i "s|REPLACE_ME_API_SECRET_64_HEX_CHARS|${SECRET}|" ~/livekit/livekit.yaml

cd ~/livekit && docker compose up -d

# Verify
curl -s http://127.0.0.1:7880/    # → 200 OK
docker logs livekit-livekit-1     # → "starting LiveKit server"
```

Save the generated KEY/SECRET — they go into the app env next.

## 4. Nginx vhost

```bash
sudo cp infra/nginx/hotline-agent.noble.vn.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/hotline-agent.noble.vn.conf \
          /etc/nginx/sites-enabled/
sudo certbot --nginx -d hotline-agent.noble.vn
sudo nginx -t && sudo systemctl reload nginx
```

Verify:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://hotline-agent.noble.vn/  # 200
curl -s https://hotline-agent.noble.vn/livekit/token?room=x&identity=x    # after §5
```

## 5. Hotline agent app

CI deploys the app via gitlab-runner. The runner invokes
`docker-compose.deploy.yml` (root of this repo) with `${IMAGE_TAG}` injected
from the pipeline. Two containers come up:

- **agent**    — aiortc transport, serves static UI + `/livekit/token`
- **agent-lk** — LiveKit worker, registers with the livekit-server

Required GitLab CI/CD variables (Settings → CI/CD → Variables):

| Key | Type | Notes |
|---|---|---|
| `ECR_URL`, `AWS_*` | var | image push/pull |
| `CI_TOKEN` | var | access to this repo for the runner |
| `ENV_FILE` | **file** | full `.env` — see [§5.1](#51-env_file-contents) |

### 5.1 ENV_FILE contents

Minimum for LiveKit self-host:

```env
# TTS / voice
ELEVENLABS_API_KEY=...
ELEVENLABS_TTS_VOICE_ID=iSFxP4Z6YNcx9OXl62Ic
ELEVENLABS_TTS_MODEL=eleven_flash_v2_5
ELEVENLABS_TTS_STABILITY=1.0
ELEVENLABS_TTS_SIMILARITY_BOOST=0.75
ELEVENLABS_TTS_SPEED=1.1

# Hotline
NOBLE_HOTLINE="1800 6112"
NOBLE_WORKING_HOURS=8:00-21:00

# LiveKit (self-host)
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_PUBLIC_URL=wss://hotline-agent.noble.vn/livekit
LIVEKIT_API_KEY=<KEY from §3>
LIVEKIT_API_SECRET=<SECRET from §3>
# Empty → auto-dispatch the worker into every new room
LIVEKIT_AGENT_NAME=

# Plus: GEMINI_API_KEY, REDIS_URL, MONGODB_URI, etc.
# See .env.example in the repo root.
```

## 6. Data bootstrap (one-time per host)

The app mounts `./data` into the container. Two paths need manual
population because they are too large or too environment-specific for git:

### 6.1 RAG chunks

Copy `kv_store_text_chunks.json` for each of 5 projects. From a machine
that has the santa-chat-agent export:

```bash
rsync -av santa-chat-agent/src/services/rag/data/lightrag_s02_*/ \
  ubuntu@HOST:/home/gitlab-runner/santa-hotline-agent/data/rag/
```

Expected layout:

```
data/rag/lightrag_s02_<key>/<key>/kv_store_text_chunks.json
```

where `<key>` is one of `crystal_tay_ho, noble_crystal_long_bien,
noble_palace_long_bien, noble_palace_tay_thang_long, noble_sunshine_legend_city`.

### 6.2 FlatStore embedding cache

A fresh encode takes ~30 min on Mac M / ~3 min on x86 AVX-512. To skip:
copy the prebuilt cache from another host.

```bash
scp -r ubuntu@SRC:/home/gitlab-runner/santa-hotline-agent/data/flat_store \
       /home/gitlab-runner/santa-hotline-agent/data/
```

If no cache exists anywhere, the first container start will encode from
chunks and write the cache. Bump `INITIALIZE_PROCESS_TIMEOUT=3600` in
`.env` for that first boot, then remove it.

## 7. First deploy

Trigger a CI pipeline on the `develop` branch. The deploy job:

```
git reset --hard && git pull
cp $ENV_FILE .env
docker compose -f docker-compose.deploy.yml pull
docker compose -f docker-compose.deploy.yml up -d --remove-orphans
```

Verify:

```bash
docker ps | grep -E "santa-hotline|livekit"
curl -s https://hotline-agent.noble.vn/livekit/token?room=x&identity=x | jq .
```

Open `https://hotline-agent.noble.vn/livekit.html`, click **Bắt đầu gọi**,
grant mic — the agent should greet you within ~2s.

## 8. Telephony (FreePBX / AudioSocket)

Wires the hotline number `1800 6112` through FreePBX (`voip.noble.vn`) into
the agent via AudioSocket TCP on port 8090. See
[docs/freebpx-setup.md](../freebpx-setup.md) for the full protocol and
dialplan reference. Minimal checklist below:

### 8.1 Agent-side env (via GitLab `ENV_FILE`)

```env
TELEPHONY_ENABLED=true
ASTERISK_HOST=voip.noble.vn
ASTERISK_ARI_PORT=8088
ASTERISK_ARI_SCHEME=http
ASTERISK_ARI_USERNAME=noble-agent
ASTERISK_ARI_PASSWORD=<from FreePBX ari_additional.conf>
ASTERISK_ARI_APP=noble-voice-agent
AUDIOSOCKET_HOST=0.0.0.0
AUDIOSOCKET_PORT=8090
TELEPHONY_RECORD_CALLS=false
```

Leave `ASTERISK_ARI_PASSWORD` empty to disable the ARI client entirely —
telephony keeps working via AudioSocket, but caller-number prefetch is
skipped and every call is treated as anonymous.

### 8.2 Agent-side network

- AWS SG opens TCP 8090 from the FreePBX public IP only:

  ```bash
  aws ec2 authorize-security-group-ingress --region ap-southeast-1 \
    --group-id sg-<hotline-sg> --ip-permissions '[{
      "IpProtocol":"tcp","FromPort":8090,"ToPort":8090,
      "IpRanges":[{"CidrIp":"<voip-public-ip>/32",
                   "Description":"Asterisk AudioSocket from voip.noble.vn"}]
    }]'
  ```

- Redeploy (CI pipeline) — expect log:

  ```
  [TEL] AudioSocket on :8090
  [TEL] Telephony manager started
  ```

### 8.3 FreePBX dialplan (co-worker side)

`Admin → Config Edit → extensions_custom.conf`:

```ini
[noble-voice-agent]
exten => s,1,NoOp(=== Noble Voice Agent inbound ===)
 same => n,Answer()
 same => n,Wait(0.3)
 same => n,Set(UH=${MD5(${UNIQUEID}${EPOCH})})
 same => n,Set(AS_UUID=${UH:0:8}-${UH:8:4}-${UH:12:4}-${UH:16:4}-${UH:20:12})
 same => n,AudioSocket(${AS_UUID},<agent-public-ip>:8090)
 same => n,Hangup()
```

Key gotchas (learned the hard way):
- `${CHANNEL(uniqueid)}` is **not** a valid UUID (format `<epoch>.<seq>`)
  — `app_audiosocket.c` rejects it with `Failed to parse UUID`. Use the
  MD5 → UUID-format trick above instead.
- `${SHELL(uuidgen)}` returns empty when Asterisk runs with
  `live_dangerously = no` (the secure default). Avoid SHELL entirely.
- Do **not** `Stasis(noble-voice-agent)` before `AudioSocket()` unless the
  ARI client is reachable — Stasis pauses the channel waiting for
  `POST /channels/{id}/continue` and the call hangs.

`Connectivity → Inbound Routes` for DID `18006112` → Custom Destination
→ `noble-voice-agent,s,1`. Apply Config.

### 8.4 FreePBX → agent firewall

Sangoma Firewall (`Admin → System Admin → Firewall`):
- **Networks** tab → add `<agent-public-ip>/32` → zone
  **Trusted (Excluded from Firewall)** → Save → Apply Config.

This only matters for **agent → FreePBX** direction (ARI WebSocket on
8088) — FreePBX → agent on 8090 works as long as the upstream NAT/router
allows outbound TCP.

### 8.5 Enabling ARI (optional)

Default prod topology blocks ARI because `voip.noble.vn` sits behind NAT
and the upstream router/gateway does not port-forward 8088. ARI only adds
caller-number prefetch; telephony itself does not need it.

To enable, devops needs to do one of:

1. Port-forward TCP 8088 on the upstream router/gateway from the agent
   public IP to `172.10.2.180:8088` (FreePBX private IP). Sangoma
   Firewall whitelist alone is insufficient — the NAT layer drops the
   packets before they ever reach Sangoma.
2. Or run an nginx reverse proxy on the FreePBX host that exposes
   `/ari/*` under port 80 (already reachable) and update
   `ASTERISK_ARI_PORT=80` in the agent env.

## 9. Rollback

The aiortc transport remains on port 8768. Legacy clients keep working.
To fully roll back LiveKit:

```bash
# Stop the worker
sudo docker compose -f /home/gitlab-runner/santa-hotline-agent/docker-compose.deploy.yml stop agent-lk
# Stop the server
cd ~/livekit && docker compose down
# (optional) remove the nginx /livekit/ locations — revert the vhost
```

The `agent` container, the token endpoint, and the static UI keep serving
so the WebSocket path at `/` still accepts calls.
