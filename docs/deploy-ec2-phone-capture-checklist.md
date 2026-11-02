# Deploy Checklist — Phone Capture + Summary + A5 Prompt

**Target server**: `ec2-47-129-187-61.ap-southeast-1.compute.amazonaws.com`
**Target Asterisk**: `voip.noble.vn` (FreePBX)
**Changes**: Part 1 (prompt A5) + Part 2 (phone capture) + Part 3 (summary) + Part 6 (booking auto-phone)

---

## Phase 0 — Pre-flight

### 0.1 Commit + push code

```bash
cd /Users/nmcxyz/Desktop/MyFolder/NobleX/Official/santa-hotline-agent
git status                   # review changes
git add -A
git commit -m "feat: phone capture + summary + A5 prompt (Part 1/2/3/6)"
git push origin develop      # or current branch
```

### 0.2 Verify dialplan already updated on Asterisk

SSH vào voip.noble.vn (nếu có access), confirm `Stasis(noble-voice-agent)` đã thêm:
```bash
asterisk -rx "dialplan show noble-voice-agent" | grep -i stasis
# expect: [1] Stasis("noble-voice-agent"...) — in s@noble-voice-agent extension
```

Nếu chưa, apply:
```bash
sudo vi /etc/asterisk/extensions_custom.conf
# add `same => n,Stasis(noble-voice-agent)` BEFORE Set(UH=...) line
sudo asterisk -rx "dialplan reload"
```

### 0.3 Generate API key for Part 3 sales API

```bash
openssl rand -hex 32
# copy output, will set as NOBLE_SALES_API_KEY in .env
```

---

## Phase 1 — Build & push Docker image

### 1.1 Login ECR

```bash
aws ecr get-login-password --region ap-southeast-1 | \
  docker login --username AWS --password-stdin 418295696099.dkr.ecr.ap-southeast-1.amazonaws.com
```

### 1.2 Build (cross-platform for EC2 amd64)

```bash
cd /Users/nmcxyz/Desktop/MyFolder/NobleX/Official/santa-hotline-agent
docker buildx build \
  --platform linux/amd64 \
  -t 418295696099.dkr.ecr.ap-southeast-1.amazonaws.com/aidc/santa-hotline-agent:phone-v1 \
  --push \
  .
```

Build takes ~3-5 mins.

### 1.3 Verify image

```bash
aws ecr describe-images \
  --repository-name aidc/santa-hotline-agent \
  --region ap-southeast-1 \
  --image-ids imageTag=phone-v1 \
  --query 'imageDetails[0].{pushedAt:imagePushedAt,size:imageSizeInBytes}'
```

---

## Phase 2 — Deploy to EC2

### 2.1 SSH vào EC2

```bash
chmod 400 ~/Downloads/ai-dev.pem
ssh -i ~/Downloads/ai-dev.pem ubuntu@ec2-47-129-187-61.ap-southeast-1.compute.amazonaws.com
```

### 2.2 Tìm docker-compose file

```bash
find /home/ubuntu /opt /root -maxdepth 5 -name "docker-compose*.yml" 2>/dev/null
# Expect to find the one with santa-hotline-agent-agent service
```

Kết quả dự kiến: `/home/ubuntu/services/docker-compose.yml` hoặc tương tự.

### 2.3 Update image tag

```bash
cd /home/ubuntu/services                                    # adjust path
vi docker-compose.yml                                       # or nano
# Find the santa-hotline-agent service and change:
#   image: 418295696099.dkr.ecr.ap-southeast-1.amazonaws.com/aidc/santa-hotline-agent:b39f3cec
# To:
#   image: 418295696099.dkr.ecr.ap-southeast-1.amazonaws.com/aidc/santa-hotline-agent:phone-v1
```

### 2.4 Thêm env mới (Part 3 API key)

Trong `docker-compose.yml` hoặc `.env` của compose file:
```bash
NOBLE_SALES_API_KEY=<paste hex from Phase 0.3>
```

Env cũ (Asterisk ARI) đã có rồi, verify:
```bash
grep -E '(ASTERISK|AUDIOSOCKET|TELEPHONY)' docker-compose.yml
# Or:
docker inspect santa-hotline-agent-agent-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | grep ASTERISK
```

### 2.5 Pull + restart

