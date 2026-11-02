"""Gom mọi kết quả benchmark thành một trang so sánh có nghe A/B."""

from __future__ import annotations

import base64
import json
import os
from datetime import date
from pathlib import Path

from _common import audio_duration

BASE = Path(__file__).parent
OUT = BASE / "out"
# Ngày in trên trang. Đặt BENCH_DATE để tái dựng báo cáo của một lượt đo cũ.
DATE = os.environ.get("BENCH_DATE") or date.today().strftime("%d/%m/%Y")

# Cấu hình đem lên phòng nghe, theo thứ tự trình bày
LISTEN = [
    ("soniox-v2-Nina-sp1.15-rs", "sx", "Soniox v2 · Nina · speed 1.15 + reduce_silence"),
    ("soniox-v2-Nina", "sx", "Soniox v2 · Nina · mặc định"),
    ("el-flash-v2_5-AnhVien", "el", "ElevenLabs Flash v2.5 · Ánh Viên (đang chạy)"),
]
LISTEN_EMO = [
    ("soniox-v2-Nina-emo", "sx", "Soniox v2 · Nina"),
    ("el-v3-AnhVien-emo", "el", "ElevenLabs v3 · Ánh Viên"),
    ("el-flash-v2_5-AnhVien-emo", "el", "ElevenLabs Flash v2.5 · Ánh Viên"),
]
TIMELINE = [
    ("soniox-v2-ws-mp3", "sx", "Soniox v2 · mp3"),
    ("soniox-v2-ws-mulaw8k", "sx", "Soniox v2 · µ-law 8k"),
    ("el-flash-v2_5-stream", "el", "ElevenLabs Flash · mp3"),
    ("el-flash-v2_5-stream-ulaw8k", "el", "ElevenLabs Flash · µ-law 8k"),
]


def jload(name: str) -> list | dict:
    return json.loads((BASE / name).read_text())


