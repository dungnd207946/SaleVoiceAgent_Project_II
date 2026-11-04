import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

# Add src/ to path
SRC = str(Path(__file__).resolve().parents[2] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import librosa
import torch
import websockets
import websockets.asyncio.server

# ML imports
from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForSequenceClassification
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gender_test")

PORT = 8898
MODEL_DIR = "/Users/nmcxyz/Desktop/MyFolder/NobleX/Ref/Common-Voice-Gender-Detection"

logger.info("Đang tải model (tốn vài giây)...")
try:
    model = Wav2Vec2ForSequenceClassification.from_pretrained(MODEL_DIR)
    processor = Wav2Vec2FeatureExtractor.from_pretrained(MODEL_DIR)
    logger.info("Tải model thành công!")
except Exception as e:
    logger.error(f"Lỗi khi tải model: {e}")
    sys.exit(1)

id2label = {"0": "female", "1": "male"}


# ── Hàm chạy mô hình tốn CPU (Chạy ngầm) ────────────────────────────────────────────────
def process_audio_blocking(temp_path: str):
    """
    Đây là hàm đồng bộ (blocking). Thao tác PyTorch và librosa.load sẽ block CPU.
    Hàm này SẼ ĐƯỢC CHẠY async trên ThreadPool để không làm treo Event Loop chính.
    """
    try:
        t0 = time.time()
        # Đọc file âm thanh (librosa cần ffmpeg để xử lý webm từ trình duyệt)
        speech, sample_rate = librosa.load(temp_path, sr=16000)

        # Xử lý input cho transformers
        inputs = processor(speech, sampling_rate=sample_rate, return_tensors="pt", padding=True)

        # Predict
        with torch.no_grad():
            outputs = model(**inputs)
            logits = outputs.logits
            probs = torch.nn.functional.softmax(logits, dim=1).squeeze().tolist()

        prediction = {id2label[str(i)]: round(probs[i], 3) for i in range(len(probs))}
        detected_gender = max(prediction, key=prediction.get)
        t1 = time.time()
        logger.info(f"Hoàn thành inference sau {round((t1 - t0) * 1000)}ms - {detected_gender}")

        return {
            "success": True,
            "prediction": prediction,
            "detected": detected_gender,
            "duration": round((t1 - t0) * 1000),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ── Mô phỏng System Prompt ────────────────────────────────────────────────
def simulate_system_prompt_injection(gender_result):
    before = "═══ THÔNG TIN KHÁCH HÀNG ═══\nXưng hô: Quý Khách"
    honorific = "Anh" if gender_result == "male" else "Chị"
    gender_vie = "Nam" if gender_result == "male" else "Nữ"
    after = f"═══ THÔNG TIN KHÁCH HÀNG ═══\nGiới tính: {gender_vie}\nXưng hô: {honorific}"
    return before, after


# ── WebSocket Handler ──────────────────────────────────────────────────
async def ws_handler(ws: websockets.asyncio.server.ServerConnection):
    logger.info("WS client connected")
    try:
        async for raw_data in ws:
            # Nhận dạng byte buffer (âm thanh từ trình duyệt)
            if isinstance(raw_data, bytes):
                logger.info(f"Đã nhận file âm thanh ({len(raw_data)} bytes). Đang đẩy vào Background Thread...")

                start_time = time.time()
                await ws.send(json.dumps({"type": "processing", "message": "Đang chạy model phân tích giới tính..."}))

                # Lưu tạm âm thanh để librosa đọc
                with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
                    tmp.write(raw_data)
                    tmp_path = tmp.name

                # CHÚ Ý QUAN TRỌNG:
                # asyncio.to_thread() sẽ đẩy tác vụ xử lý của PyTorch sang một thread phụ.
                # Bằng cách này, Event Loop (nơi điều phối WebRTC/STT/LLM Streaming) KHÔNG HỀ BỊ CHẶN!
                result = await asyncio.to_thread(process_audio_blocking, tmp_path)

                os.remove(tmp_path)

                total_time = round((time.time() - start_time) * 1000)

                if result["success"]:
                    before, after = simulate_system_prompt_injection(result["detected"])
                    await ws.send(
                        json.dumps(
                            {
                                "type": "result",
                                "prediction": result["prediction"],
                                "detected": result["detected"],
                                "prompt_before": before,
                                "prompt_after": after,
                                "inference_ms": result["duration"],
                                "total_ms": total_time,
                            }
                        )
                    )
                else:
                    await ws.send(json.dumps({"type": "error", "message": result["error"]}))
            else:
                pass

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        logger.error(f"WS error: {e}")
    finally:
        logger.info("WS client disconnected")


HTML_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <title>Voice Gender Detection Test</title>
    <style>
        body { font-family: -apple-system, system-ui, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; max-width: 800px; margin: auto; }
        div { margin-bottom: 20px; }
        h1 { color: #58a6ff; }
        .box { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; }
        button { background: #238636; color: white; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-size: 16px; font-weight: bold; }
        button:disabled { background: #484f58; cursor: not-allowed; }
        #record-btn.recording { background: #da3633; animation: pulse 1s infinite alternate; }
        @keyframes pulse { from { opacity: 1; } to { opacity: 0.6; } }
        pre { background: #010409; padding: 10px; border: 1px solid #30363d; border-radius: 6px; white-space: pre-wrap; font-size: 14px;}
        .highlight { color: #3fb950; font-weight: bold; }
    </style>
</head>
<body>
    <h1>🎙️ Voice Gender Detection Async Test</h1>
    <p>Chạm vào nút để thu âm khoảng 2 đến 3 giây, sau đó hệ thống sẽ tự gửi âm thanh qua WebSocket và chạy model dạng Background Thread.</p>
    
    <div class="box">
        <button id="record-btn">Nhấn để Bắt Đầu Thu Âm</button>
        <span id="status" style="margin-left:15px; color:#c9d1d9;">Sẵn sàng.</span>
    </div>

    <div class="box" id="results" style="display:none;">
        <h3>Kết quả nhận diện (Background Task)</h3>
        <p><strong>Thời gian xử lý:</strong> <span id="time-ms"></span></p>
        <p><strong>Dự đoán (%):</strong> <span id="pred"></span></p>
        
        <hr style="border-color: #30363d; margin: 20px 0;">
        
        <h3>Mô phỏng thay đổi System Prompt</h3>
        <div style="display:flex; gap:20px;">
            <div style="flex:1;">
                <h4>TRƯỚC KHI CÓ GIỚI TÍNH</h4>
                <pre id="before" style="color: #6e7681;"></pre>
            </div>
            <div style="flex:1;">
                <h4>SAU KHI MODEL UPDATE</h4>
                <pre id="after" style="color: #58a6ff;"></pre>
            </div>
        </div>
    </div>

<script>
    let ws = new WebSocket('ws://' + location.host + '/ws');
    let recordBtn = document.getElementById('record-btn');
    let statusEl = document.getElementById('status');
    let resultsDiv = document.getElementById('results');
    
    let mediaRecorder;
    let audioChunks = [];

    ws.onopen = () => { statusEl.textContent = "WebSocket đã kết nối. Nhấn để thu âm."; };
    ws.onmessage = (e) => {
        let msg = JSON.parse(e.data);
        if (msg.type === "processing") {
            statusEl.textContent = msg.message;
        } else if (msg.type === "result") {
            statusEl.innerHTML = `<span style="color:#56d364;">Hoàn thành! Model trả về: <b>${msg.detected}</b></span>`;
            resultsDiv.style.display = 'block';
            document.getElementById('time-ms').innerHTML = `Inference PyTorch: ${msg.inference_ms}ms | Tổng khứ hồi: ${msg.total_ms}ms`;
            document.getElementById('pred').innerText = JSON.stringify(msg.prediction);
            document.getElementById('before').innerText = msg.prompt_before;
            document.getElementById('after').innerText = msg.prompt_after;
            recordBtn.disabled = false;
        } else if (msg.type === "error") {
            statusEl.textContent = `Lỗi: ${msg.message}`;
            recordBtn.disabled = false;
        }
    };

    recordBtn.onclick = async () => {
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
            return;
        }
        audioChunks = [];
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
        mediaRecorder.onstop = () => {
            const blob = new Blob(audioChunks, { type: 'audio/webm' });
            ws.send(blob);
            recordBtn.textContent = 'Nhấn để Bắt Đầu Thu Âm';
            recordBtn.classList.remove('recording');
            recordBtn.disabled = true;
            statusEl.textContent = 'Đang gửi và xử lý...';
            // Tắt stream mic
            stream.getTracks().forEach(t => t.stop());
        };
        mediaRecorder.start();
        recordBtn.textContent = 'Dừng Thu Âm (Gửi đi)';
        recordBtn.classList.add('recording');
        statusEl.textContent = 'Đang ghi âm...';
        
        // Tự động dừng sau 3 giây
        setTimeout(() => { if(mediaRecorder.state === 'recording') mediaRecorder.stop(); }, 3000);
    };
</script>
</body>
</html>
"""


def process_request(connection, request: Request):
    if request.path == "/":
        return Response(200, "OK", Headers({"Content-Type": "text/html; charset=utf-8"}), HTML_PAGE.encode("utf-8"))
    if request.path != "/ws":
        return Response(404, "Not Found", Headers(), b"")
    return None


async def main():
    logger.info(f"Khởi động Web UI: http://localhost:{PORT}")
    async with websockets.asyncio.server.serve(ws_handler, "0.0.0.0", PORT, process_request=process_request) as server:
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
