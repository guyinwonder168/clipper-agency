# Clipper Agency — Product Requirements Document

**Version:** 2.9
**Date:** 2026-06-06
**Status:** Tier 4 Design Accepted — Timeline-Aware Agent Orchestration (pending implementation)
**Related:** `docs/SRS.md`, `docs/technical_design.md`, `docs/requirements_traceability.md`

---

## 1. Executive Summary

Clipper Agency automates short-form video content production for social media. The system takes a trending topic, researches it, writes a script, generates voiceover, assembles visuals, composes a finished video, and delivers a ready-to-upload package.

**MVP (Stage 1):** Single client, single TikTok account, Indonesian artist infotainment niche. Manual topic input. yt-dlp media download with Pexels fallback. Local machine + Docker-ready.

---

## 2. Target Users

| User | Role | Need |
|------|------|------|
| **Agency Operator (Admin)** | Runs the system | Manage clients, accounts, agents, secrets, budget, revenue |
| **Creative Lead** | Content strategy | Approve jobs, emergency override for soft-safety warnings, manage risk |
| **Creative User** | Daily operations | Create jobs, select topics/niches/templates |
| **Reviewer** | Quality control | Approve/reject output packages before upload |

---

## 3. MVP Scope

| Dimension | Decision |
|-----------|----------|
| **Platform** | TikTok only |
| **Scale** | 1 client, 1 account |
| **Niche** | Indonesian artist trending updates (infotainment) |
| **Tone** | Casual, TikTok-style Bahasa Indonesia |
| **Video** | Target 45-55 second vertical (9:16, 1080x1920) w/ configurable hard limit ≤60s |
| **Upload** | Manual (no TikTok API posting) |
| **Media** | yt-dlp download (Layer 1 primary); Pexels fallback when no source URL or download fails; local user asset path accepted |
| **Research** | ScrapeCreators (TikTok video/music) + Firecrawl (context/news) |
| **Voice** | One configured voice ID with provider fallback: ElevenLabs → Google AI Studio Gemini TTS → Fish Audio → fail clearly |
| **Auth** | Basic auth + 2 groups (privileged, creative/ops) |
| **Retry** | Human-triggered only. No auto-retry loops. |
| **Runtime** | Local machine, Docker-ready for VPS |

Niche, language, tone, and all content rules are **config-swappable** without code changes.

### Platform Support (Publishing Destinations)

| Platform | MVP | Future |
|----------|-----|--------|
| TikTok | ✅ | ✅ |
| Instagram Reels | ❌ | Stage 3+ |
| YouTube Shorts | ❌ | Stage 3+ |

Source media may come from any yt-dlp-supported site during MVP regardless of publishing platform.

---

## 4. Output Package

Every successful job produces a final customer-ready package under `OUTPUT_DIR/job_{id}`:

| File | Content |
|------|---------|
| `video.mp4` | Finished video, 9:16, 1080x1920 |
| `caption.txt` | Caption (max 150 chars, max 5 hashtags) |
| `thumbnail.png` | Template-based 1080x1920 thumbnail |
| `metadata.json` | Job metadata, agent states, cost estimate, asset provenance |

Intermediate execution material is not part of the final upload package. Each job also persists an auditable workspace under `ASSETS_CACHE/job_{id}` containing agent `input.json`/`output.json`, gate results, research raw/normalized artifacts, TTS provider attempts, FFmpeg diagnostics, and `manifest.json`. This workspace is used for audit, debug observability, and future retry/resume safety.

---

## 5. Core Product Requirements

