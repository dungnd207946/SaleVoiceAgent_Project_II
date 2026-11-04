import logging
import sys
import time
from pathlib import Path

# Add src to path
SRC = str(Path(__file__).resolve().parents[2] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    from noble_agent.voice.gender_detector import GenderDetector

    print("=" * 60)
    print("   TEST GENDER DETECTOR (Nền tảng RAW PCM)   ")
    print("=" * 60)

    t0 = time.time()
    detector = GenderDetector.get_instance()
    t1 = time.time()
    print(f"\n[1] Thời gian khởi tạo/nạp Model: {round((t1 - t0) * 1000)}ms")

    # Tạo một mảng PCM ảo (Giả lập mảng âm thanh)
    # Ví dụ: 3 giây âm thanh 16kHz 16-bit PCM = 3 * 16000 * 2 = 96,000 bytes
    # Hoặc nếu bạn có 1 file chuẩn dạng đuôi .wav 16kHz, bạn có thể truyền thẳng vào mảng dưới đây.

    import numpy as np

    # Tạo luồng âm thanh ngẫu nhiên (noise giả lập để test log và tốc độ)
    fake_audio_pcm = np.random.randint(-32768, 32767, size=(48000,), dtype=np.int16).tobytes()

    print(f"\n[2] Gửi {len(fake_audio_pcm)} bytes Raw PCM (3 giây thu âm) cho Model...")

    t2 = time.time()
    result = detector.predict(fake_audio_pcm)
    t3 = time.time()

    print(f"\n✅ Kết quả trả về: '{result}' (M=Nam, F=Nữ)")
    print(f"✅ Tốc độ xử lý Inference cốt lõi: {round((t3 - t2) * 1000)}ms")
    print("=" * 60)
    print("\n* LƯU Ý:")
    print("Kết quả có thể ra F vì đây là mảng byte ngẫu nhiên (trắng) dùng để test hiệu năng.")
    print("Để test log/debug với hệ thống thật sự, bạn hãy gọi điện thẳng cho con Bot!")


if __name__ == "__main__":
    main()