```bash
aws ecr get-login-password --region ap-southeast-1 | \
  docker login --username AWS --password-stdin 418295696099.dkr.ecr.ap-southeast-1.amazonaws.com

cd /home/ubuntu/services
docker compose pull santa-hotline-agent-agent
docker compose up -d santa-hotline-agent-agent santa-hotline-agent-agent-lk
```

### 2.6 Verify containers restarted

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
# Expect both agent containers with new :phone-v1 tag and Up <few seconds>
```

---

## Phase 3 — Smoke tests (no real call yet)

### 3.1 Tail log, confirm ARI reconnects

```bash
docker logs -f santa-hotline-agent-agent-1 2>&1 | grep -iE '\[TEL\]|ARI|stasis'
```

Expected within 30 seconds of container start:
```
[TEL] Telephony manager started
AudioSocket server listening on 0.0.0.0:8090
[TEL] ARI client connecting to voip.noble.vn:8088
ARI connected — listening for Stasis events (app=noble-voice-agent)
```

### 3.2 Health check

```bash
docker exec santa-hotline-agent-agent-1 curl -s http://localhost:8768/health/ready | jq .
# Expect: status=ok, all services except maybe qdrant (known unhealthy)
```

### 3.3 Sales API smoke test

```bash
# Replace <KEY> with the NOBLE_SALES_API_KEY you set in Phase 2.4
docker exec santa-hotline-agent-agent-1 curl -s \
  -H "X-Noble-API-Key: <KEY>" \
  "http://localhost:8768/api/v1/sales/summaries?phone=0000000000" | jq .
# Expect: {"phone":"0000000000","total":0,"summaries":[]}
```

---

## Phase 4 — Real call E2E test

### 4.1 Start tailing log in separate window

```bash
docker logs --since 1m -f santa-hotline-agent-agent-1 2>&1 | \
  grep -iE '\[TEL\]|stasis|caller|phone|SUMMARY|SWITCH'
```

### 4.2 Dial from SIP softphone

Softphone: Zoiper / Linphone trên máy anh.

Config SIP account:
- Server: Noble PBX (hỏi IT Noble)
- Extension: một số nội bộ
- Outbound caller ID: set rõ ràng để test, VD `0912345678`

Gọi vào `18006112` (hoặc DID của noble-voice-agent).

### 4.3 Log sequence kỳ vọng

```
[TEL][ARI] StasisStart: channel=1735189234.42 caller_raw='0912345678' phone='0912345678' (map_size=0)
[TEL] Caller registered: channel=1735189234.42 phone=0912345678
AudioSocket connection from ('x.x.x.x', yyyy)
AudioSocket call started: call_id=<uuid-hex-dashed>       ← GIỜ LÀ UUID ĐẸP, KHÔNG BINARY
[TEL] Caller matched by fallback: ch=1735189234.42 phone=0912345678 (AudioSocket=<uuid>)
[TEL] Call started: call_id=<uuid> session_id=tel-<uuid>
[TEL] No prior profile for phone=0912345678          ← lần 1 không có
[TEL] STT started: soniox
[AGENT] Auto-greeting: Dạ em chào Anh, em là Luna ...   ← nếu gender detect M
```

Nếu lần sau gọi lại (có tên trong MongoDB):
```
[TEL] Loaded customer profile for phone=0912345678 name=Minh gender=M
[AGENT] Auto-greeting: Dạ em chào Anh Minh, em là Luna ...
```

### 4.4 Trong cuộc gọi, xin đặt lịch

Caller nói: "em muốn đặt lịch xem dự án Noble Crystal Long Biên"

Expected Luna response:
```
Dạ em sẽ hỗ trợ đặt lịch Noble Crystal Long Biên cho mình ạ. Em ghi nhận số anh
đang gọi là 091-234-5678 để liên hệ, anh dùng số này hay muốn đổi số khác ạ?
```

(thay vì "Xin anh cho em số điện thoại ạ?")

Log kỳ vọng:
```
[TOOL] get_booking_state auto_filled=['phone_number']
```

### 4.5 Cúp máy và verify MongoDB

```bash
# Wait 5-10s after hangup for _cleanup + summary to finish
docker exec santa-hotline-agent-agent-1 python3 -c "
import asyncio
from noble_agent.storage.session_store import load_customer_by_phone
from noble_agent.storage.call_summaries import load_last_summary_by_phone

async def check():
    c = await load_customer_by_phone('0912345678')
    print('Customer:', c)
    s = await load_last_summary_by_phone('0912345678')
    print('Last summary:', s.get('summary') if s else None)
    print('Open actions:', s.get('open_actions') if s else None)