| ID | Requirement | Priority | Stage |
|----|-------------|----------|-------|
| PR-01 | Automated video generation from trending topics via gated agent pipeline | P0 | MVP |
| PR-02 | Agent pipeline: Safety → Researcher (content_direction) → Orchestrator Format Validator → Scriptwriter (word/time budget) → Script Duration Gate → Voice → Timeline Reconciler → Visual (timeline-aware) → Compose (timeline-obedient) → Review. Each step gated with pass/soft-fail/hard-fail rules. See `docs/technical_design.md` §3 for full gate definitions. | P0 | MVP |
| PR-03 | Web dashboard for job management and agent configuration | P0 | MVP |
| PR-04 | CLI for direct pipeline execution | P0 | MVP |
| PR-05 | Ready-to-upload output package (video + caption + thumbnail + metadata) | P0 | MVP |
| PR-06 | Configurable niche profiles (language, tone, audience, rules) swappable without code changes | P0 | MVP |
| PR-07 | Selectable video templates (manual or agent-auto selection) | P1 | MVP |
| PR-08 | Configurable agent autonomy levels | P1 | MVP |
| PR-09 | Creative Director Agent — proposes new angles/templates when variation exhausted | P1 | Stage 2 |
| PR-10 | Safety/Compliance Agent — pre-checks content before expensive generation | P0 | MVP |
| PR-11 | Lightweight preflight cost/credit estimate before job start | P0 | MVP |
| PR-12 | Dashboard roles (MVP: basic auth + 2 groups; full role model Stage 2+) | P1 | MVP / Stage 2 |
| PR-13 | Budget governance with visible budget envelope + emergency override | P1 | Stage 2 |
| PR-14 | Cost tracking: estimated vs actual cost per job | P1 | Stage 2 |
| PR-15 | Cost-optimized model presets (Budget East, Agentic East, Premium East, Premium West) | P1 | MVP |
| PR-16 | Restricted financial analytics (revenue/gross profit visible to authorized roles only) | P1 | Stage 2 |
| PR-17 | Multi-account management per client | P2 | Stage 3 |
| PR-18 | Scheduled automated content generation | P2 | Stage 3 |
| PR-19 | TikTok Direct Post API integration | P2 | Stage 3 |
| PR-20 | Multi-platform publishing (Instagram Reels, YouTube Shorts) | P2 | Stage 3+ |
| PR-21 | Post-publishing analytics (Stage 1.5 basic snapshots → Stage 2 expanded → Stage 3 learning loop) | P2 | Stage 1.5+ |
| PR-22 | Per-agent model configuration via environment variables | P0 | MVP |
| PR-23 | Structured logging for all external API calls, agent executions, and pipeline state transitions | P0 | MVP |
| PR-24 | `test-agent` CLI subcommand for independent agent testing/debugging | P1 | MVP |
| PR-25 | Configurable TTS provider fallback: ElevenLabs first, Google AI Studio Gemini TTS second, Fish Audio third, then fail clearly with provider attempts recorded | P0 | MVP |
| PR-26 | Treatment system: YAML-defined visual treatments (Ken Burns zoom/pan, cinematic crop, B-roll, slow-motion, lower-third slide, text card reveal, hook caption, fade-to-black) with transitions (crossfade, hard cut, wipe left, dissolve, circle open) and FPS/pacing rules, applied automatically by Visual Director and Composer without code changes | P0 | MVP |
| PR-27 | Scene normalizer: unify mixed-asset framerates to 30fps target, normalize SAR to 1:1, apply Ken Burns zoompan for static images, validate clip duration bounds (1-5s), enforce consistent encoding parameters across all scenes before composition | P0 | MVP |
| PR-28 | Per-scene audio sequencing with silence padding, timed subtitle overlays from script text via drawtext, xfade/concat mixed transition chain with duration clamping and safety margins, and TikTok-ready production output flags (yuv420p, faststart, H.264/AAC) | P0 | MVP |
| PR-29 | Timeline-aware content planning and cross-agent reconciliation: Researcher recommends content direction (format + story selection), Orchestrator validates and derives word/time budgets, Scriptwriter obeys budgets with scene roles and estimated durations, Voice Producer measures actual audio durations, Orchestrator Timeline Reconciler creates canonical timeline, Visual Director plans assets from timeline, Composer renders timeline-obedient output with synced audio/subtitles/opening/CTA | P0 | MVP (Proposed) |

---

## 6. Safety Principles