def b64(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode()


rest = [r for r in jload("results_rest.json") if not r.get("error")]
rest += [r for r in jload("results_rs.json") if not r.get("error")]
emo = [r for r in jload("results_emotion.json") if not r.get("error")]
stt = {(r["config"], r["case"]): r for r in jload("results_stt_rescored.json")}
cost = jload("results_cost.json")
cases_main = jload("cases.json")
cases_emo = jload("cases_emotion.json")
audio_by = {(r["config"], r["case"]): r for r in rest + emo}


def build_cases(case_defs: list, configs: list) -> list:
    blocks = []
    for c in case_defs:
        clips = []
        for cfg, prov, label in configs:
            meta = audio_by.get((cfg, c["id"]))
            f = OUT / f"{c['id']}__{cfg}.mp3"
            if not meta or not f.exists():
                continue
            sc = stt.get((cfg, c["id"]))
            clips.append(
                {
                    "config": cfg,
                    "provider": prov,
                    "label": label,
                    "audio_s": meta["audio_s"],
                    "b64": b64(f),
                    "cer": sc["cer_words_pct"] if sc else None,
                    "wer": sc["wer_words_pct"] if sc else None,
                }
            )
        blocks.append({"id": c["id"], "label": c["label"], "text": c["text"], "clips": clips})
    return blocks


def build_timeline() -> list:
    groups = []
    for tag, title in (("greet", "Câu chào hotline — 3,2–3,8 s thoại"), ("long", "Đoạn dài — 22–24 s thoại")):
        rows_src = {r["target"]: r for r in jload(f"results_stream_{tag}.json") if not r.get("error")}
        rows = []
        for target, prov, label in TIMELINE:
            r = rows_src.get(target)
            if not r:
                continue
            ext = "ulaw" if "law" in target else "mp3"
            f = OUT / f"stream_{tag}__{target}.{ext}"
            if not f.exists():
                continue
            d = audio_duration(f)
            rows.append(
                {
                    "label": label,
                    "provider": prov,
                    "ttfb": r["ttfb_median_s"],
                    "total": r["total_median_s"],
                    "audio": round(d, 2),
                    "margin": round(r["ttfb_median_s"] + d - r["total_median_s"], 2),
                }
            )
        groups.append({"title": title, "rows": rows})
    return groups


digits_raw = jload("results_verify_digits.json")
dig_groups = []
for target, prov, label in (
    ("soniox-v2-sp1.15-rs", "sx", "Soniox v2 · sp1.15 + rs"),
    ("el-flash-v2_5", "el", "ElevenLabs Flash v2.5"),
):
    runs = [
        {
            "ok": not r["missing"],
            "missing": r["missing"],
            "digits": " ".join(w for w in r["hyp"].split() if w.isdigit()),
        }
        for r in digits_raw
        if r["target"] == target
    ]
    dig_groups.append({"label": label, "provider": prov, "runs": runs})

cost_min = min(c["usd_per_audio_hour"] for c in cost)
data = {
    "meta": {
        "date": DATE,
        "stt_model": "stt-async-v5",
        "timeline_caption": (
            "Ở câu ngắn, vạch sinh-xong của Soniox nằm sau mép thanh phát: audio sinh ra chậm hơn "
            "nhịp phát khoảng 0,1–0,3 s, nên cần đệm trước khi phát. Ở đoạn dài, Soniox vượt lên "
            "trước và dư khoảng 3 s. ElevenLabs dư 3 s ở câu ngắn và 23 s ở đoạn dài."
        ),
        "digits_caption": (
            "Mỗi ô là một lần sinh độc lập cùng một câu. ElevenLabs Flash đọc "
            '<span class="mono">1.250.000</span> thành “một triệu hai trăm ba mươi nghìn” ở lần đầu — '
            "sai một chữ số trong số tiền. 5 mẫu là ít, nên hãy coi đây là rủi ro cần kiểm chứng thêm "
            "chứ chưa phải tỉ lệ lỗi đã chốt."
        ),
    },
    "tiles": [
        {
            "label": "TTFB streaming, câu ngắn",
            "value": "0,21 s",
            "winner": "el",
            "note": "Soniox 0,44 s — chậm hơn 2,1 lần. Đo qua 5 lần, độ dao động thấp ở cả hai.",
        },
        {
            "label": "Biên phát lại, câu ngắn",
            "value": "+3,15 s",
            "winner": "el",
            "note": "Soniox −0,09 s (mp3) và −0,27 s (µ-law): sinh chậm hơn nhịp phát, sẽ hụt nếu phát ngay.",
        },
        {
            "label": "Chi phí mỗi giờ audio",
            "value": "$0,70",
            "winner": "sx",
            "note": "ElevenLabs Flash $3,14 — đắt hơn 4,5 lần. Quy đổi theo ký tự/giây đo thực tế.",
        },
        {
            "label": "Đọc đúng số tiền, 5 lần",
            "value": "5/5",
            "winner": "sx",
            "note": "ElevenLabs Flash 4/5 — một lần đọc 1.250.000 thành 1.230.000.",
        },
    ],
    "cases": build_cases(cases_main, LISTEN),
    "emotion": build_cases(cases_emo, LISTEN_EMO),
    "timeline": build_timeline(),
    "digits": dig_groups,
    "latency": [
        {
            "config": r["config"],
            "case": r["case"],
            "chars": r["chars"],
            "ttfb": r["ttfb_best_s"],
            "total": r["total_best_s"],
            "audio": r["audio_s"],
            "rtf": r["rtf"],
        }
        for r in rest
    ],
    "stt": [
        {
            "config": k[0],
            "case": k[1],
            "cer_words": v["cer_words_pct"],
            "cer": v["cer_pct"],
            "wer_words": v["wer_words_pct"],
        }
        for k, v in sorted(stt.items())
    ],
    "cost": [{"config": c["config"], "cps": c["chars_per_audio_s"], "usd": c["usd_per_audio_hour"]} for c in cost],
    "cost_min": cost_min,
    "notes": [
        "Cả hai bên dùng cùng văn bản tiếng Việt, cùng mp3 44,1 kHz 128 kbps. REST lặp 3 lần lấy "
        "giá trị tốt nhất; streaming lặp 5 lần (câu ngắn) và 3 lần (đoạn dài) lấy trung vị.",
        "So sánh này <strong>không công bằng về giọng</strong>: Ánh Viên là giọng Việt chuyên nghiệp đã "
        "clone, còn 70 giọng sẵn của Soniox đều không phải giọng Việt bản địa. Soniox có tính năng "
        "voice cloning — muốn so đúng thì phải clone giọng Việt trước.",
        "Điểm CER dùng STT của chính Soniox nên thiên vị nhẹ về phía Soniox. Đây là phép đo độ rõ, "
        "không đo độ tự nhiên — phần nghe A/B mới trả lời được câu hỏi đó.",
        "CER thô ở câu trộn Anh–Việt và đoạn dài bằng nhau ở mọi cấu hình vì STT xuất chữ số "
        "(“3 000”) trong khi văn bản gốc viết chữ (“ba nghìn”). Sau khi loại chênh lệch đó, cả hai "
        "về 0% ở câu trộn và 1,25% đồng đều ở đoạn dài — tức không bên nào phát âm sai.",
        "Soniox REST và WebSocket đều sinh audio ở tốc độ gần nhịp thoại (RTF 0,87–1,19). "
        "ElevenLabs Flash sinh nhanh hơn 10–30 lần nhịp thoại, nên dư biên rất lớn.",
        "Định dạng: Soniox nhận pcm_f32le, pcm_s16le, pcm_mulaw, pcm_alaw, wav, flac, mp3, opus, aac "
        "— tài liệu REST của họ ghi thiếu và còn ghi sai pcm_s16be. ElevenLabs có ulaw_8000, pcm_* "
        "và opus. Cả hai đủ cho telephony.",
        "Audio tag chỉ chạy trên tts-rt-v2 (Soniox) và eleven_v3 (ElevenLabs). Flash v2.5 phát âm "
        "luôn tên tag — bản phiên âm ra đúng chữ “excited”.",
        "Đo từ một máy tại chỗ làm, không phải từ máy chủ production. RTT tới Soniox 53 ms, tới "
        "ElevenLabs 19–25 ms; hãy đo lại từ nơi triển khai thật.",
        "Key Soniox trong odyssey-agent/.env đã bị thu hồi (401 cả STT lẫn TTS). Bài thử này dùng "
        "key mới. Key ElevenLabs còn dùng được nhưng thiếu quyền user_read nên không đọc được hạn mức.",
    ],
}

html = (BASE / "report_template.html").read_text().replace("__DATA__", json.dumps(data, ensure_ascii=False))
target = BASE / "report.html"
target.write_text(html)
mb = target.stat().st_size / 1048576
print(f"report.html: {mb:.2f} MB")
print(
    f"  cases={len(data['cases'])} emotion={len(data['emotion'])} "
    f"clips={sum(len(c['clips']) for c in data['cases'] + data['emotion'])}"
)
print(f"  timeline groups={len(data['timeline'])} latency rows={len(data['latency'])} stt rows={len(data['stt'])}")
assert mb < 15, "vượt giới hạn artifact"
