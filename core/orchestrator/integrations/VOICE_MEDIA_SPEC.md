# Voice & Media Processing Specification

**Status:** Draft
**Version:** 0.1.0
**Last Updated:** 2026-01-30
**Author:** AGENT-33 Implementer

## Purpose

Define the canonical architecture for voice interaction and media processing within AGENT-33 orchestrated workflows. This specification enforces a privacy-first design: all media processing defaults to local/on-device execution, and no audio, image, or video data is transmitted to external providers without explicit, per-invocation user consent.

---

## 1. Speech-to-Text (STT)

### 1.1 Provider Tiers

| Tier | Provider | Latency | Privacy | Notes |
|------|----------|---------|---------|-------|
| **Tier 3 (PREFERRED)** | whisper.cpp | Medium | Excellent | Fully local, no network calls |
| Tier 2 | Deepgram | Low | Moderate | Streaming-optimized, cloud-hosted |
| Tier 2 | OpenAI Whisper API | Medium | Moderate | High accuracy, cloud-hosted |
| Tier 1 | Google Speech-to-Text | Low | Low | Enterprise SLA, data retention concerns |
| Tier 1 | Azure Speech Services | Low | Low | Enterprise SLA, data retention concerns |
| Tier 1 | AWS Transcribe | Low | Low | Enterprise SLA, data retention concerns |

### 1.2 Local-First Processing Requirement

All STT operations MUST attempt local processing before falling back to cloud providers. The fallback chain is:

1. Local whisper.cpp with the configured model (default: `base.en`)
2. If local fails or quality threshold not met, prompt user for cloud consent
3. Cloud provider selected per configuration

Local model selection guidance:

| Model | Size | Use Case |
|-------|------|----------|
| `tiny.en` | 39 MB | Low-resource devices, quick drafts |
| `base.en` | 74 MB | Default, good balance |
| `small.en` | 244 MB | Higher accuracy when resources allow |
| `medium.en` | 769 MB | Near-cloud accuracy, requires GPU |
| `large-v3` | 1.5 GB | Maximum accuracy, requires dedicated GPU |

### 1.3 Data Handling

- Audio buffers MUST be held in memory only; no disk persistence unless explicitly cached.
- Audio MUST NEVER be sent to external providers without per-session or per-invocation consent.
- When cloud STT is used, audio is transmitted over TLS 1.3 and the provider's data retention policy must be documented in the consent prompt.
- After transcription completes, source audio references are zeroed in memory.

### 1.4 Streaming vs Batch Modes

**Streaming mode** is used for real-time voice interaction:
- WebSocket-based audio chunks (16kHz, 16-bit PCM, mono)
- Partial results returned with `is_final` flag
- Voice activity detection (VAD) handled locally before streaming

**Batch mode** is used for file-based transcription:
- Accepts WAV, FLAC, OGG, MP3, WEBM
- Maximum file size: 100 MB
- Timeout: 300 seconds per file

---

## 2. Text-to-Speech (TTS)

### 2.1 Provider Tiers

| Tier | Provider | Quality | Privacy | Notes |
|------|----------|---------|---------|-------|
| **Tier 3 (PREFERRED)** | piper | Good | Excellent | Fully local, ONNX-based |
| **Tier 3 (PREFERRED)** | edge-tts | Good | **SEE SECURITY NOTE** | Local client, remote synthesis |
| Tier 2 | ElevenLabs | Excellent | Low | Voice cloning risk, cloud-only |
| Tier 2 | OpenAI TTS | Excellent | Moderate | Cloud-hosted |
| Tier 1 | Azure Neural TTS | Excellent | Low | Enterprise SLA |
| Tier 1 | AWS Polly | Good | Low | Enterprise SLA |

### 2.2 Security Note: edge-tts

**RISK FLAG:** `edge-tts` is a Python package that uses a reverse-engineered Microsoft Edge Read Aloud endpoint. This carries the following risks:

- The endpoint is undocumented and may break without notice.
- Text content IS sent to Microsoft servers (not truly local).
- No SLA, no data processing agreement, no guarantee of data handling.
- Microsoft may block or rate-limit usage at any time.

**Recommendation:** Use `piper` for true local TTS. Use `edge-tts` only in development or when piper voice quality is insufficient and the user accepts the risk.

### 2.3 Local TTS Preference

The default TTS provider MUST be `piper` with a bundled voice model. Voice model downloads are performed once and cached locally. No text content leaves the device when using piper.

### 2.4 Audio Caching with Encryption

Synthesized audio may be cached to avoid redundant synthesis of repeated phrases (e.g., status notifications).

- Cache location: `{data_dir}/cache/tts/`
- Cache entries encrypted with AES-256-GCM
- Encryption key derived from the agent's session key
- Cache entries keyed by `HMAC-SHA256(text + voice_id + settings)`
- Maximum cache size: 500 MB (LRU eviction)
- Cache TTL: 24 hours

---

## 3. Image/Video Understanding

### 3.1 Provider Tiers

