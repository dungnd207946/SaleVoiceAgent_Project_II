"""Generate an RTP/PCMU pcap for sipp `pcap_play` from a source audio file.

Why: sipp plays caller audio at load-test time by replaying a pcap file
(one RTP stream, 20 ms PCMU frames at 8 kHz). We need a Vietnamese
utterance pcap so the worker's STT+LLM+TTS pipeline exercises the real
code path — not silence.

Input:
    A mono PCM16 .wav at ANY sample rate (we resample via audioop).
    OR a raw .pcm file if you pass --raw --rate N (e.g. the pre-synth
    ack assets in assets/voice/acks/).

Output:
    LINKTYPE_ETHERNET pcap with UDP/RTP/PCMU packets, 20 ms apart,
    payload type 0, sequence + timestamp + ssrc correctly incremented.

Usage:
    # From a wav:
    uv run python scripts/load_test/gen_pcap.py \\
        --in some_voice.wav \\
        --out scripts/load_test/fixtures/utterance_pcmu.pcap

    # From a 24 kHz raw PCM16 (e.g. an ack asset):
    uv run python scripts/load_test/gen_pcap.py \\
        --in assets/voice/acks/01_em_can_kiem_tra_thong_tin_trong_he_thong_quy_khach.pcm \\
        --raw --rate 24000 \\
        --out scripts/load_test/fixtures/utterance_pcmu.pcap

Notes:
- Source/dest IP/port in the pcap are placeholders; sipp rewrites them
  at playback to match the SIP dialog's negotiated RTP endpoints.
- We build raw RTP (V=2, PT=0, CSRC=0, no extensions). That's what any
  sane SIP peer expects on a G.711 stream.
"""
from __future__ import annotations

import argparse
import audioop
import struct
import sys
import wave
from pathlib import Path


# ── Constants ────────────────────────────────────────────────────────────────

PCMU_RATE = 8000           # G.711 μ-law is fixed at 8 kHz
FRAME_MS = 20              # one RTP packet per 20 ms of audio
FRAME_SAMPLES = PCMU_RATE * FRAME_MS // 1000  # 160 samples / 160 bytes PCMU

# Pcap linktypes
LINKTYPE_ETHERNET = 1

# Placeholder addresses — sipp rewrites these at playback. Values just
# need to produce a valid IP header checksum.
# Use loopback for the source — sipp's pcap_play replays the pcap's source
# IP/port verbatim, and the OS refuses `sendto` from any address not bound
# to a local interface. 127.0.0.1 is always bound.
SRC_IP = (127, 0, 0, 1)
DST_IP = (127, 0, 0, 1)
SRC_MAC = b"\x00\x00\x5e\x00\x53\x01"
DST_MAC = b"\x00\x00\x5e\x00\x53\x02"
# SRC_PORT must NOT collide with sipp's own media port (-mp in the driver,
# default 40000). pcap_play binds this port at replay time; if sipp already
# holds it, `sendto` fails with "Can't assign requested address".
SRC_PORT = 40100
DST_PORT = 40002


# ── Audio load + convert ─────────────────────────────────────────────────────

def _load_pcm16_from_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise SystemExit(f"wav must be 16-bit PCM (got {w.getsampwidth() * 8} bit)")
        if w.getnchannels() != 1:
            raise SystemExit(f"wav must be mono (got {w.getnchannels()} ch)")
        return w.readframes(w.getnframes()), w.getframerate()


def _load_pcm16_raw(path: Path, rate: int) -> tuple[bytes, int]:
    data = path.read_bytes()
    if len(data) % 2 != 0:
        raise SystemExit(f"raw pcm16 file has odd byte count: {len(data)}")
    return data, rate


def _to_pcmu_8k(pcm16: bytes, src_rate: int) -> bytes:
    if src_rate != PCMU_RATE:
        pcm16, _ = audioop.ratecv(pcm16, 2, 1, src_rate, PCMU_RATE, None)
    return audioop.lin2ulaw(pcm16, 2)


# ── Packet builders ──────────────────────────────────────────────────────────

def _ipv4_checksum(header: bytes) -> int:
    if len(header) % 2 != 0:
        header += b"\x00"
    total = 0
    for i in range(0, len(header), 2):
        total += (header[i] << 8) | header[i + 1]
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def _build_rtp(seq: int, ts: int, ssrc: int, payload: bytes) -> bytes:
    # V=2, P=0, X=0, CC=0, M=0, PT=0 (PCMU)
    first_byte = 0x80
    second_byte = 0x00
    return struct.pack("!BBHII", first_byte, second_byte, seq & 0xFFFF, ts & 0xFFFFFFFF, ssrc & 0xFFFFFFFF) + payload


