"""Unified settings for noble_agent.

Merges all fields from noble_agent.config.Settings (legacy) and
noble_agent_refactor.config.RefactorSettings, minus the handoff fields
that are no longer meaningful in the unified architecture.

Removed refactor fields (not carried over):
  - default_agent
  - max_handoff_chain
  - auto_briefing_lookback
  - briefing_model
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Built-in defaults for the remote STT/TTS service URLs. Used both as the field
# defaults (env var absent) and by the validator below (env var present but
# empty/blank → fall back to these instead of an unusable "").
_DEFAULT_STT_SERVICE_URL = "ws://127.0.0.1:8770/stt"
_DEFAULT_TTS_SERVICE_URL = "ws://127.0.0.1:8771/tts"
_SERVICE_URL_DEFAULTS = {
    "stt_service_url": _DEFAULT_STT_SERVICE_URL,
    "tts_service_url": _DEFAULT_TTS_SERVICE_URL,
}


def parse_probe_schedule(
    marks_csv: str, bonus_csv: str, match_threshold: float
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """CSV → (mốc probe, ngưỡng probe). Ngưỡng = match_threshold + bonus[i].

    CSV chứ không phải list[float]: pydantic-settings đòi cú pháp JSON cho kiểu
    list, nên "0.25,0.4" trong .env sẽ nổ khi parse.
    """
    marks = tuple(float(x) for x in marks_csv.split(",") if x.strip())
    bonus = tuple(float(x) for x in bonus_csv.split(",") if x.strip())
    if not marks or not bonus:
        raise ValueError("SPV_PROBE_MARKS_SEC / SPV_PROBE_BONUS không được rỗng")
    if len(marks) != len(bonus):
        raise ValueError(
            f"SPV_PROBE_MARKS_SEC ({len(marks)}) và SPV_PROBE_BONUS ({len(bonus)}) phải cùng số phần tử"
        )
    if any(b <= a for a, b in zip(marks, marks[1:], strict=False)):
        raise ValueError(f"SPV_PROBE_MARKS_SEC phải tăng dần nghiêm ngặt: {marks}")
    thresholds = tuple(match_threshold + b for b in bonus)
    if any(not (0.0 < t <= 1.0) for t in thresholds):
        raise ValueError(f"ngưỡng probe ngoài khoảng (0, 1]: {thresholds}")
    return marks, thresholds


class UnifiedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── flags ──────────────────────────────────────────────────────────────────
    use_unified_agent: bool = Field(False, alias="USE_UNIFIED_AGENT")
    # Simulate a random VN mobile when a session opens with no phone (so a
    # /chat or browser session still persists under a phone key). Only fills an
    # EMPTY phone — a telephony-seeded real caller number is left intact. Set
    # NOBLE_SIMULATE_PHONE=false on trunk-only deploys to keep "no phone → no
    # persist" for anonymous PSTN calls.
    noble_simulate_phone: bool = Field(True, alias="NOBLE_SIMULATE_PHONE")

    # Testing knobs for the simulated-phone path (chat + LiveKit go through
    # ensure_session_started). NOBLE_SIMULATE_PHONE_NUMBER pins a fixed caller
    # phone (empty → random) — set one present in tenant_data.contacts to
    # exercise the DB profile lookup (telephony-sim). NOBLE_SIMULATE_CUSTOMER is
    # a JSON object of Customer fields seeded before the bootstrap (app-client
    # sim, mirroring the browser set_customer push); empty → phone only.
    simulate_phone_number: str = Field("", alias="NOBLE_SIMULATE_PHONE_NUMBER")
    simulate_customer: str = Field("", alias="NOBLE_SIMULATE_CUSTOMER")

    # DB project registry (tool-schema code enums + prompt project table) is
    # warmed once at boot. To pick up ma_du_an changes without a restart, the
    # start of each new call re-warms it — but only if the last warm was longer
    # ago than this TTL (debounce, so a burst of calls shares one DB query).
    # 0 disables the per-call refresh (boot-warmed cache only → restart to update).
    project_registry_refresh_sec: int = Field(120, alias="NOBLE_PROJECT_REGISTRY_REFRESH_SEC")

    # ── agent core (from refactor, minus removed handoff fields) ──────────────
    summary_threshold_K: int = Field(8, alias="NOBLE_SUMMARY_K")
    summary_keep_tail: int = Field(4, alias="NOBLE_SUMMARY_KEEP_TAIL")
    # After a summary is persisted, fire a background throwaway LLM call that
    # replays the next turn's exact request shape so the provider's prompt cache
    # is warm before the next live turn. Provider-agnostic (see design spec).
    summary_warm_cache: bool = Field(True, alias="NOBLE_SUMMARY_WARM_CACHE")
    # Per-path primary-provider pin. The value must match one of the
    # configured per-provider model names (`ANTHROPIC_MODEL`,
    # `OPENAI_MODEL`, `GEMINI_MODEL`) — that match identifies the primary
    # provider for the path. If empty or no match, that path falls back
    # to the default provider chain order (anthropic → openai → gemini),
    # still asking each provider with its own `<P>_MODEL`.
    agent_model: str = Field("", alias="NOBLE_AGENT_MODEL")
    summary_model: str = Field("", alias="NOBLE_SUMMARY_MODEL")
    semcache_model: str = Field("", alias="NOBLE_SEMCACHE_MODEL")
    # Follow-up suggestion chips (quick-reply) generated after each chat turn.
    suggestions_enabled: bool = Field(True, alias="NOBLE_SUGGESTIONS_ENABLED")
    suggestions_model: str = Field("", alias="NOBLE_SUGGESTIONS_MODEL")
    # Agent display name used in the system prompt, greeting, and prompt labels.
    agent_name: str = Field("Luna", alias="NOBLE_AGENT_NAME")
    # Source of the agent's persona/scope/tools config: "legacy" (config.json +
    # manifest.toml, current behavior) | "db" (Portal Postgres published config +
    # on-disk skeleton — see agent/facade.py::_agent_def_from_db).
    agent_config_source: str = "legacy"
    agent_temperature: float = 0.7  # DB path only: replaces persona/config.json
    agent_max_tokens: int = 800  # DB path only: replaces persona/config.json
    tenant_id: str = "noble"
    # ── multi-tenant store (SaaS slice #1) ─────────────────────────────────────
    tenant_store_enabled: bool = Field(False, alias="TENANT_STORE_ENABLED")
    minio_endpoint: str = Field("", alias="MINIO_ENDPOINT")
    minio_root_user: str = Field("", alias="MINIO_ROOT_USER")
    minio_root_password: str = Field("", alias="MINIO_ROOT_PASSWORD")
    tenant_bucket: str = Field("hotline-tenants", alias="TENANT_BUCKET")
    tenant_materialize_dir: str = Field("/var/lib/noble/tenants", alias="TENANT_MATERIALIZE_DIR")
    # TTL (seconds) for the published-version pointer read (SP-C2, YC03). A new
    # conversation picks up a newly published version within ~this window; the
    # pointer read is TTL-cached, not a per-conversation store round-trip. 0 =
    # resolve at boot only.
    noble_config_poll_sec: float = Field(20.0, alias="NOBLE_CONFIG_POLL_SEC")
    # ── SP-D heartbeat (C3): agent proactively writes <tenant>/_heartbeat.json to
    # the tenant store every ~heartbeat_sec so Backend/Dashboard can INFER status
    # (fresh<=60s, applying>2min→E03) — no one polls the agent (BR02). Inert unless
    # the tenant store is enabled (nowhere to write otherwise); disable independently
    # via NOBLE_HEARTBEAT_ENABLED without turning off the store.
    heartbeat_enabled: bool = Field(True, alias="NOBLE_HEARTBEAT_ENABLED")
    heartbeat_sec: float = Field(20.0, alias="NOBLE_HEARTBEAT_SEC")
    # ── SaaS slice #2: provider-facing gateway ─────────────────────────────────
    tenant_endpoint_template: str = Field("wss://{tenant_id}.agents.noblex.vn", alias="TENANT_ENDPOINT_TEMPLATE")
    gateway_host: str = Field("0.0.0.0", alias="GATEWAY_HOST")
    gateway_port: int = Field(9200, alias="GATEWAY_PORT")
    gateway_cred_cache_ttl_sec: float = Field(30.0, alias="GATEWAY_CRED_CACHE_TTL_SEC")
    gateway_worker_secret: str = Field("", alias="GATEWAY_WORKER_SECRET")
    # URL đầy đủ của Portal runtime-credentials API (POST, Bearer = API key của provider).
    # Rỗng ⇒ gateway fail-closed: từ chối MỌI kết nối với reason auth_api_unavailable.
    gateway_credentials_api_url: str = Field("", alias="GATEWAY_CREDENTIALS_API_URL")
    worker_chat_internal_url_template: str = Field("ws://agent:8766/chat", alias="WORKER_CHAT_INTERNAL_URL_TEMPLATE")
    enable_slow_thinker: bool = Field(True, alias="NOBLE_ENABLE_SLOW_THINKER")
    session_ttl_seconds: int = Field(86400, alias="NOBLE_SESSION_TTL")
    # Noisy-neighbor guard: in-process cap on concurrent /chat sessions (Plan 3).
    # <=0 = unbounded. Default wide — chat is I/O-bound; the point is the seam.
    chat_max_concurrent_sessions: int = Field(200, alias="CHAT_MAX_CONCURRENT_SESSIONS")
    use_refactor_core: bool = Field(False, alias="USE_REFACTOR_CORE")
    search_backend: Literal["rag", "grep", "empty"] = Field("rag", alias="NOBLE_SEARCH_BACKEND")
    transcript_log_enabled: bool = Field(False, alias="NOBLE_TRANSCRIPT_LOG_ENABLED")
    transcript_log_dir: str = Field("data/training_logs", alias="NOBLE_TRANSCRIPT_LOG_DIR")

    # ── semantic cache (deferred; disabled by default in unified) ──────────────
    semcache_enabled: bool = Field(False, alias="NOBLE_SEMCACHE_ENABLED")
    semcache_num_predictions: int = Field(5, alias="NOBLE_SEMCACHE_NUM_PREDICTIONS")
    semcache_threshold: float = Field(0.85, alias="NOBLE_SEMCACHE_THRESHOLD")
    semcache_embed_model: str = Field("intfloat/multilingual-e5-small", alias="NOBLE_SEMCACHE_EMBED_MODEL")
    semcache_predictor_temperature: float = Field(0.8, alias="NOBLE_SEMCACHE_PREDICTOR_TEMPERATURE")
    semcache_history_lookback: int = Field(8, alias="NOBLE_SEMCACHE_HISTORY_LOOKBACK")

    # ── STT backend selection ──────────────────────────────────────────────────
    stt_backend: str = "soniox"  # "sherpa" | "soniox" | "qwen3asr" | "elevenlabs" | "remote"

    # ── TTS backend selection ──────────────────────────────────────────────────
    tts_backend: str = "vieneu"  # "vieneu" | "vieneu_vllm" | "elevenlabs" | "remote" | "hotline_ws"

    # ── Remote STT/TTS services (backend "remote") ─────────────────────────────
    # Client: agent worker đặt STT_BACKEND/TTS_BACKEND=remote và trỏ *_SERVICE_URL
    # tới service WS thường trú (cùng host hoặc máy GPU khác). URL đầy đủ, không
    # giả định localhost → tách máy chỉ là đổi .env.
    stt_service_url: str = _DEFAULT_STT_SERVICE_URL
    tts_service_url: str = _DEFAULT_TTS_SERVICE_URL
    # Server bind (dùng bởi stt_server/tts_server main()). 0.0.0.0 cho máy khác kết nối.
    stt_service_host: str = "0.0.0.0"
    stt_service_port: int = 8770
    tts_service_host: str = "0.0.0.0"
    tts_service_port: int = 8771
    # Speaker-embedding service (speaker_server). Bind host/port for the resident
    # HTTP service; workers reach it via SPEAKER_REMOTE_URL.
    speaker_service_host: str = "0.0.0.0"
    speaker_service_port: int = 9100
    # Which engine the resident TTS service (tts_server) uses INTERNALLY. The worker
    # is unaffected (it stays TTS_BACKEND=remote, talking WS to this service).
    #   "vieneu"      → in-process transformers backbone + token streaming (GPU here)
    #   "vieneu_vllm" → client to a separate vLLM server (start scripts/run_vllm_tts.sh);
    #                   the GPU backbone lives in vLLM, this service only runs the codec.
    tts_service_engine: str = "vieneu"  # "vieneu" | "vieneu_vllm"
    # Tùy chọn (rỗng = tắt xác thực). Khi đặt: client gửi header
    # `Authorization: Bearer <token>`; server từ chối kết nối thiếu/sai token.
    voice_service_auth_token: str = ""

    @field_validator("stt_service_url", "tts_service_url", mode="before")
    @classmethod
    def _service_url_or_default(cls, v: object, info) -> object:
        """Empty/blank STT_SERVICE_URL / TTS_SERVICE_URL → built-in default.

        Lets `.env` leave the var blank (or set it explicitly) without breaking
        the client: a blank value falls back to ws://127.0.0.1:877{0,1}/...,
        a real value is used verbatim (trimmed).
        """
        if v is None or (isinstance(v, str) and not v.strip()):
            return _SERVICE_URL_DEFAULTS[info.field_name]
        return v.strip() if isinstance(v, str) else v

    # ── STT: sherpa-onnx ──────────────────────────────────────────────────────
    sherpa_model_dir: str = ""
    # false → encoder-*.onnx (excluding *.int8.onnx); true → encoder-*.int8.onnx.
    # The filename stem is auto-discovered by globbing SHERPA_MODEL_DIR.
    sherpa_model_quantize: bool = False
    sherpa_preserve_case: bool = True
    sherpa_chunk_size: int = 16
    sherpa_num_threads: int = 2
    sherpa_rule1_min_trailing_silence: float = 2.4
    sherpa_rule2_min_trailing_silence: float = 1.2
    sherpa_rule3_min_utterance_length: float = 20.0
    # Transducer decoding. "greedy_search" (default, fastest) or
    # "modified_beam_search" (N-best, more accurate on rare words / code-switch,
    # ~N× CPU). Loading a hotwords file forces modified_beam_search regardless.
    sherpa_decoding_method: str = "greedy_search"
    sherpa_max_active_paths: int = 4  # beam width when modified_beam_search is active
    sherpa_hotwords_file: str = "data/hotwords.txt"
    sherpa_hotwords_score: float = 2.0
    # Auto-pull the model from HuggingFace when SHERPA_MODEL_DIR is missing the
    # expected files (CD: the gitignored models/ dir isn't in the repo).
    sherpa_hf_repo: str = "NobleX-AI/santa-stt"
    sherpa_hf_revision: str = "prod"  # HF branch/tag to pull the sherpa repo from
    hf_token: str = ""  # reads HF_TOKEN; "" = anonymous / huggingface_hub env default

    # ── Speaker verification (opt-in; remote-default like gender_detector) ──────
    speaker_verification_enabled: bool = False  # DEPRECATED — use SPEAKER_MODE=single
    # Speaker policy. "off" | "single" | "multi". Replaces speaker_verification_enabled
    # (legacy true → resolved to "single" by config.resolve_speaker_mode()).
    speaker_mode: str = "off"
    speaker_remote_url: str = ""  # non-empty → remote embedder (default); empty → local sherpa
    speaker_remote_timeout: float = 3.0
    speaker_remote_token: str = ""  # optional bearer for the remote embedder
    speaker_model_dir: str = "models/speaker"  # (local) ONNX dir
    speaker_model_name: str = "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"  # (local) ONNX file
    speaker_hf_repo: str = "csukuangfj/speaker-embedding-models"  # (local) single-file provision source
    speaker_hf_revision: str = "main"  # public csukuangfj repo has only `main` (set to your mirror's tag if different)
    speaker_match_threshold: float = 0.5  # min cosine to accept as the same speaker
    speaker_min_enroll_sec: float = 1.0  # min utterance length to enroll
    # ── Speaker registry + fast barge-in (spec 2026-09-03) ────────────────────
    # Ba ngưỡng thực thi đều suy ra từ speaker_match_threshold: probe mốc i =
    # MATCH + bonus[i]; nhận diện ở final = MATCH; ghi centroid = MATCH + adapt_margin.
    spv_probe_marks_sec: str = "0.25,0.4,0.6,0.9,1.3"  # mốc embed tích luỹ từ đầu utterance
    spv_probe_bonus: str = "0.15,0.1,0.05,0,0"  # siết thêm cho từng mốc (cửa sổ ngắn → chặt hơn)
    spv_probe_tail_window_sec: float = 1.5  # hết chuỗi mốc → cửa sổ TRƯỢT dài bấy nhiêu
    spv_probe_tail_hop_sec: float = 1.0  # nhịp trượt giai đoạn đuôi
    spv_enroll_window_sec: float = 1.5  # cửa sổ trượt khi enroll
    spv_enroll_hop_sec: float = 0.75  # bước trượt (chồng lấn 50%)
    spv_enroll_consensus_sim: float = 0.5  # thang RIÊNG: hai lát cùng câu nói, không neo vào MATCH
    spv_enroll_min_cluster: int = 2  # cụm nhỏ hơn → không enroll (fail-open, để tập rỗng)
    spv_adapt_margin: float = 0.1  # siết thêm khi GHI centroid; 0 = hành vi spec 2026-08-28
    spv_max_identities: int = 4  # cap FIFO danh tính mỗi phiên
    spv_max_centroids: int = 10  # cap FIFO centroid mỗi danh tính
    spv_min_match_probe: int = 2  # probe phải khớp ≥ N centroid mới tính speaker (kẹp theo cỡ tập)
    spv_min_match_identify: int = 1  # identify() đường nguội theo cosine hạng N; 1 = max (hành vi cũ)
    spv_mismatch_streak_max: int = 2  # số final "không khớp ai" LIÊN TIẾP trước khi bỏ asker;
    # chỉ đếm final có cụm nhất quán (cluster >= spv_enroll_min_cluster) — final quá
    # ngắn/không bằng chứng không tính.
    spv_utt_cap_sec: float = 30.0  # cap PCM giữ cho một utterance

    # ── Observability: Arize Phoenix (self-hosted OTEL LLM tracing) ────────────
    # Empty `phoenix_collector_endpoint` is the gate: no endpoint → clean no-op
    # (no import, no crash). See observability/phoenix_tracing.py.
    phoenix_api_key: str = Field("", alias="PHOENIX_API_KEY")
    phoenix_collector_endpoint: str = Field("", alias="PHOENIX_COLLECTOR_ENDPOINT")
    phoenix_project_name: str = Field("noble-voice-agent", alias="PHOENIX_PROJECT_NAME")

    # ── STT: Soniox cloud ─────────────────────────────────────────────────────
    soniox_api_key: str = ""
    soniox_model: str = "stt-rt-v4"
    soniox_language_hints: str = "vi"
    soniox_language_hints_strict: bool = True
    soniox_enable_language_identification: bool = False
    soniox_enable_speaker_diarization: bool = True
    soniox_enable_endpoint_detection: bool = True
    soniox_max_endpoint_delay_ms: int = 250
    soniox_context_terms: str = ""
    soniox_context_domain: str = "Real Estate"
    soniox_context_organization: str = "NobleX"

    # ── STT: Qwen3-ASR ────────────────────────────────────────────────────────
    qwen3asr_mode: str = "dashscope"
    qwen3asr_api_key: str = ""
    qwen3asr_model: str = "qwen3-asr-flash-realtime-2026-02-10"
    qwen3asr_region: str = "intl"
    qwen3asr_language: str = ""
    qwen3asr_vllm_url: str = "http://localhost:8000"
    qwen3asr_chunk_size_sec: float = 2.0

    # ── STT: ElevenLabs Scribe v2 ─────────────────────────────────────────────
    elevenlabs_api_key: str = ""
    elevenlabs_stt_model: str = "scribe_v2_realtime"
    elevenlabs_stt_language_code: str = "vi"
    elevenlabs_stt_language_detection: bool = True
    elevenlabs_stt_vad_silence_sec: float = 1.5
    elevenlabs_stt_vad_threshold: float = 0.4
    elevenlabs_stt_context_text: str = "NobleX, tư vấn bất động sản"

    # ── TTS: ElevenLabs ───────────────────────────────────────────────────────
    elevenlabs_tts_model: str = "eleven_flash_v2_5"
    elevenlabs_tts_voice_id: str = "pNInz6obpgDQGcFmaJgB"
    elevenlabs_tts_language_code: str = "vi"
    elevenlabs_tts_stability: float = 0.5
    elevenlabs_tts_similarity_boost: float = 0.75
    elevenlabs_tts_speed: float = 1.0

    # ── STT audio format ──────────────────────────────────────────────────────
    stt_sample_rate: int = 16000
    stt_language: str = "vi"

    # ── TTS: VieNeu-TTS ───────────────────────────────────────────────────────
    # GGUF (local dir / HF gguf repo) OR safetensors HF repo (e.g. NobleX-AI/santa-tts).
    vieneu_backbone_repo: str = ""
    vieneu_hf_revision: str = "prod"  # HF branch/tag for the NobleX-AI backbone repo (codec stays default)
    vieneu_voice_id: str = ""
    # santa-tts (safetensors) path: backbone on GPU, ONNX int8 decoder on CPU.
    vieneu_backbone_device: str = "cuda"
    # Cast the safetensors backbone after load. transformers defaults to fp32 (leaves
    # tensor cores idle on Blackwell → ~2x slower); bfloat16 is the right default on cuda.
    # One of: bfloat16 | float16 | float32. Ignored on cpu / gguf backbones.
    vieneu_backbone_dtype: str = "bfloat16"
    # torch.compile the backbone (reduce-overhead) to cut per-step launch overhead of
    # the batch=1 autoregressive generate loop. Applied AFTER the dtype cast. Distinct
    # env name from the library's own VIENEU_COMPILE so the two don't collide.
    vieneu_compile_backbone: bool = False
    vieneu_codec_repo: str = "neuphonic/neucodec-onnx-decoder-int8"
    vieneu_codec_device: str = "cpu"
    # Empty → loader resolves reference/presets.json relative to the tts module dir.
    vieneu_presets_path: str = ""
    # None → use the library's use_chat_format default (False for santa-tts).
    # true/false overrides it (mitigation for the chat-format risk).
    vieneu_use_chat_format: bool | None = None
    tts_sample_rate: int = 24000
    # Token-level streaming of the transformers backbone (TTFA win; overlaps generation
    # with playback). ON by default — identical audio contract, flag exists for instant
    # rollback to the one-shot infer_stream path. NOBLE_TTS_STREAMING=false disables it.
    tts_streaming: bool = Field(True, validation_alias=AliasChoices("tts_streaming", "NOBLE_TTS_STREAMING"))
    # LiveKit output playout buffer (ms). The default 40 ms cannot bridge the
    # ~300 ms synth gap at a clause seam → audible stutter. A bigger cushion
    # rides over the common seam; it does NOT delay first audio (capture_frame
    # returns while there is room) and barge-in still drops it instantly via
    # AgentAudioIO.clear() in _handle_interrupt.
    tts_output_queue_ms: int = Field(
        800, validation_alias=AliasChoices("tts_output_queue_ms", "NOBLE_TTS_OUTPUT_QUEUE_MS")
    )

    # ── TTS: VieNeu via vLLM (backend "vieneu_vllm") ───────────────────────────
    # Client to a SEPARATE vLLM OpenAI server that streams <|speech_N|> tokens for
    # santa-tts; the speech tokens feed the SAME codec sink as the local path. The
    # client process does NOT load the GPU backbone (vLLM owns it) — only the ONNX
    # codec + tokenizer + presets. The server must be launched WITHOUT the CUDA
    # toolkit/nvcc on the host (see scripts/run_vllm_tts.sh):
    #   VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN vllm serve ... --enforce-eager
    vieneu_vllm_url: str = "http://localhost:8000"
    vieneu_vllm_model: str = "NobleX-AI/santa-tts"
    vieneu_vllm_temperature: float = 1.0
    vieneu_vllm_top_k: int = 50
    # Requested output budget for ONE clause. 1024 speech tokens ≈ 20s of audio
    # (one token ≈ a 20ms frame) — ample for a TTS clause. The real safety net is
    # the clamp below against max_model_len.
    vieneu_vllm_max_tokens: int = 1024
    # MUST match the server's `--max-model-len`. The source clamps the requested
    # max_tokens so `len(prompt_ids) + max_tokens <= max_model_len`; without this,
    # a normal prompt (~484 ids) + max_tokens overflows the context and vLLM returns
    # HTTP 400 ("maximum context length is N tokens") → the produce loop yields no
    # audio.
    vieneu_vllm_max_model_len: int = 2048
    # min_tokens is REQUIRED: without it the model emits EOS immediately → empty
    # audio. Mirrors the library's min_new_tokens=50.
    vieneu_vllm_min_tokens: int = 50

    # ── LLM: Anthropic ────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_base_url: str = ""

    # ── LLM Primary: Gemini ───────────────────────────────────────────────────
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 2048
    # Global thinking-mode toggle. Off by default — for a real-time voice agent
    # reasoning adds latency and leaks <think> tokens into TTS/history. When
    # False, StreamingClient sends each provider's disable kwarg AND strips any
    # leaked <think>...</think> span. Works across all providers.
    llm_enable_thinking: bool = Field(False, alias="NOBLE_LLM_ENABLE_THINKING")
    # Show generated thinking in the chat-UI display channel (debug only). TTS
    # never shows thinking regardless. History keeps thinking when generation is
    # on. Only meaningful when llm_enable_thinking=True.
    llm_show_thinking: bool = Field(False, alias="NOBLE_LLM_SHOW_THINKING")
    # Ép vòng LLM ĐẦU của mỗi turn phải gọi tool (tool_choice="required" —
    # chỉ forward cho provider OpenAI-compat, xem _TOOL_CHOICE_PROVIDERS).
    # Chặn model bỏ tool rồi "nhớ" dữ liệu (gemini-2.5-flash/qwen bịa tên dự án
    # ở câu mở màn). Lượt xã giao thoát qua tool no_lookup_needed — van xả đó
    # CHỈ được chào khi cờ này bật (facade tự thêm ở cả path db lẫn legacy;
    # cờ tắt thì nó không chiếm chỗ trong prompt). Yêu cầu thinking off khi
    # provider là dashscope (thinking bật → 400 required).
    llm_force_tool_first_round: bool = Field(False, alias="LLM_FORCE_TOOL_FIRST_ROUND")

    # ── LLM Fallback: OpenAI ─────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5.4-nano-2026-03-17"
    openai_reasoning_effort: str = "none"

    # ── LLM Primary: vLLM (self-hosted, OpenAI-compatible) ───────────────────
    # Empty model = provider OFF (opt-in), matching the "empty model = skip
    # provider" convention. When set, vLLM is built FIRST → primary tier.
    vllm_base_url: str = Field("http://localhost:8000/v1", alias="VLLM_BASE_URL")
    vllm_model: str = Field("", alias="VLLM_MODEL")
    vllm_api_key: str = Field("EMPTY", alias="VLLM_API_KEY")

    # ── LLM Provider 3: Qwen / DashScope ─────────────────────────────────────
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen3.5-flash"
    dashscope_enable_thinking: bool = False

    # ── LLM Provider 4: OpenRouter ────────────────────────────────────────────
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = ""

    # ── LLM Provider 5: Groq ─────────────────────────────────────────────────
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = ""

    # ── LLM Provider 6: Cerebras ─────────────────────────────────────────────
    cerebras_api_key: str = ""
    cerebras_base_url: str = "https://api.cerebras.ai/v1"
    cerebras_model: str = ""

    # ── LLM Retry & Fallback ──────────────────────────────────────────────────
    llm_max_retries: int = 2
    llm_retry_base_delay: float = 0.5
    llm_retry_max_delay: float = 5.0
    llm_timeout: int = 30

    # ── VAD: Silero ───────────────────────────────────────────────────────────
    vad_threshold: float = 0.7
    vad_chunk_ms: int = 32  # Silero v5+ fixed window: must be 32 (512 samples @ 16 kHz)

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_session_ttl_hours: int = 24

    # ── Media search (send_media, collection `<tenant>_media`) ────────────────
    media_search_top_k: int = 10
    # RRF scale, NOT cosine — and it shifts with the number of branches fused
    # (visual only joins when embed_service_url is set). 0 = no filter, use top_k.
    media_search_threshold: float = 0.0
    media_search_cache_ttl: float = 300.0  # in-process cache; not invalidated on ingest
    # Off = item chỉ mang `media_url`, client tự rơi về nó cho cả lưới và lightbox.
    media_send_thumb: bool = True

    # ── kb_search (NOBLE_RAG_BACKEND=kb_service, collection `<tenant>_documents`) ──
    kb_search_top_k: int = 5
    kb_search_min_score: float = 0.0  # applied AFTER fuse → RRF scale, not cosine
    # TẮT (2026-08-26): kb_search đính kèm tệp nguồn của MỌI hit có tệp, không xét
    # hit đó có góp chữ nào vào câu trả lời. Với tenant mà kho KB gần như toàn văn
    # bản chính sách (đo aina_prod: 107/111 chunk của một dự án thuộc 3 tệp CSBH),
    # gần như MỌI câu hỏi đều gửi kèm một thẻ tài liệu không ai xin — khách hỏi vị
    # trí thì nhận ảnh scan trang chính sách. Cờ chứ không xoá code: đường ĐƯA tệp
    # qua `items[]` vẫn đúng (LLM không phải chép URL dài), chỉ việc đính kèm VÔ
    # ĐIỀU KIỆN là sai. Bật lại khi có phép gác "khách có thật sự xin tài liệu".
    kb_search_attach_source_files: bool = False

    # ── Embedding (kb_search + send_media) ────────────────────────────────────
    # Dense backend switch; sparse runs in-process. Both must match what ingest
    # indexed with, else scores are noise / term ids miss.
    embed_backend: str = "gemini"  # gemini | service | hf
    embed_model: str = ""  # empty = backend default
    embed_dim: int = 1024  # must equal the collection's dense vector size
    embed_sparse_model: str = "Qdrant/bm25"  # fastembed, in-process
    embed_service_url: str = ""  # FULL endpoint (…/embed); only visual needs it now
    embed_timeout: float = 30.0

    # ── SP-E Postgres data plane (Odyssey, contract C4/C5) ─────────────────────
    # Fixed-store (N9): Odyssey writes the 3 agent tables to Postgres. Two DSNs:
    #   - runtime: shared app role conn (Option C pooling); RLS `agent_runtime` policy
    #     scopes each txn to a tenant via set_config('app.current_tenant', …, true).
    #   - admin: superuser conn used ONLY by `noble-tenant` provisioning to apply
    #     the shared schema + CREATE ROLE per tenant. Never used on the turn path.
    postgres_enabled: bool = Field(False, alias="POSTGRES_ENABLED")
    # Billing metering (SP-BILL). Mặc định TẮT: bảng billing.usage_events do
    # Portal ship, bật trước khi họ tạo bảng + cấp GRANT thì mọi phiên log
    # error liên tục. Bật sau khi Portal tick xong §11 của
    # docs/handoff/agent-postgres-billing-write-contract.md.
    billing_metering_enabled: bool = Field(False, alias="BILLING_METERING_ENABLED")
    postgres_dsn: str = Field("", alias="POSTGRES_DSN")
    postgres_admin_dsn: str = Field("", alias="POSTGRES_ADMIN_DSN")
    # DSN KHÔNG chứa user/password (vd postgresql://10.50.13.220:5433/odyssey).
    # Worker lắp role+password per-tenant (từ runtime-credentials) vào để dựng pool
    # riêng. Rỗng ⇒ pool_for_tenant luôn fallback shared POSTGRES_DSN.
    postgres_server_dsn: str = Field("", alias="POSTGRES_SERVER_DSN")
    # Shared runtime app role (Option C pooling): ALL tenants' connections use this
    # ONE role; RLS isolates by app.current_tenant GUC, not by role identity. Must
    # differ from every tenant_id (see pg_provisioning.assert_app_role_distinct).
    postgres_app_role: str = Field("odyssey_agent", alias="POSTGRES_APP_ROLE")

    # ── analyze_projects (SQL analytics tool, spec 2026-08-26) ────────────────
    analyze_sql_role: str = "agent_sql_ro"       # SET LOCAL ROLE khi chạy SQL của LLM
    analyze_sql_timeout_ms: int = 2000           # statement_timeout per-query
    analyze_sql_max_rows: int = 50               # cap dòng trả về + LIMIT auto-chèn
    analyze_vocab_ttl_sec: float = 600.0         # TTL cache vocab giá trị cột

    # ── Email ─────────────────────────────────────────────────────────────────
    email_enabled: bool = False
    email_smtp_host: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_user: str = ""
    email_app_password: str = ""
    email_default_from: str = "luna@noblex.vn"

    # ── Business constants ────────────────────────────────────────────────────
    noble_hotline: str = "1800 6112"
    noble_working_hours: str = "8:00-21:00"

    # ── Emotion Tags ──────────────────────────────────────────────────────────
    emotion_tags_enabled: bool = False

    # ── Health check ──────────────────────────────────────────────────────────
    health_check_interval: int = 30

    # ── Rate limit ────────────────────────────────────────────────────────────
    max_ws_connections: int = 100
    max_ws_per_ip: int = 5

    # ── Server ────────────────────────────────────────────────────────────────
    ws_host: str = "0.0.0.0"
    ws_port: int = 8766

    # ── WebRTC (ICE) ──────────────────────────────────────────────────────────
    rtc_stun_url: str = "stun:stun.l.google.com:19302"
    rtc_turn_url: str = ""
    rtc_turn_username: str = ""
    rtc_turn_credential: str = ""

    # ── Audio ─────────────────────────────────────────────────────────────────
    audio_chunk_ms: int = 20
    # Input gate to STT: "off" (passthrough) | "rms" (energy) | "vad" (Silero is_speech).
    stt_input_gate_mode: str = "off"
    audio_gate_preroll_chunks: int = 3  # K chunk lookback to recover clipped lead-in (all modes); 0 = off
    audio_gate_min_rms: float = 160.0  # (rms) per-frame energy threshold
    audio_gate_required_consecutive: int = 3  # (rms) consecutive frames to confirm speech
    audio_gate_barge_in_rms: float = 2400.0  # (rms) high-energy barge-in threshold
    stt_vad_gate_hangover_ms: int = 300  # (vad) keep gate open this long after speech ends
    stt_gate_keepalive_max_sec: float = 2.0  # (rms/vad) max silence fed to STT for endpoint; 0 = off
    audio_guard_repetition_detector_enabled: bool = True

    # ── Sentence / Clause Buffer ─────────────────────────────────────────────
    buffer_mode: str = "clause"
    min_sentence_length: int = 10
    min_clause_length: int = 50

    # ── Data provider (see docs/BA/spec_provider.md) ─────────────────────────
    noble_data_source: str = "pg_kb"  # "pg_kb" (Postgres KB provider)
    # discover_projects funnel: how many projects returned per page (top-K)
    discover_page_size: int = 5

    # ── RAG: Backend selection ────────────────────────────────────────────────
    noble_rag_backend: str = "flat_store"
    flat_store_skip_faq: bool = True

    # ── Qdrant — THE endpoint for the whole app ───────────────────────────────
    # Read by kb_search + send_media (per-tenant `<tenant>_documents`/`_media`) AND
    # by the legacy clone-from-root backends (`qdrant`/`hipporag`, collection
    # `qdrant_collection`). One deployment, so those legacy backends only work if
    # their clone collection exists wherever this points.
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_timeout: float = 10.0
    # Legacy clone-from-root (only `noble-rag-sync` / the `qdrant`|`hipporag`
    # backends). Empty → the reconcile skips, which is the normal state now.
    qdrant_collection_root: str = ""
    qdrant_collection: str = "noble_kb_hybrid"
    qdrant_dense_vector_name: str = "dense"
    qdrant_sparse_vector_name: str = "bm25"
    # On-disk BM25 fallback (built by sparse_reconcile from the same root snapshot).
    qdrant_fallback_dir: str = str(
        Path(__file__).resolve().parent.parent.parent / "data" / "flat_store" / "bm25_qdrant_fallback"
    )
    qdrant_reconcile_timeout_sec: int = 120
    rag_top_k: int = 3
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024
    tei_url: str = "http://localhost:8080"

    # ── RAG: HippoRAG 2 graph backend (opt-in via NOBLE_RAG_BACKEND=hipporag) ──
    # KG built OFFLINE from the Qdrant clone via LLM OpenIE (noble-rag-sync);
    # query-time runs numpy Personalized PageRank only (no LLM). See
    # agent/rag/hipporag/ and docs/hipporag2-explainer.html.
    hipporag_graph_path: str = str(Path(__file__).resolve().parent.parent.parent / "data" / "hipporag" / "graph.json")
    hipporag_ppr_alpha: float = 0.5  # PPR damping (mass that keeps flowing vs restarts to seeds)
    hipporag_ppr_iters: int = 30  # power-iteration steps (tiny graph → converges fast)
    hipporag_seed_k: int = 8  # how many hybrid hits seed the PPR restart distribution
    hipporag_top_k: int = 5  # passages returned after PPR + RRF fuse
    hipporag_openie_max_tokens: int = 1024  # build-time OpenIE completion cap
    # Primary-provider pin for the build-time OpenIE extraction, INDEPENDENT of the
    # main agent. Must equal one of the configured <P>_MODEL values (same scheme as
    # NOBLE_AGENT_MODEL). Empty → fall back to the NOBLE_AGENT_MODEL pin.
    hipporag_openie_model: str = ""
    # Triple embedding store for the sparse triple-seed. "local" (default) = the
    # numpy sidecar <graph>.triple_emb.npz; "qdrant" = a dedicated Qdrant collection
    # (built alongside the npz by noble-rag-sync). Query cascade when "qdrant":
    # Qdrant → local npz → sparse-seed no-op. Toggle needs no rebuild (both built).
    hipporag_triple_store: str = "local"  # env HIPPORAG_TRIPLE_STORE
    # env QDRANT_TRIPLE_COLLECTION
    qdrant_triple_collection: str = "noble_kb_hipporag_triples"
    # Sparse triple-seed (HippoRAG 2 dual seeding): besides the dense passage
    # seeds, cosine-match the query against embedded TRIPLES ("subject relation
    # object") and seed PPR at both entity nodes of the top triples (NO LLM). Runs
    # in PARALLEL with the hybrid search. Triple embeddings are built by
    # noble-rag-sync (needs `--renew-graph` once for older graphs); missing → no-op.
    hipporag_sparse_seed_enabled: bool = False
    hipporag_sparse_seed_top_m: int = 5  # how many TRIPLES to match (each seeds ≤2 entities)
    hipporag_sparse_seed_weight: float = 0.3  # PPR restart mass share for sparse seeds (0..1)
    # Minimum score a top-K seed must clear to be USED (applied AFTER top-K, BEFORE
    # the dense/sparse mix) — drops low-similarity seeds so they don't inject noise.
    # passage = the qdrant hybrid score; phrase = the triple cosine. 0.0 = keep all.
    hipporag_passage_seed_threshold: float = 0.0
    hipporag_phrase_seed_threshold: float = 0.0

    # ── HippoRAG: artefact do Portal ghi (backend `hipporag_kb`) ──────────────
    # Cấu hình TĨNH, không phải credential per-tenant: registry `tenant_credentials.py`
    # chỉ mang role/password Postgres. Cách ly nằm ở `current_tenant()` trong đường dẫn
    # khoá — cùng mô hình `kb_service_adapter` dùng cho tên collection. Rỗng ⇒ degrade.
    hipporag_artefact_endpoint: str = Field("", alias="HIPPORAG_ARTEFACT_ENDPOINT")
    hipporag_artefact_bucket: str = Field("", alias="HIPPORAG_ARTEFACT_BUCKET")
    hipporag_artefact_access_key: str = Field("", alias="HIPPORAG_ARTEFACT_ACCESS_KEY")
    hipporag_artefact_secret_key: str = Field("", alias="HIPPORAG_ARTEFACT_SECRET_KEY")
    hipporag_cache_dir: str = Field("/var/lib/noble/hipporag", alias="HIPPORAG_CACHE_DIR")

    # ── User snapshot memory (per-caller cumulative narrative) ───────────────
    # Always on when a real phone is present. Short-term = snapshot + last K turns
    # of the prior session, injected at bootstrap. See
    # docs/superpowers/specs/2026-07-13-user-snapshot-memory-redesign-design.md.
    user_memory_short_term_turns: int = 6
    user_memory_since_days: int = 30
    snapshot_lock_wait_sec: float = 10.0  # bootstrap waits at most this for an in-flight merge
    snapshot_lock_ttl_sec: int = 60  # merge lock TTL (self-heal if the merge crashes)

    # ── VoiceAgentRAG: Semantic Cache (legacy, paper Table 6) ────────────────
    cache_enabled: bool = True
    cache_similarity_threshold: float = 0.35
    cache_max_size: int = 2000
    cache_ttl_seconds: float = 300.0
    cache_dedup_threshold: float = 0.95

    # ── VoiceAgentRAG: Slow Thinker ───────────────────────────────────────────
    slow_thinker_prediction_strategy: str = "llm"
    slow_thinker_max_predictions: int = 5
    slow_thinker_prefetch_top_k: int = 10
    slow_thinker_rate_limit: float = 0.5
    slow_thinker_llm_model: str = "gpt-4o-mini"
    slow_thinker_llm_temperature: float = 0.3
    slow_thinker_llm_max_tokens: int = 200

    # ── VoiceAgentRAG: Fast Talker ────────────────────────────────────────────
    fast_talker_max_context_chunks: int = 10
    fast_talker_fallback_to_retrieval: bool = True

    # ── VoiceAgentRAG: Conversation Stream ───────────────────────────────────
    conversation_window_size: int = 10

    # ── VoiceAgentRAG: Document chunking ─────────────────────────────────────
    chunk_size: int = 512
    chunk_overlap: int = 50

    # ── VAD: Interruption debounce ────────────────────────────────────────────
    vad_interrupt_confirm_chunks: int = 3
    interrupt_mode: str = "immediate"
    # Min RMS (int16 scale 0–32768) the triggering audio chunk must reach to
    # honor a VAD interrupt *while the agent is audibly playing* — rejects
    # low-level AEC echo residual that would otherwise self-interrupt the agent
    # (notably the greeting). Real barge-in speech is well above this; quiet
    # post-AEC echo is below. Lower it if soft-spoken callers can't barge in;
    # raise it if echo still cuts the agent. No effect outside playback. 0 = off.
    barge_in_rms_threshold: float = 1500.0

    # ── Idle prompts ──────────────────────────────────────────────────────────
    idle_first_delay: float = 25.0
    idle_prompt_delay: float = 10.0
    idle_goodbye_delay: float = 4.0

    # ── Tool-call bridge phrase ───────────────────────────────────────────────
    tool_ack_enabled: bool = True
    tool_ack_text: str = "Để em kiểm tra ngay, anh chị chờ em một chút nhé."
    tool_ack_fast_tools: str = "update_customer"
    tool_ack_assets_dir: str = "assets/voice/acks"
    # Frequency limiters — without these the canned ack fires on *every* turn
    # that hits a slow tool (≈ every RAG turn), which callers hear as the agent
    # saying "để em kiểm tra" before every single answer. Probability thins it
    # out per-eligible-turn; cooldown blocks back-to-back acks within a session.
    tool_ack_probability: float = 0.4
    tool_ack_cooldown_s: float = 30.0

    # ── Addressee gate (chống nói leo) ───────────────────────────────────────
    # Phân biệt "khách ngắt lời agent" vs "khách nói chuyện với người bên cạnh".
    # off = behavior cũ (VAD interrupt ngay). Spec:
    # docs/superpowers/specs/2026-08-12-addressee-gate-design.md
    addressee_gate_mode: Literal["off", "heuristic", "llm", "hybrid"] = "off"
    addressee_min_speech_ms: int = 400  # speech liên tục tối thiểu mới soft-pause
    addressee_llm_model: str = ""  # pin model verdict; rỗng → chain mặc định
    addressee_llm_timeout_ms: int = 600  # quá hạn → DIRECTED (fail-open)
    addressee_gate_when_idle: bool = False  # áp gate cả khi agent không nói
    addressee_resume_ack_text: str = "Em nói tiếp nhé."
    # Hạn tối đa giữ soft-pause chờ STT final (amendment 2026-08-12 đêm — verdict
    # giờ chờ final, không classify trên partial nữa). PHẢI < pacer's
    # _PAUSE_WATCHDOG_S (5s, voice/voice_agent.py) — nếu không pacer tự resume
    # trước khi deadline này bắn.
    addressee_max_pause_ms: int = 4000

    # ── Smart Turn v3 ─────────────────────────────────────────────────────────
    smart_turn_enabled: bool = False
    smart_turn_model_path: str = ""
    smart_turn_threshold: float = 0.5
    smart_turn_max_hold_sec: float = 2.0

    # ── Gender Detection Model ────────────────────────────────────────────────
    gender_model_dir: str = ""
    gender_remote_url: str = ""
    gender_remote_timeout: float = 3.0

    # ── Remote embedding service ──────────────────────────────────────────────
    # When set, the query/passage embedder POSTs to {url}/embed instead of loading
    # e5-large locally (microservice deploy). Body: {"texts":[...],"is_query":bool};
    # response: {"embeddings":[[...]]}. Token (if set) → `Authorization: Bearer`.
    embed_remote_url: str = ""
    embed_remote_timeout: float = 10.0
    embed_remote_token: str = ""

    # ── Telephony: Asterisk/FreePBX ───────────────────────────────────────────
    telephony_enabled: bool = False
    asterisk_host: str = "voip.noble.vn"
    asterisk_ari_port: int = 8088
    asterisk_ari_scheme: str = "http"
    asterisk_ari_username: str = "noble-agent"
    asterisk_ari_password: str = ""
    asterisk_ari_app: str = "noble-voice-agent"
    audiosocket_host: str = "0.0.0.0"
    audiosocket_port: int = 8090
    audiosocket_format: str = "slin"
    telephony_sample_rate: int = 8000
    telephony_record_calls: bool = False
    telephony_recordings_dir: str = "data/recordings"

    # ── Telephony: Outbound call originate ────────────────────────────────────
    asterisk_sip_trunk: str = "NobleX-88801441"
    asterisk_outbound_callerid: str = "18006112"
    asterisk_outbound_context: str = "noble-agent-outbound"
    asterisk_outbound_timeout: int = 30

    # ── Telephony admin HTTP server ───────────────────────────────────────────
    telephony_admin_enabled: bool = True
    telephony_admin_host: str = "127.0.0.1"
    telephony_admin_port: int = 8767

    # ── SMS ───────────────────────────────────────────────────────────────────
    sms_enabled: bool = False
    sms_backend: str = "dry_run"
    sms_from: str = "18006112"
    sms_esms_api_key: str = ""
    sms_esms_secret_key: str = ""
    sms_esms_brandname: str = ""
    sms_esms_type: str = "1"
    sms_esms_unicode: str = "0"
    sms_speedsms_token: str = ""
    sms_speedsms_sender: str = ""
    sms_speedsms_type: int = 2

    # ── Prompt variant selection ──────────────────────────────────────────────
    noble_prompt_mode: str = ""

    # ── System Prompt ─────────────────────────────────────────────────────────
    # Unified builds its prompt from agent/definitions/ (SOUL+RULES+PROMPT_TEMPLATE)
    # via build_system_prompt; this field is kept only for legacy code that may
    # still read settings.system_prompt.
    system_prompt: str = ""

    # ── Transport layer ───────────────────────────────────────────────────────
    transport_backend: str = "aiortc"
    livekit_url: str = "ws://localhost:7880"
    livekit_public_url: str = ""
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "devsecret_change_me_for_prod_1234567890abcdef"
    # Single SHARED LiveKit agent-dispatch name. One worker pool registers under
    # this name and serves EVERY tenant; the per-job tenant is resolved from the
    # caller's participant metadata (gateway-injected), NOT from the dispatch name.
    # Used identically by worker registration, app_session mint, and the gateway.
    livekit_agent_name: str = "noble-hotline-agent"
    worker_max_concurrent_sessions: int = 50
    livekit_worker_port: int = 8081
    # When true, GET /livekit/token is publicly reachable (dev browser tester).
    # Prod keeps it false — the app path mints LiveKit tokens via
    # POST /api/v1/app/session (channel="voice") instead.
    livekit_token_public: bool = False

    # ── NobleX App integration (bubble chat/voice) ─────────────────────────────
    # Server-to-server key the NobleX backend uses to provision agent sessions.
    noble_app_api_key: str = ""
    # When true, WS /chat requires a valid connect-token (prod). False keeps the
    # local /chat tester (static/chat.html) working without provisioning.
    chat_ws_require_token: bool = False
    # TTL (seconds) of the short-lived connect-token minted at provisioning.
    app_connect_token_ttl_seconds: int = 120
    # Public wss base (e.g. wss://hotline-agent.noble.vn). Empty → ws_url is a
    # bare path and the backend composes the host.
    app_ws_public_base: str = ""

    # ── Validators (from legacy Settings) ────────────────────────────────────

    @model_validator(mode="after")
    def validate_redis_session_ttl_covers_idle(self) -> UnifiedSettings:
        """CONCERNS.md 7.3 (Phase 4.3): ensure session TTLs outlive the
        idle-goodbye window so state isn't evicted mid-call.

        Validates BOTH:
          - `redis_session_ttl_hours` (legacy session_store path).
          - `session_ttl_seconds` (StateRepo.save_all in unified package).
        """
        required_hours = (self.idle_goodbye_delay / 3600) + 1
        if self.redis_session_ttl_hours < required_hours:
            raise ValueError(
                f"redis_session_ttl_hours ({self.redis_session_ttl_hours}) must be "
                f">= (idle_goodbye_delay / 3600) + 1 = {required_hours:.2f}"
            )
        required_seconds = self.idle_goodbye_delay + 60
        if self.session_ttl_seconds < required_seconds:
            raise ValueError(
                f"session_ttl_seconds ({self.session_ttl_seconds}) must be "
                f">= idle_goodbye_delay + 60s = {required_seconds:.0f}"
            )
        return self

    @model_validator(mode="after")
    def apply_emotion_tags_model_override(self) -> UnifiedSettings:
        """Đảm bảo model hỗ trợ emotion tag lẫn language_code='vi' qua WebSocket."""
        if self.emotion_tags_enabled and self.elevenlabs_tts_model == "eleven_multilingual_v2":
            self.elevenlabs_tts_model = "eleven_flash_v2_5"
        return self

    @model_validator(mode="after")
    def _validate_probe_schedule(self) -> UnifiedSettings:
        """Fail-loud khi khởi động nếu cấu hình SPV probe không hợp lệ."""
        if self.speaker_mode != "off":
            parse_probe_schedule(self.spv_probe_marks_sec, self.spv_probe_bonus, self.speaker_match_threshold)
        return self


_settings: UnifiedSettings | None = None


def get_settings() -> UnifiedSettings:
    global _settings
    if _settings is None:
        _settings = UnifiedSettings()
    return _settings


def reset_settings_for_tests() -> None:
    """Test-only helper: clear cached settings."""
    global _settings
    _settings = None


def resolve_speaker_mode() -> str:
    """Effective speaker policy: SPEAKER_MODE, with legacy SPEAKER_VERIFICATION_ENABLED=true → 'single'."""
    s = get_settings()
    mode = (s.speaker_mode or "off").strip().lower()
    if mode not in ("off", "single", "multi"):
        mode = "off"
    if mode == "off" and s.speaker_verification_enabled:
        mode = "single"
    return mode


def primary_for(settings: UnifiedSettings, model_name: str) -> str | None:
    """Resolve a `NOBLE_*_MODEL` value to the provider that serves it.

    The value must equal one of the configured per-provider model names
    (`ANTHROPIC_MODEL` / `OPENAI_MODEL` / `GEMINI_MODEL`); that match
    identifies the primary provider. Empty input or no match → `None`,
    meaning "no pin — use the default provider chain order for this path".

    The caller (`StreamingClient`) reorders the chain so the primary runs
    first; remaining providers still serve as fallback (each with their
    own `<P>_MODEL`).
    """
    if not model_name:
        return None
    base = provider_model_map(settings)
    for name, configured in base.items():
        if configured and configured == model_name:
            return name
    import logging  # local: avoid a module-level logger in pure config.

    logging.getLogger("noble_agent.config").warning(
        "primary_for: model %r doesn't match any of %s — falling back to default chain order",
        model_name,
        {n: m for n, m in base.items() if m},
    )
    return None


def provider_model_map(settings: UnifiedSettings) -> dict[str, str]:
    """Per-provider model mapping for non-main-agent LLM paths (summary,
    semcache predictor + sandbox). The StreamingClient walks the fallback
    chain and asks each provider with ITS configured model — empty entries
    mean "skip this provider for this path". vLLM / Anthropic / OpenAI /
    DashScope / Gemini are the providers `build_llm_providers` may construct,
    so the map populates exactly those keys (vLLM empty unless `VLLM_MODEL`
    is set; DashScope keyed off `DASHSCOPE_MODEL`).

    Kept here (not in agent.facade) to avoid the facade ↔ orchestrator
    import cycle.
    """
    return {
        "vllm": settings.vllm_model,
        "anthropic": settings.anthropic_model,
        "openai": settings.openai_model,
        "dashscope": settings.dashscope_model,
        "gemini": settings.gemini_model,
    }


def __getattr__(name: str):
    """Lazy module-level `settings` — preserves
    ``from noble_agent.config import settings`` without forcing
    settings construction at import time (which broke env overrides applied
    after the first import).
    """
    if name == "settings":
        return get_settings()
    raise AttributeError(f"module 'noble_agent.config' has no attribute {name!r}")