| Tier | Provider | Capabilities | Privacy |
|------|----------|-------------|---------|
| **Model Default** | Anthropic Claude (vision) | Image analysis, OCR, reasoning | Per Anthropic DPA |
| Model Default | OpenAI GPT-4 (vision) | Image analysis, OCR | Per OpenAI DPA |
| Model Default | Google Gemini (vision) | Image, video analysis | Per Google DPA |
| **Local** | LLaVA | Image analysis | Excellent |
| **Local** | MiniCPM-V | Image analysis, lightweight | Excellent |

### 3.2 Local Alternatives

For privacy-sensitive deployments, local vision models can be used via:
- `llama.cpp` with multimodal model support
- Dedicated ONNX runtime for lightweight models
- Quality trade-off documented per model

### 3.3 Image Sanitization Before Processing

All images MUST be sanitized before being sent to any provider (including local models):

1. **EXIF stripping:** Remove all EXIF, IPTC, XMP metadata.
2. **GPS removal:** Explicitly strip GPS coordinates even if general EXIF strip fails.
3. **Metadata removal:** Remove embedded thumbnails, comments, ICC profiles (optional, configurable).
4. **Format normalization:** Convert to PNG or JPEG before processing to reduce attack surface.
5. **Dimension validation:** Reject images exceeding 8192x8192 pixels.
6. **File size validation:** Reject images exceeding 20 MB.

### 3.4 Consent Requirement

Images MUST NOT be sent to cloud vision providers without explicit consent. The consent prompt must include:
- Which provider will receive the image
- Whether the provider retains submitted images
- A preview or description of the image being sent

---

## 4. Media Pipeline Security

### 4.1 Encryption at Rest

All media files stored on disk (cached audio, queued images, temporary video frames) MUST be encrypted with AES-256-GCM. Keys are managed through the credential management system (see `CREDENTIAL_MANAGEMENT_SPEC.md`).

### 4.2 Temporary File Cleanup

- All temporary media files are created in a dedicated temp directory: `{data_dir}/tmp/media/`
- Files are registered in a cleanup manifest on creation.
- Secure deletion: overwrite with random bytes before unlinking (where OS supports).
- Cleanup runs on: operation completion, agent shutdown, and periodic sweep (every 5 minutes).
- Maximum temp directory age: 1 hour. Files older than this are force-deleted.

### 4.3 No Media Forwarding

Media received from a user or agent MUST NOT be forwarded to third parties beyond the configured processing provider. Specifically:
- No analytics or telemetry containing media content
- No media in log files
- No media in error reports
- No media shared between unrelated agent workflows

### 4.4 EXIF/Metadata Stripping

Applied universally on all media ingestion (not just images sent to vision providers). This includes:
- Images: EXIF, IPTC, XMP, GPS, embedded thumbnails
- Audio: ID3 tags, Vorbis comments, metadata atoms
- Video: Container-level metadata, embedded subtitles with PII

### 4.5 Content Type Validation

Prevent polyglot attacks (files that are valid as multiple formats):
- Validate magic bytes match declared content type
- Reject files where multiple format parsers succeed (polyglot detection)
- Enforce strict MIME type checking
- Do not rely on file extensions for type determination

### 4.6 Size Limits

| Media Type | Maximum Size | Maximum Duration/Dimensions |
|-----------|-------------|---------------------------|
| Audio (STT) | 100 MB | 60 minutes |
| Audio (cached TTS) | 50 MB | 30 minutes |
| Image | 20 MB | 8192x8192 px |
| Video | 500 MB | 10 minutes |

---

## 5. Configuration Schema

```yaml
voice_media:
  stt:
    provider: local | google | azure | deepgram | openai
    prefer_local: true
    local_model: base.en          # whisper.cpp model
    consent_required: true
    streaming:
      enabled: true
      vad_threshold: 0.5
      sample_rate: 16000
    batch:
      max_file_size_mb: 100
      timeout_seconds: 300

  tts:
    provider: local | azure | elevenlabs | openai
    prefer_local: true
    local_engine: piper            # piper | edge-tts
    voice_id: en_US-lessac-medium  # piper voice
    cache_encrypted: true
    cache_max_mb: 500
    cache_ttl_hours: 24

  vision:
    provider: model_default | google | local
    local_model: llava             # llava | minicpm-v
    strip_metadata: true
    consent_required: true
    max_image_size_mb: 20
    max_dimension: 8192

  security:
    encrypt_at_rest: true
    secure_delete: true
    temp_max_age_minutes: 60
    polyglot_detection: true
    metadata_strip_all: true
```

---

## 6. Integration with AGENT-33 Orchestrator

Voice and media capabilities are exposed as agent tools, not standalone services. The orchestrator routes media requests through the configured pipeline:

1. **Ingestion:** Media received, validated, sanitized.
2. **Consent check:** If cloud processing required, consent verified.
3. **Processing:** Routed to appropriate provider (local preferred).
4. **Result delivery:** Text/analysis returned to requesting agent.
5. **Cleanup:** Source media securely deleted if temporary.

Agents declare media capabilities in their manifest:

```yaml
agent:
  name: voice-assistant
  capabilities:
    - stt
    - tts
  media_permissions:
    - audio_input
    - audio_output
```

Only agents with declared capabilities receive media-related tool access.