asyncio.run(check())
"
```

Expected output:
```
Customer: {'phone': '0912345678', 'gender': 'M', 'updated_at': ..., 'created_at': ...}
Last summary: 'Anh hỏi về lịch xem dự án NCLB, Luna đã ghi nhận ...'
Open actions: ['...']
```

### 4.6 Test cuộc gọi thứ 2 — verify memory

Gọi lại từ cùng số `0912345678` ngay sau đó.

Expected:
- Greeting mention đích danh (nếu lần 1 có capture name)
- Trong prompt: `LỊCH SỬ CUỘC GỌI TRƯỚC` block appears
- Luna tự nhiên tiếp nối từ lần trước

Verify trong log:
```
[TEL] Loaded customer profile for phone=0912345678 name=...
```

Grep prompt build log nếu bật DEBUG:
```
[FAQ] ... project=NCLB ...
```

---

## Phase 5 — Failure debugging

### 5.1 Không có `StasisStart` log khi gọi

**Check**:
```bash
# Trên voip.noble.vn:
asterisk -rx "dialplan show noble-voice-agent" | grep -i stasis
# Phải có dòng [n] Stasis(noble-voice-agent)

asterisk -rx "module show like res_ari"
# Phải loaded
```

Nếu Stasis có nhưng event không emit → check ARI app subscribe:
```bash
# Trên voip.noble.vn:
asterisk -rx "ari show apps"
# Phải thấy noble-voice-agent với subscribers
```

### 5.2 `StasisStart: caller_raw=''`

SIP trunk strip CALLERID. Fix trên trunk:
- FreePBX UI → Connectivity → Trunks → NobleX trunk → pjsip Settings → Advanced
- Set: `Trust RPID/PAI: Yes`, `Send RPID/PAI: PAI`, `Caller ID: (leave empty)`

### 5.3 `call_id` vẫn binary junk

`audiosocket.py` fix chưa deploy. Check:
```bash
docker exec santa-hotline-agent-agent-1 grep -A3 "Asterisk binary UUID" \
  /app/src/noble_agent/telephony/audiosocket.py
# Should show the UUID(bytes=payload) logic
```

Nếu không có → rebuild image (Phase 1 again).

### 5.4 Summary không save

```bash
docker logs santa-hotline-agent-agent-1 2>&1 | grep -i SUMMARY
# Check for:
# [SUMMARY] LLM timeout — increase timeout in base_session.py stop()
# [SUMMARY] JSON parse failed — LLM returned non-JSON
# [SUMMARY] providers failed — LLM API down
```

---

## Phase 6 — Rollback

Nếu bất kỳ critical issue:
```bash
# SSH vào EC2
cd /home/ubuntu/services
vi docker-compose.yml   # revert image tag to :b39f3cec (old working)
docker compose pull santa-hotline-agent-agent
docker compose up -d santa-hotline-agent-agent santa-hotline-agent-agent-lk
```

Dialplan rollback (optional):
```bash
# Trên voip.noble.vn:
sudo vi /etc/asterisk/extensions_custom.conf
# remove Stasis() line
sudo asterisk -rx "dialplan reload"
```

---

## Phase 7 — Observability

### Metrics to watch (7 days post-deploy)

| Metric | Target | How |
|---|---|---|
| Phone capture rate | >95% calls | grep `Caller registered` / grep `Call started` |
| Prompt cache hit (Part 1) | >80% turn 2+ | OpenAI dashboard (if have cache_read_input_tokens metric) |
| Summary generation rate | >90% of phone-tied calls | MongoDB count: `db.call_summaries.count()` vs sessions count |
| Summary LLM timeout rate | <5% | grep `[SUMMARY] LLM timeout` |
| Booking auto-fill rate | >95% calls with known phone | grep `auto_filled=['phone_number']` |

### Log queries

```bash
# Last 24h phone capture success
docker logs --since 24h santa-hotline-agent-agent-1 2>&1 | grep 'Caller registered' | wc -l
docker logs --since 24h santa-hotline-agent-agent-1 2>&1 | grep 'No caller phone available' | wc -l

# Summary saves
docker logs --since 24h santa-hotline-agent-agent-1 2>&1 | grep '\[SUMMARY\] saved' | wc -l

# Repeat callers (have prior profile)
docker logs --since 24h santa-hotline-agent-agent-1 2>&1 | grep 'Loaded customer profile' | wc -l
```