| Rule | Behavior |
|------|----------|
| **Hard-block** | Illegal content, banned platform policy, clear high-risk defamation. **No override.** Job stops. |
| **Soft-warning** | Unverified claims. Requires cautious wording ("dikabarkan" — reported/said to be, "ramai dibahas netizen" — widely discussed by netizens). Emergency override allowed: only Creative Lead or Admin can override, must provide written reason, admin is alerted immediately, override logged in audit log. |
| **Post-research risk gate** | Topic may look safe before research but become risky after real entities/claims/URLs are discovered. Second safety check after research. |
| **Manual retry only** | No auto-retry on safety failures. Only Admin or Creative Lead can trigger retry. |

Safety always overrides cost saving.

---

## 7. Cost/Credit Principles

| Rule | Behavior |
|------|----------|
| **Cache before providers** | Never call ScrapeCreators/Firecrawl if cached research is fresh. |
| **Cheap before expensive** | Deterministic checks → ultra-cheap LLM → budget LLM → multimodal. |
| **No voice before script approval** | ElevenLabs only after script passes validation gate. |
| **No render before validation** | FFmpeg only after audio + assets pass validation gates. |
| **Lightweight cost estimate** | MVP shows estimated cost before generation. Full budget governance is Stage 2. |
| **Human stop on uncertainty** | If quota/credit/quality is unclear, stop and ask human. |

---

## 8. Failure/Fallback Policy

| Condition | Behavior |
|-----------|----------|
| Safety hard-block | Stop job. No override. Only Admin/Creative Lead notified. |
| Safety soft-warning | Continue with cautious wording. Override: Creative Lead or Admin, reason required, admin alerted, logged in audit. |
| Research quota exhausted | Ask Admin/Creative Lead for source URL or use Pexels/generated cards. |
| yt-dlp download fails | Try next source URL (max 5 attempts). If none: Pexels/local asset/generated cards. |
| Fewer than 2 usable sources | Proceed with 1 source + Pexels/generated cards. Log risk warning. |
| Voice provider fails | Try configured fallback chain: ElevenLabs → Gemini TTS → Fish Audio. If all providers are missing or fail, stop clearly and record sanitized provider attempts. Admin/Creative Lead triggers retry. Max 3 retries per job. |
| FFmpeg diagnostic fails | Pre-flight check fails before any render work — missing FFmpeg, libx264, aac, or mp3 support. Stop. Admin/Creative Lead must fix environment. |
| FFmpeg render fails | Stop. Admin/Creative Lead triggers retry. Max 3 retries per job. |
| Reviewer rejects | Recommend which step to retry. Admin/Creative Lead triggers. Max 2 retries. |
| Variation exhausted | MVP: Admin/Creative Lead review required. Stage 2: Creative Director. |

---

## 9. Asset Sourcing

| Source | Purpose | MVP Role |
|--------|---------|----------|
| **yt-dlp** | Download from 1000+ sites (YouTube, TikTok, IG, Twitter) | Layer 1 Primary |
| **Pexels** | Licensed stock video/images | Fallback |
| **User uploaded** | Local file path/import for approved client media | Accepted |
| **Third-party clips** | yt-dlp downloads with safeguards (<5s, transformed, multi-source target) | Core |

### Clip Safeguards

| Rule | Value |
|------|-------|
| Max clip duration | 5 seconds |
| Min clip duration | 1 second (clips <1s are flash frames, rejected) |
| Min unique sources target | 2. If <2 usable: proceed with 1 + Pexels/generated cards, log risk warning |
| Original voiceover | Required |
| Transformation | Required (re-encode, crop, speed, overlay, brightness/hue shift, pitch shift, metadata strip) |
| Attribution | When source is known |
| Risk logging | Always |

### Generated Cards Fallback

