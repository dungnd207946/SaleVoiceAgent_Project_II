# lipsync-musetalk :8020 — lip sync thời gian thực (MuseTalk 1.5) cho tab Voice của portal.
# Build context = CHÍNH thư mục này (service tự chứa):
#   docker build -f lipsync_musetalk/Dockerfile -t odyssey-lipsync-musetalk lipsync_musetalk
#
# Base slim như tts_omnivoice: wheel torch cu128 mang sẵn thư viện CUDA, chỉ cần driver
# của host qua nvidia-container-toolkit. Image KHÔNG chứa weights (~3,9 GB) — tải về volume
# `/data` lúc boot đầu (weights.py), cùng nguyên tắc với mọi service khác trong repo.
FROM python:3.11-slim

# ffmpeg: tách frame khi dựng avatar lần đầu (avatar.py). libgl1 + libglib2.0-0: opencv
# bản đầy đủ mà rtmlib (DWPose ONNX) đòi — xem requirements.txt.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install -r requirements.txt

# Code + video nhân vật gốc (avatars/nguoi-dan.mp4) — avatar được DỰNG từ video này ở
# lần boot đầu rồi cache vào volume (avatar.py); đổi video = build image mới = tự dựng lại.
COPY . .

EXPOSE 8020 8021
ENV PYTHONUNBUFFERED=1 \
    LIPSYNC_DATA_DIR=/data
CMD ["python3", "lipsync_server.py"]
