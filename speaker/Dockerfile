# Standalone speaker-embedding service — sherpa-onnx CAM++ (CPU). Self-contained:
# no dependency on any agent image. Model auto-pulled from HF to a mounted volume.
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    sherpa-onnx \
    huggingface_hub \
    "fastapi>=0.110" \
    "uvicorn[standard]>=0.29" \
    numpy

COPY speaker_server.py /app/speaker_server.py

EXPOSE 8014
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "speaker_server:app", "--host", "0.0.0.0", "--port", "8014"]