When no source clips or stock footage are available, the Visual Director generates text-based card images:
- **Format:** Static image (PNG) at 1080x1920 rendered by Pillow or FFmpeg drawtext.
- **Content:** Headline text + colored background + optional avatar/emoji.
- **Style:** Matches niche template (fonts, colors, layout from niche config).
- **Usage:** Integrated into scene sequence by Composer as full-screen slides between other clips.
- **Quality signal:** If a job uses only generated cards (no real clips or stock footage), the risk warning is escalated and the Reviewer is notified.
- **Relevant images:** Text cards attempt to include a relevant image via 3-tier fallback: Pexels photo search (`search_photos()`) → Firecrawl article og:image → gradient card background.

---

## 10. Success Metrics

| Metric | Target |
|--------|--------|
| Pipeline success rate | > 90% (video generated without errors) |
| Video generation time | < 15 minutes per video |
| Human review pass rate | > 80% (approved without rework) |
| Config-driven niche changes | No code changes required |
| Agent observability | All agent states visible in dashboard |
| LLM cost per video | < $0.01 (Budget East presets) |

---

## 11. Constraints

- **No GPU** for MVP — all rendering CPU-based (FFmpeg).
- ScrapeCreators limited to 75 free credits.
- TikTok Direct Post API requires 3-4 week approval process.
- Source media clips subject to platform copyright detection — transformative editing and original voiceover required.

---

## 12. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| TikTok API changes break scrapers | High | Multi-provider abstraction; manual fallback |
| yt-dlp site detection/blocks | Medium | Configurable sleep intervals, rotate user-agent, Cobalt fallback (Stage 2+) |
| Copyright/takedown on clipped assets | Medium | Safeguards: <5s, transformed, multi-source, original voiceover |
| Music licensing/copyright | Medium | Prefer platform-native sound during manual upload; fallback to no background music or safe stock music |
| LLM API cost at scale | Medium → Low | Chinese models ~14x cheaper than Western |
| Platform duplicate detection | Medium | Transformative editing, uniqueness layer, pre-generation memory check |
| Budget overspend | Low | MVP lightweight estimate warning; Stage 2 budget envelope |
| Financial data exposure | High | Role-based visibility; revenue/profit hidden from creative roles |

---

## 13. Cost Model

### Per-Job Cost by Strategy

| Strategy | LLM Cost | Voice Cost | Total |
|----------|---------|------------|-------|
| Budget East (default) | ~$0.003 | ~$0.03 | ~$0.033 |
| Agentic East | ~$0.008 | ~$0.03 | ~$0.038 |
| Premium East | ~$0.015 | ~$0.03 | ~$0.045 |
| Premium West | ~$0.04 | ~$0.03 | ~$0.07 |

> **Voice cost note:** Costs vary by provider. Provider order is quality/availability-first: ElevenLabs → Google AI Studio Gemini TTS → Fish Audio → fail clearly. Fish Audio ($15/1M chars) is ~6.7× cheaper than ElevenLabs ($100/1M chars). At ~200 chars/video, Fish Audio costs ~$0.003 vs ElevenLabs ~$0.02/video. Estimates above use ElevenLabs pricing as baseline. ElevenLabs and Fish Audio currently require paid plans; Gemini TTS uses the configured Google AI Studio quota/key.

### Financial Visibility

| Data | Admin/Finance | Creative Lead | Creative User |
|------|--------------|---------------|---------------|
| Estimated job cost | ✅ | ✅ | ✅ |
| Actual job cost | ✅ | ✅ (configurable) | ❌ |
| Remaining budget | ✅ | ✅ | ✅ |
| Client payment/margin | ✅ | ❌ | ❌ |

---

## 14. Future Stages

See `docs/design/evolution_plan.md` for full details.

| Stage | Adds |
|-------|------|
| **Stage 1.5** | Post URL input, public metrics collector, basic snapshot dashboard |
| **Stage 2** | Dashboard improvements, approval workflow, Serper, CSV import, budget envelope, actual cost tracking |
| **Stage 2+** | Official API connectors (OAuth), baseline tracking, outlier detection |
| **Stage 3** | Scheduled automation, multi-account, posting automation, learning loop, Creative Director |
| **Stage 3+** | Multi-platform, Multilogin integration |
| **Stage 4+** | Client portal, billing, 1,000+ account scale |