def _build_udp(src_port: int, dst_port: int, payload: bytes) -> bytes:
    udp_len = 8 + len(payload)
    # checksum=0 → disabled (allowed over IPv4); sipp replays verbatim
    return struct.pack("!HHHH", src_port, dst_port, udp_len, 0) + payload


def _build_ipv4(src: tuple, dst: tuple, udp_frame: bytes) -> bytes:
    total_len = 20 + len(udp_frame)
    header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,           # Version=4, IHL=5
        0x00,           # DSCP/ECN
        total_len,
        0x0000,         # Identification
        0x4000,         # Flags=DF, FragOffset=0
        64,             # TTL
        17,             # UDP
        0x0000,         # checksum placeholder
        bytes(src),
        bytes(dst),
    )
    csum = _ipv4_checksum(header)
    header = header[:10] + struct.pack("!H", csum) + header[12:]
    return header + udp_frame


def _build_ethernet(frame: bytes) -> bytes:
    return DST_MAC + SRC_MAC + b"\x08\x00" + frame


# ── Pcap writer ──────────────────────────────────────────────────────────────

# pcap container uses host-native byte order (we pick little-endian — what
# most tools write). Network protocol headers below remain big-endian.

def _pcap_global_header() -> bytes:
    return struct.pack(
        "<IHHIIII",
        0xA1B2C3D4,         # magic — reader infers endianness from this field
        2, 4,               # version_major, version_minor
        0,                  # thiszone
        0,                  # sigfigs
        65535,              # snaplen
        LINKTYPE_ETHERNET,  # network
    )


def _pcap_record(ts_sec: int, ts_usec: int, frame: bytes) -> bytes:
    return struct.pack("<IIII", ts_sec, ts_usec, len(frame), len(frame)) + frame


# ── Orchestrator ─────────────────────────────────────────────────────────────

def write_pcap(pcmu: bytes, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    ssrc = 0x5A5A_5A5A
    seq = 0
    ts = 0  # RTP timestamp in samples (8k clock)
    ts_sec = 0
    ts_usec = 0

    n_frames = len(pcmu) // FRAME_SAMPLES
    if n_frames == 0:
        raise SystemExit("audio shorter than one 20 ms frame — nothing to write")

    with out.open("wb") as f:
        f.write(_pcap_global_header())

        for i in range(n_frames):
            payload = pcmu[i * FRAME_SAMPLES : (i + 1) * FRAME_SAMPLES]
            rtp = _build_rtp(seq, ts, ssrc, payload)
            udp = _build_udp(SRC_PORT, DST_PORT, rtp)
            ipv4 = _build_ipv4(SRC_IP, DST_IP, udp)
            eth = _build_ethernet(ipv4)
            f.write(_pcap_record(ts_sec, ts_usec, eth))

            seq += 1
            ts += FRAME_SAMPLES
            ts_usec += FRAME_MS * 1000
            if ts_usec >= 1_000_000:
                ts_sec += ts_usec // 1_000_000
                ts_usec %= 1_000_000

    return n_frames


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--in", dest="src", required=True, type=Path, help="source wav or pcm16 file")
    ap.add_argument("--out", required=True, type=Path, help="output pcap path")
    ap.add_argument("--raw", action="store_true", help="source is raw pcm16 (use with --rate)")
    ap.add_argument("--rate", type=int, default=0, help="sample rate for --raw sources")
    args = ap.parse_args()

    if args.raw:
        if args.rate <= 0:
            raise SystemExit("--raw requires --rate")
        pcm16, src_rate = _load_pcm16_raw(args.src, args.rate)
    else:
        if not args.src.suffix.lower() == ".wav":
            print(f"warn: non-wav input without --raw; assuming wav container: {args.src}", file=sys.stderr)
        pcm16, src_rate = _load_pcm16_from_wav(args.src)

    pcmu = _to_pcmu_8k(pcm16, src_rate)
    n = write_pcap(pcmu, args.out)
    secs = n * FRAME_MS / 1000
    print(f"wrote {args.out}  frames={n}  duration={secs:.2f}s  (src_rate={src_rate}Hz → PCMU/{PCMU_RATE})")


if __name__ == "__main__":
    main()
