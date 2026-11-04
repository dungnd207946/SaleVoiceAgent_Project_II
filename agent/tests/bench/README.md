# Bench Suite — Storage / RAG / Tool Latency

Đo độ trễ thật của 3 lớp riêng biệt để cô lập regression khi thay backend
(Mac local ↔ EC2 ↔ RunPod):

| Suite | File | Phụ thuộc | Mục đích |
|---|---|---|---|
| Storage RTT | `test_storage_latency.py` | MongoDB / Redis URI | Đo round-trip cloud DB primitive (ping, find_one, get/set) |
| RAG retrieval | `test_rag_latency.py` | `data/flat_store/` artifacts + e5-large | Đo in-process retrieval (không liên quan cloud) |
| Tool dispatch | `test_tool_latency.py` | Tất cả phía trên + Mongo writable | Đo full path qua `execute_tool` (~13 tools, gồm voice booking flow) |
| Dashboard reads | `test_dashboard_latency.py` | MongoDB + storage layer | Đo Mongo aggregation/scan đứng sau `/api/v1/sales/*` (CSKH UI) |

Marker `bench` đăng ký trong `pyproject.toml` → mặc định **không** chạy khi
`pytest` thường (CI, dev). Phải gọi rõ `-m bench`.

---

## Chạy

Giả định bạn đã activate venv và `.env` đã trỏ về EC2 (đúng pattern hiện tại):

```bash
# 1) Smoke — tất cả 3 suites, 50 runs/op (~3-5 phút trên mạng VN→Singapore)
pytest tests/bench -v -s -m bench
```

```bash
# 2) Chỉ storage (Mongo/Redis) — nhanh nhất, ~30s
pytest tests/bench/test_storage_latency.py -v -s -m bench
```

```bash
# 3) Chỉ RAG — không cần cloud, dùng để verify trên pod khi DB chưa up
pytest tests/bench/test_rag_latency.py -v -s -m bench
```

```bash
# 4) Chỉ tools — phụ thuộc storage + RAG, ~2 phút
pytest tests/bench/test_tool_latency.py -v -s -m bench
```

```bash
# 5) Một test duy nhất + tăng số runs để có percentile ổn định hơn
BENCH_N_RUNS=200 pytest tests/bench/test_storage_latency.py::test_mongo_ping -v -s -m bench
```

```bash
# 6) Đặt nhãn môi trường rõ ràng (override auto-detect)
BENCH_ENV_LABEL=mac-vn-fpt pytest tests/bench -v -s -m bench
BENCH_ENV_LABEL=runpod-2xA40 pytest tests/bench -v -s -m bench
```

> **Quan trọng:** dùng `-s` để xem dòng kết quả `[name] n=… p50=… p95=…` ngay
> khi từng test xong. Mặc định pytest nuốt stdout.

### Tunables (env vars)

| Env | Mặc định | Ý nghĩa |
|---|---|---|
| `BENCH_N_RUNS` | `50` | Số lần lặp mỗi op |
| `BENCH_WARMUP` | `3` | Drop N sample đầu (cold cache, JIT) |
| `BENCH_ENV_LABEL` | auto | Đè nhãn môi trường vào file output |

---

## Output

Mỗi test append một dòng JSON vào:

```
tests/bench/results/<suite>__<env>.jsonl
```

Ví dụ:

```
tests/bench/results/storage__mac-local.jsonl
tests/bench/results/storage__runpod.jsonl
tests/bench/results/rag__mac-local.jsonl
tests/bench/results/tools__mac-local.jsonl
```

Schema mỗi dòng (đã round 2 chữ số):

```json
{
  "name": "mongo.ping",
  "n": 50,
  "failed": 0,
  "p50_ms": 45.2, "p95_ms": 78.5, "p99_ms": 110.3,
  "min_ms": 32.1, "max_ms": 125.6,
  "mean_ms": 51.4, "stdev_ms": 14.8,
  "samples": [...],
  "env_label": "mac-local",
  "timestamp": "2026-04-28T...",
  "extra": {}
}
```

`results/` đã được gitignore — chỉ là local artifact.

---

## So sánh local ↔ pod

Sau khi chạy cùng suite ở 2 môi trường:

```bash
# Mac
pytest tests/bench/test_storage_latency.py -v -s -m bench

# Pod
ssh -p $POD_PORT root@$POD_HOST "cd /workspace/santa-hotline-agent && pytest tests/bench/test_storage_latency.py -v -s -m bench"

# Diff p50/p95 nhanh:
jq -c '{name, env: .env_label, p50: .p50_ms, p95: .p95_ms}' \
   tests/bench/results/storage__mac-local.jsonl tests/bench/results/storage__runpod.jsonl
```

Kỳ vọng: pod-to-EC2 (cùng Singapore region) **nhanh hơn 5–10×** so với
Mac→EC2 (qua internet VN). Storage suite là chỗ thấy chênh lệch rõ nhất; RAG
suite phải **gần bằng nhau** vì in-process.

---

## Markers + skip behaviour

Test dùng các marker tự nhận trong `conftest.py`:

| Marker | Nếu env thiếu sẽ … |
|---|---|
| `needs_mongo` | skip với reason `MONGODB_URI not set` |
| `needs_redis` | skip với reason `REDIS_URL not set` |

→ Có thể chạy partial trên pod khi DB chưa up.

---

## Diễn giải kết quả

**Storage RTT (target từ Mac VN → EC2 Singapore):**
- p50 30-60ms acceptable, p95 < 150ms
- Nếu p95 > 300ms → kiểm tra mạng nội bộ (VPN, proxy, DNS)

**RAG retrieval (target):**
- FlatStore cold load: 2–5s lần đầu, < 1s nếu npy cached
- FlatStore search_hybrid warm: p50 < 50ms, p95 < 100ms
- FAQ semantic inject: p50 < 30ms

**Tools (target):**
- noble_search p50 < 100ms (RAG + Redis)
- get_project_overview p50 < 5ms (mock dict lookup)
- schedule_viewing p50 < 200ms (Mongo write)

Khi vượt target → mở suite tương ứng để tìm thủ phạm (đa phần là DB I/O).

---

## Postgres gap (chưa migrate)

Hiện `DATA_MODE=mock` → các tool `get_project_financial`, `search_units`,
`check_availability` trả từ dict in-memory ở
`src/noble_agent/services/structured_data_service.py`. Bench vẫn đo được
overhead dispatch (~< 1ms) nhưng **không phản ánh I/O thật**.

Khi chuyển sang Postgres real, **không** sửa bench — chỉ cần đặt
`DATA_MODE=real` + `POSTGRES_URI_REAL` rồi chạy lại; cùng test sẽ tự đo I/O
thực. Đây là lý do bench chia thành 3 suite tách biệt.
