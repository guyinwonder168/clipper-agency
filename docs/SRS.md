# Clipper Agency — Software Requirements Specification

**Version:** 3.4
**Date:** 2026-06-29
**Status:** Phase 23 Complete + ADR 0030 (Inter-Agent Contract Gates — implementation in progress: FIX-1/2/3/5/6 COMPLETE, FIX-4 COMPLETE [FR-77 entity-vs-beat + audio-not-truncated reviewer gates; MAX-DWELL→FIX-7]; FIX-7 pending)
**Related:** `docs/PRD.md`, `docs/technical_design.md`, `docs/requirements_traceability.md`

---

## 1. Platform Requirements

| Requirement | Specification |
|-------------|---------------|
| **OS** | Linux (primary), macOS (development), Windows (WSL2 acceptable) |
| **CPU** | x86_64, 4+ cores recommended for parallel FFmpeg |
| **GPU** | Not required (CPU-only FFmpeg rendering) |
| **RAM** | 8 GB minimum, 16 GB recommended |
| **Storage** | 20 GB free for outputs, assets, database |
| **Python** | 3.11+ |
| **FFmpeg** | 5.0+ with libx264, aac, mp3 support |
| **Docker** | Docker Compose for VPS deployment |

---

## 2. Functional Requirements

### 2.1 Pipeline

| ID | Requirement | Priority | Stage |
|----|-------------|----------|-------|
| FR-01 | Gated agent pipeline executes topic-to-output with pass/soft-fail/hard-fail at every transition | P0 | MVP |
| FR-02 | Safety Agent pre-checks topic before any paid generation using ultra-cheap model (GLM-4-9B) | P0 | MVP |
| FR-03 | Segment Producer Agent (formerly Researcher) gathers context + source URLs + music candidates via ScrapeCreators + Firecrawl, outputs structured edit blueprint with story_beats (visual_must_show/must_not_show, asset_candidates, overlay_text, caption_keywords), format_decision, verified_facts with safe_wording, unverified_claims, and do_not_use list. 5 sub-roles: Fact Checker, Viral Analyst, Clip Scout, Story Producer, Edit Planner. Renamed from `researcher.py` → `segment_producer.py`. See `docs/adr/0021-audio-first-continuous-voiceover.md` | P0 | MVP |
| FR-04 | Post-research risk gate: second safety check after real entities/claims/URLs are known | P0 | MVP |
| FR-05 | Scriptwriter Agent writes continuous voiceover narration (75-110 words, no emojis, spoken-word style) from Segment Producer's story_beats. Outputs voiceover_text + narrative_structure (beat_id, section, word_range, overlay_text, caption_keywords) + caption + hashtags. Removes per-scene max_words_per_scene formula in favor of total word budget | P0 | MVP |
| FR-06 | Voice Producer generates continuous voiceover via single TTS call (1 call instead of 8 per-scene = 87.5% cost reduction) with word-level timestamps. Primary: ElevenLabs `/with-timestamps` endpoint (character-level alignment grouped into words). Fallback: Gemini TTS (silence detection for approximate timing) → Fish Audio → fail clearly. Voice files and metadata saved under `ASSETS_CACHE/job_{id}/agents/voice_producer/` | P0 | MVP |
| FR-07 | Visual Director uses LLM to plan beat-driven visual strategy from story_beats + word-level timestamps. Each beat carries visual_must_show/visual_must_not_show rules, asset_candidates, and exact audio durations. Visual hierarchy: direct source clip → official screenshot → subject portrait with Ken Burns → text card → generic stock (abstract topics only). 3-tier image fallback for text cards: Pexels photo search → Firecrawl article image → gradient card. Falls back to legacy sequential planning when LLM unavailable. Sequential execution: Voice Producer must complete before Visual Director starts | P0 | MVP |
| FR-08 | Composer assembles video with single audio timeline (voiceover.mp3 as immutable anchor). Smart scene trimming: ffprobe keyframe boundary detection with ±15% tolerance, speed adjustment up to ±20% (imperceptible). Keyword captions (max 6 words, beat-aligned, bottom-positioned) replace full-sentence subtitles. Never trims or speeds up audio. Template-driven rendering via `clipper_agency/rendering/` engine with per-template adapters | P0 | MVP |
| FR-09 | Reviewer Agent performs hard gates and deterministic quality gates before LLM multimodal review: AV sync validation, caption quality, fact safety, narrative structure, visual coverage, text collision, safe-area, package consistency, timestamp-level semantic review, and semantic visual relevance. Consumes Composer diagnostics, `rendered_scene_manifest`, `story_beats`, and `word_timestamps` from the engine; rejects with repairable issue details. Max 2 retries by Admin/Creative Lead | P0 | MVP |
| FR-10 | Output packager produces `video.mp4` + `caption.txt` + `thumbnail.png` + `metadata.json` | P0 | MVP |
| FR-11 | Research cache with Time To Live (TTL): fresh <60min, stale 60-240min, expired >240min or new Asia/Jakarta day | P0 | MVP |
| FR-12 | Creative memory: pre-generation check prevents repetition; post-generation update records usage | P0 | MVP |
| FR-13 | Lightweight cost + credit estimate displayed before generation. Blocks job if insufficient credits. | P0 | MVP |
| FR-14 | Agent states, timestamps, failure summaries, gate results, and key artifact paths visible through debug-first dashboard/CLI observability | P0 | MVP |
| FR-15 | Asset/cache layout: intermediate agent/gate artifacts under `ASSETS_CACHE/job_{id}`, final customer package under `OUTPUT_DIR/job_{id}`, with downloaded media cacheable to avoid redundant downloads | P0 | MVP |
| FR-16 | Research data size guard: ScrapeCreators responses trimmed via `trim=true` + field extraction; researcher LLM input capped at 40K chars to prevent token overflow | P0 | MVP |
| FR-28 | Human-triggered retry and resume: CLI `job-retry <id> --from <agent>` re-runs from a specified agent, CLI `job-resume <id>` continues from a failed/paused stage; dashboard POST `/jobs/<id>/retry` and `/jobs/<id>/resume` routes provide the same controls | P0 | MVP |
| FR-29 | FFmpeg preflight diagnostic: before any render work, check `ffmpeg exists`, `ffprobe exists`, libx264 available, aac support, mp3 decode; fail clearly with diagnostic message if any missing | P0 | MVP |
| FR-30 | Generated card fallback: when no video clips or stock footage are available for a scene, generate 1080x1920 text-based PNG cards (headline, fact, context, CTA) using Pillow, styled from niche template; usage-only-cards condition escalates risk warning to Reviewer | P1 | MVP |
| FR-31 | Deterministic video validation (G10): before Reviewer multimodal spend, validate `video.mp4` exists, non-zero, 9:16 aspect ratio, 1080x1920, duration within configurable hard limit (default 60s), audio track present, h264/aac codec, metadata stripped | P0 | MVP |
| FR-32 | Treatment system: YAML-defined treatments in `templates/treatments.yaml` providing 9 visual treatments (ken_burns_zoom_in, ken_burns_pan_left, cinematic_crop, broll_standard, slow_motion, lower_third_slide, text_card_reveal, hook_big_caption, fade_to_black) + 5 transitions (crossfade, hard_cut, wipe_left, dissolve, circle_open) + FPS rules (30fps target) + pacing rules. Visual Director selects treatments per-scene; Composer applies via template-driven rendering engine. Adding new treatments requires YAML only, no code changes | P0 | MVP |
| FR-33 | Scene normalizer: unify mixed-asset framerates to 30fps target, normalize SAR to 1:1, apply Ken Burns zoompan for static images (2.5s zoom cycle), validate clip duration bounds (1-5s), enforce consistent encoding parameters (h264/aac) across all scenes before composition. Rejects flash-frame clips (<1s) and clips exceeding 5s | P0 | MVP |
| FR-34 | Audio sequencer: per-scene audio+video concat with two modes — Mode A (paired video+audio when no xfade) and Mode B (audio-only concat when xfade handles video). Pads missing audio with silence sources (anullsrc). Replaces broken amix that played all voice tracks simultaneously. Implemented in `clipper_agency/rendering/audio_sequencer.py` | P0 | MVP |
| FR-35 | Subtitle engine: converts script scene text into timed CaptionOverlay objects with absolute timestamps across scenes. Builds hook overlay (first 3s center-positioned caption) and validates TikTok output requirements (pix_fmt, faststart, libx264, aac, bitrate, shortest). Implemented in `clipper_agency/rendering/subtitle_engine.py` | P0 | MVP |
| FR-36 | Composer production output: xfade/concat mixed transition chain with offset calculation (cumulative_duration - trans_duration - safety_margin), duration clamping (min of transition_duration, min(prev_dur, next_dur) - headroom), fallback to crossfade for unknown transitions. Production flags: `-pix_fmt yuv420p`, `-movflags +faststart`, H.264/AAC codecs. Subtitle drawtext filters chained with `enable='between(t,start,end)'` and escape_drawtext for special characters | P0 | MVP |
| FR-37 | Segment Producer edit blueprint: outputs story_beats with per-beat visual instructions (visual_must_show, visual_must_not_show, asset_candidates, overlay_text, caption_keywords), format_decision (single_story_deep_dive / three_story_roundup / two_story_highlight), verified_facts with safe_wording, unverified_claims, and do_not_use list. Supersedes FR-37 (proposed content_direction) with richer beat contract | P0 | MVP |
| FR-38 | Scriptwriter continuous voiceover: writes single voiceover_text (75-110 words, no emojis, spoken-word style) from story_beats. Outputs narrative_structure mapping beats to word ranges with overlay_text and caption_keywords per beat. Total word budget replaces per-scene formula | P0 | MVP |
| FR-39 | Voice Producer single audio with timestamps: generates continuous voiceover via 1 TTS call (87.5% cost reduction). Returns voiceover.mp3 + word-level timestamps via ElevenLabs `/with-timestamps` (character-level grouped to words). Gemini TTS/Fish Audio fallback with silence-detection approximate timing | P0 | MVP |
| FR-40 | Shared schema contract via `config/schema.py`: 11 Pydantic models (StoryBeat, FormatDecision, VerifiedFact, UnverifiedClaim, VisualInstruction, AssetCandidate, KeywordCaption, VoiceSettings, VoiceProviderResult, ContentBrief, NarrativeSection) defining cross-agent data contracts | P0 | MVP |
| FR-41 | Beat-driven visual planning: Visual Director consumes story_beats + word timestamps + visual rules. Each beat has exact audio duration from timestamps. Sequential Voice→Visual execution enforced in engine | P0 | MVP |
| FR-42 | Audio-first composition: voiceover.mp3 is immutable timeline anchor (never trimmed). Composer smart-trims visuals at keyframe boundaries, overlays keyword captions (max 6 words, beat-aligned), speed-adjusts visuals ±20% to match audio | P0 | MVP |
| FR-43 | Visual coverage evaluation: `evaluate_visual_coverage()` in `clipper_agency/core/visual_coverage.py` scores frame-level visual completeness via sampled thumbnails. Detects black/freeze frames, blank regions, and insufficient visual content. Composer owns frame-level technical quality checks | P0 | MVP |
| FR-44 | OCR text region detection and collision checking: `detect_text_collisions()` in `clipper_agency/core/text_collision.py` identifies overlapping text bounding boxes from captions, overlays, and source clip text. `detect_source_text_density()` flags excessively dense on-screen text. Visual Director owns layout-level text compliance | P0 | MVP |
| FR-45 | Safe-area compliance: `detect_safe_area_issues()` in `clipper_agency/core/safe_area.py` validates caption and overlay placement against TikTok safe zones (top/bottom UI overlays, side action buttons). Visual Director owns safe-area positioning | P0 | MVP |
| FR-46 | Story mode classification: `classify_story_mode()` in `clipper_agency/core/story_mode.py` determines narrative structure (single_deep_dive, three_roundup, two_highlight) from segment producer output and validates consistency with actual scene composition | P0 | MVP |
| FR-47 | Duration budget allocation: `allocate_duration_budget()` in `clipper_agency/core/duration_budget.py` distributes total video duration across beats by role weight (hook, main_claim, evidence, reaction, closing_cta). Ensures no beat exceeds its allocated budget | P0 | MVP |
| FR-48 | Package consistency validation: `evaluate_package_consistency()` in `clipper_agency/core/package_consistency.py` validates that story mode, scene count, clip types, and visual hierarchy match the declared format_decision. Flags scope mismatches between declared and actual composition | P0 | MVP |
| FR-49 | Semantic visual relevance scoring: `score_visual_relevance()` in `clipper_agency/core/semantic_visual_review.py` scores claim-to-visual alignment using keyword overlap between story_beat narration goals and actual visual content. Uses evidence contracts on StoryBeat to verify each claim has supporting visuals | P0 | MVP |
| FR-50 | Structured repair routing: `route_repair()` + `build_repair_plan()` in `clipper_agency/core/repair_router.py` map quality gate failures to the correct existing agent for targeted repair. Routes visual coverage failures to Composer, text collision/safe-area failures to Visual Director, consistency/relevance failures to Segment Producer. Engine executes repair plan without creating new pipeline branches | P0 | MVP |
| FR-51 | Multi-provider asset source services: YouTube (yt-dlp search), Tavily (web news API), Brave (video/web search) with graceful per-provider fallback, entity-aware search queries, and source quality tier scoring (youtube_official=0.95, web_video=0.85, tiktok_clip=0.50, image=0.70, article=0.40, firecrawl=0.30) | P0 | MVP |
| FR-52 | YouTube thumbnail fallback: extract maxresdefault→hqdefault thumbnail as image asset candidate (0.70 quality tier) when no video clips available | P1 | MVP |
| FR-53 | Runtime FFmpeg black/freeze segment detection: `detect_black_segments()` + `detect_freeze_segments()` in `clipper_agency/core/media_detectors.py` with graceful `MediaDetectionError` fallback | P0 | MVP |
| FR-54 | Runtime frame extraction: `extract_frames()` with perceptual hashing (`perceptual_hash()`, `hash_distance()`) for deduplication in `clipper_agency/core/frame_extraction.py` and `frame_hashing.py` | P0 | MVP |
| FR-55 | PaddleOCR runtime text detection adapter: `PaddleOCRRuntimeAdapter` with model auto-download, confidence thresholding, and region normalization | P1 | MVP |
| FR-56 | MediaPipe face detection runtime adapter: `FaceDetectionRuntimeAdapter` using mp.solutions.face_detection with image array input | P1 | MVP |
| FR-57 | Source cleanliness scoring: `score_candidate()` in `clipper_agency/core/source_cleanliness.py` evaluates source type, resolution confidence, aspect ratio, and file size consistency | P0 | MVP |
| FR-58 | Final layout inspection pipeline: `inspect_final_layout()` pipelines FFmpeg black/freeze detection, text detection, face detection into structured `LayoutInspectionResult` | P0 | MVP |
| FR-59 | Story-mode reconciliation: 4-rule priority system in `story_decision_reconciliation.py`: (1) explicit niche override → (2) multi-entity roundup heuristic → (3) legacy format_decision contradiction → (4) fallback to single_story. Story-mode contract derivation: `derive_story_contract()` produces thumbnail_text, cta_text, duration_structure | P0 | MVP |
| FR-60 | Rendered scene manifest: `build_rendered_scene_manifest()` in `clipper_agency/core/rendered_scene_manifest.py` — RenderedSceneEntry/Manifest models, scene-to-beat temporal mapping via midpoint containment + range overlap | P0 | MVP |
| FR-61 | Reviewer context builder: `build_review_context_bundle()` in `clipper_agency/core/reviewer_context.py` — SceneBeatMapping, get_semantic_review_context() for timestamp-level scene review | P0 | MVP |
| FR-62 | Multimodal candidate inspection: `MultimodalInspectionClient` with base64 image encoding, retry, structured JSON parsing, and SHA-256 inspection cache. `candidate_semantic_ranker.py` combines inspection + relevance + cleanliness + credibility with rejection rules | P1 | MVP |
| FR-63 | LLM trace artifacts: `chat_traced()` in `OpenRouterClient` for structured trace persistence; `TraceWriter` protocol for pluggable trace backends | P1 | MVP |
| FR-64 | Bounded automated repair loop: `_execute_repair_cycle()` in engine with max N cycles, identical-patch exhaustion detection (`_are_patches_identical()`), cycle output retention (`cycle_{n}` subdirs), promotion on approval | P0 | MVP |
| FR-65 | Repair quality metrics: `compute_repair_cycle_record()`, `extract_quality_snapshot()`, `is_repair_improved()`, `persist_repair_cycle()` in `clipper_agency/core/repair_metrics.py` | P0 | MVP |
| FR-66 | Publication blocking: rejected artifacts retained under `outputs/job_{id}/`. `_promote_to_final()` requires quality=passed AND artifact=approved. Atomic promotion via temp dir + rename | P0 | MVP |
| FR-67 | Timestamp-level semantic review integrated into reviewer gate chain: `map_scenes_to_beats()` maps rendered scenes to story beats, `_run_timestamp_semantic_review()` emits SceneSemanticReview with evidence contracts | P0 | MVP |
| FR-68 | Reviewer diagnostics passthrough and manifest serialization: Orchestrator engine passes Composer diagnostics and rendered scene manifest to Reviewer in `_retry_review_and_package()` and repair rerun path; `RenderedSceneManifest` is serialized to dict before Reviewer gate code consumes `entries` | P0 | MVP |
| FR-69 | Pre-Visual-Director asset-qualification boundary: `clipper_agency/core/asset_qualification.py` scores each beat's `asset_candidates` BEFORE Visual Director consumes them, via the engine seam `_apply_asset_qualification` in `Orchestrator._run_visual_director_phase`. Each beat is immutably rewritten so `beat.asset_candidates` contains only the qualified set; rejected candidates never reach Visual Director's live per-beat surface. The flat candidate pool is defense-in-depth filtered. Enforcement is pure orchestration — no new agent, no new gate, no schema change, no state-machine change (ADR 0026). The cache-miss inspection delegates to Visual Director's own bound `_run_multimodal_inspection` so cached output is byte-identical to Visual Director's, with no cache-namespace drift and frame ownership staying in Visual Director (ADR 0027) | P0 | MVP |
| FR-70 | Bounded source recovery before text-card fallback: when a beat has zero qualified candidates, a RECOVER stage re-runs Segment Producer discovery for fresh candidates and re-scores them instead of immediately degrading to a text card. Recovery is bounded to MAX_RECOVERY_CYCLES=1 (no loop). Job #8 root cause was candidate rejection, not scarcity; recovery strictly reduces text-card fallbacks versus the all-reject baseline | P0 | MVP |
| FR-71 | Qualification report artifact: a `qualification_report.json` artifact is emitted per job documenting per-beat verdicts (qualified / recovered / exhausted_text_card), recovery outcome, and reject reasons for every rejected candidate | P0 | MVP |
| FR-72 | Clip-window selector (minimal, contract-first): `clipper_agency/core/clip_window.py` exposes a frozen `ClipWindow` dataclass, a pluggable `WindowSelector` Protocol, and a conservative v1 default `KeywordOverlapWindowSelector` (returns the full-clip window `ClipWindow(0.0, None)` for every candidate since keyword overlap cannot localize a spoken point to a timestamp). `AssetCandidate` gains optional `source_start_sec: float = 0.0` / `source_end_sec: float | None = None` (additive, defaults preserve today's from-zero trim; excluded from the inspection content hash so FR-69 cache-key parity holds). The window propagates qualification seam → Visual Director → Composer, where `_smart_trim` clamps it to source bounds (degenerate ⇒ full clip) and `_trim_long_clip`/`_stretch_short_clip` emit `-ss <start>`. The transcript/whisper backend, auto-caption extraction, and keyframe-precise snapping are DEFERRED to post-v2.4.0 (ADR 0026 do-not-rebuild, GPU forbidden, no transcript infra, release gate does not require clip-windowing). Pure orchestration — no new agent, no new gate, no state-machine change | P2 | MVP |
| FR-73 | Visual Director LLM JSON-parse robustness (job_17 fix): the VD planning LLM call (`_llm_plan_scenes_response` in `clipper_agency/agents/visual_director.py`) requests OpenRouter JSON mode via `response_format={"type":"json_object"}` on both the traced (`chat_traced`) and untraced (`chat`) paths (forwarded through `OpenRouterClient.chat_traced`'s new `**kwargs` passthrough). Per OpenRouter + Xiaomi MiMo docs, MiMo-V2.5 supports `json_object` (JSON mode) but NOT native strict `json_schema` constrained-decoding, so the parse is additionally backed by a `json_repair` salvage net in a static `_parse_scenes_json` helper: on `JSONDecodeError` from the primary `json.loads`, `json_repair.repair_json` runs, and only when BOTH passes fail does it raise. This eliminates the malformed-JSON → 0-assets → G9 hard-fail class (job_17 root cause: a single stray extra `}` in a nested scene `fallback` object killed the whole job). Both planning entry points return `None` when the recovered plan is empty so the deterministic legacy fallback is used instead of a 0-scene plan. `json-repair==0.61.0` pinned in `requirements.txt`. Pure parse-robustness + structured-output — no new agent, no new gate, no state-machine change (ADR 0026) | P0 | MVP |
| FR-74 | **Narrative-coverage contract gate (G7 GateNarrativeCoverage, ADR 0030 — job_18 root cause; FIX-8 cue-anchor):** a deterministic gate asserts that Scriptwriter `narrative_structure` `word_range` indices fully cover `voiceover_text` — (a) every `word_range` in-bounds `[0, len(words)-1]`; (b) beats sorted + contiguous (`beat[i].end+1 == beat[i+1].start`); (c) the union of `word_range` == `[0, len(words)-1]` within tolerance (last beat `end >= len-1 - floor(len*0.05)`). Enforced AFTER Scriptwriter, BEFORE Voice Producer (in `engine._stage_content`). **FIX-8 (cue-anchor contract):** the LLM cannot reliably count its own words (job_19 over-index, job_20 under-index), so the Scriptwriter now emits `start_cue` (3-5 first words of each beat copied VERBATIM from `voiceover_text`) instead of `word_range`; CODE derives the indices via `clipper_agency/core/beat_anchor.py::derive_word_ranges` (Indonesian tokenizer, fuzzy position via `max(Jaccard, LCS ratio) ≥ 0.6`, deterministic). On cue failure (`cue_not_found` / `cue_out_of_order`) the gate hard-fails with the stable `narrative_not_covered` routing token so FIX-5 routes to Scriptwriter regen. The legacy FIX-1 `word_range` validator stays as defense-in-depth (in-place repair for uncovered tail <5 % of words) and as the fallback path for word_range-only inputs. ADR 0030 amends ADR 0026's no-rebuild default FOR OUTPUT-QUALITY WORK ONLY (product owner has lifted the constraint). Pure contract enforcement — no new agent, no state-machine change | P0 | ADR 0030 |
| FR-75 | **Audio-as-master — audio never truncated (ADR 0030, MoneyPrinterTurbo policy):** the Composer no longer ends the final FFmpeg assembly with `-shortest` (which silently cut the last ~2.6 s of job_18's CTA "…like dan share"); it emits an explicit `-t voiceover_duration` so the audio stream is the authoritative fixed-length source. Before invoking FFmpeg the Composer computes `sum(scene.target_duration)` and, if it is `< voiceover_duration_sec - tolerance`, PADS the visual track (loop/extend last still / cycle earlier clips) so visual ≥ audio — preferring a re-run of Visual Director to discover more assets over blindly looping (loop is the last-resort "use anyway, never freeze" backstop). A new **G9.5 GateVisualAudioCoverage** between Visual Director and Composer asserts `sum(planned scene durations) >= voiceover_duration_sec` and routes repair to Visual Director on failure. G10 is strengthened with an independent audio-stream re-probe (`AUDIO_NOT_TRUNCATED`: final video audio duration `>= voiceover_duration_sec - 0.5 s`), immune to `-shortest` equalization | P0 | ADR 0030 |
| FR-76 | **Entity-binding rejection at the qualification/Visual-Director chokepoint (ADR 0030, wrong-artist fix):** the shared `candidate_semantic_ranker.apply_rejection_rules` (consumed by BOTH pre-VD `asset_qualification._rank_and_select` and `VisualDirectorAgent._apply_best_candidate` — cache-key parity means one rule fixes both layers) gains a `WRONG_ENTITY` rejection: after `select_best_candidate`, the inspection's returned `subject_name` / depicted entity must overlap the beat's `spoken_point` + the job's `main_entities` (fuzzy/normalized string-token overlap, tolerant of aliases like Sarwendah/Sarwenda); on mismatch the candidate is rejected (`reason=WRONG_ENTITY`) and the beat falls back / recovers. The VLM inspector (`_run_multimodal_inspection`) MUST return `subject_name`; a missing field degrades to `revise` (not accept). The `misleading_risk` `person_match` threshold in `semantic_visual_review.py` lowers 0.8 → ~0.6. A hard `MAX_BEAT_DURATION_SEC` / max-scene cap (e.g. 12 s) in `beat_timeline.py` + VD scene planning forbids a single card from rendering a 25 s beat (must split into N scenes or fail back to Scriptwriter). job_18's Jennifer-Coppen-for-Sarwendah selection passed because "accept" was a numeric threshold with no name check. CLIP image-text relevance ranking is the future Phase 27+ upgrade | P0 | ADR 0030 |
| FR-77 | **Reviewer per-scene detection — entity-vs-beat, frozen-frame, audio-not-truncated (ADR 0030):** `_check_av_sync` is extended beyond the single total-duration scalar (which `-shortest` equalization structurally defeated, passing job_18): (1) `AUDIO_NOT_TRUNCATED` — re-probe the final video's audio stream independently of the visual track and assert `>= voiceover_duration_sec - 0.5 s`; (2) per-scene `ENTITY-VS-BIND` — for each `rendered_scene_manifest` entry, the `selected_asset`'s `subject_name` must match the temporally-mapped beat's `spoken_point` / `main_entities` (via `reviewer_context.map_scenes_to_beats`); hard-fail `WRONG_ENTITY` on mismatch; (3) `MAX-DWELL` / frozen-frame — flag any static card held >4 s without a qualifying change-event (treatment motion, caption reveal); (4) flag scenes matched to a synthetically-extended / uncovered-tail beat. The Reviewer is the last line before "completed" and must no longer be structurally blind to a frozen card, a wrong face, or a truncated CTA. **Implementation (FIX-4):** sub-requirements (1) AUDIO_NOT_TRUNCATED reviewer defense-in-depth re-probe and (2) per-scene ENTITY-VS-BIND (reason token `ENTITY_MISMATCH`) are COMPLETE — both reuse FIX-2/FIX-3 machinery (`media_probe.AUDIO_TRUNC_TOL_SEC` single-source constant; `derive_expected_entities` + `entity_overlap`); `subject_name` threaded VD→Composer manifest→Reviewer; `voiceover_duration_sec` wired on both engine reviewer paths. Sub-requirement (3) MAX-DWELL/frozen-frame is DEFERRED to FIX-7 (engagement gates); (4) uncovered-tail-scene is redundant with FR-79 (FIX-6 `UNCOVERED_TAIL` already shipped) | P0 | ADR 0030 |
| FR-78 | **Repair-router root-cause routing + bounded regeneration (ADR 0030):** `_rerun_upstream_cascade` routes the repair to the ROOT agent via the failure REASON — Scriptwriter for `narrative_not_covered` / coverage gaps (FR-74), Visual Director for entity/split/dwell failures (FR-76/FR-77), Composer for audio-truncation/`-shortest` failures (FR-75). When a coverage gate would re-fail, it FORCES `narrative_structure` regeneration (re-run Scriptwriter with an explicit "cover ALL words" instruction) instead of rebuilding `beat_timeline` from the known-broken structure. A bounded `MAX_REPAIR_CYCLES` + a terminal fail-state guarantee a job that cannot satisfy the coverage gate after N regens FAILS — it never "completes" garbage (job_18's defect re-occurred every cycle because the loop re-derived the timeline from the unchanged broken `narrative_structure`). A voiceover-text-diff skip optimization (claude-auto-tok pattern) skips the expensive Voice Producer call when a revision touches non-voiceover fields only | P0 | ADR 0030 |
| FR-79 | **Timeline UNCOVERED_TAIL detection + MAX-beat cap (ADR 0030, defense-in-depth behind FR-74):** `build_canonical_timeline` stops being a silent failure amplifier. It DETECTS uncovered gaps — if `(final timestamp end) - (last beat's intended end_sec)` exceeds `max(2.0 s, one nominal beat span)`, it emits a structured `UNCOVERED_TAIL` signal the orchestrator can gate on. A `MAX_BEAT_DURATION_SEC` cap (e.g. 12 s or 1.5× the longest real beat) rejects a 25 s single entry as non-physical instead of manufacturing one. The "cover trailing audio" heuristic becomes a logged, gated extension, not an invisible patch. Even with FR-74 in place, IF a partial structure ever reaches the timeline (gate bypass, future regression), it surfaces a warning and rejects a non-physical entry rather than amplifying the upstream defect into a 25 s mega-beat | P1 | ADR 0030 |
| FR-80 | **Engagement gates — TikTok-post-worthy quality bar (ADR 0030):** programmatic_checks beyond correctness, defending against the five "AI low-effort tells" (frozen static image, mismatched B-roll, audio cutoff, monotony, bad pacing): (1) VISUAL-CHANGE-DENSITY — minimum change-events per 1.5–4 s (~8–15 for a 30 s video); a beat plan with 1–2 images for 25 s+ fails; (2) HOOK — beat 0 must be a real image/motion, not a title/text card; first visual change by 1.5 s; (3) DURATION-BAND — final video lands in the 21–42 s infotainment/gossip sweet spot; (4) MONOTONY — no same content-hash image across consecutive beats without treatment variation; beat-aligned caption reveals (2–3 words, word-synced) count as change-events. These are WARN+repair gates (not pipeline-death), differentiating hook pacing ("breathe") from body pacing ("aggressive interrupts"); sourced from creator-economy guidance (~4 s interrupts correlate with ~58 % vs 41 % retention), not hard TikTok-API data | P1 | ADR 0030 |

### 2.2 User Interfaces

| ID | Requirement | Priority | Stage |
|----|-------------|----------|-------|
| FR-17 | Web dashboard for job management, agent configuration, niche profiles | P0 | MVP |
| FR-18 | CLI: `python3 cli.py run --topic "..." --niche indonesian_artists` | P0 | MVP |
| FR-19 | CLI `test-agent` subcommand: run individual agents independently for debugging/testing, bypassing orchestrator DB tracking | P1 | MVP |
| FR-20 | Configurable agent autonomy levels | P1 | MVP |
| FR-21 | Selectable video templates (manual or agent-auto) — implemented via `clipper_agency/rendering/` with YAML template definitions in `templates/*.yaml` and per-template adapters | P1 | MVP |

### 2.3 Configuration

| ID | Requirement | Priority | Stage |
|----|-------------|----------|-------|
| FR-22 | Configuration hierarchy: Agent defaults → Niche → Account → Job-level overrides | P0 | MVP |
| FR-23 | All agent settings configurable per level (LLM model, prompt version, temperature, max tokens, voice ID) | P0 | MVP |
| FR-24 | Per-agent LLM model configuration via environment variables (`SAFETY_MODEL`, `SEGMENT_PRODUCER_MODEL`, `SCRIPTWRITER_MODEL`, `REVIEWER_MODEL`, `VISUAL_DIRECTOR_MODEL`) with sensible defaults | P0 | MVP |
| FR-25 | Structured logging for all external API calls, agent executions, and pipeline state transitions with configurable log level (`LOG_LEVEL`) | P0 | MVP |
| FR-26 | Config versioning with diff and rollback | P0 | MVP |
| FR-27 | Niche profiles swappable without code changes | P0 | MVP |

---

## 3. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-01 | Video generation time | < 15 minutes per video |
| NFR-02 | Pipeline success rate | > 90% |
| NFR-03 | Human review pass rate | > 80% |
| NFR-04 | LLM cost per video | < $0.01 (Budget East) |
| NFR-05 | CLI startup | < 2 seconds |
| NFR-06 | Dashboard page load | < 3 seconds |
| NFR-07 | All agent state transitions persisted with timestamps and observable through DB/dashboard/CLI | Required |
| NFR-08 | Jobs restartable in principle from persisted DB state plus `ASSETS_CACHE/job_{id}` agent/gate artifacts; write-enabled retry/resume implemented after artifact contract stabilization | Required |
| NFR-09 | Agent contracts identical at all scales (MVP → 1000+ accounts) | Required |
| NFR-10 | All external API calls log request parameters, response status, token usage, cost estimate, and latency | Required |
| NFR-11 | Zero double-VLM spend on pre-qualified candidates: `asset_qualification._score_candidate` and Visual Director `_score_one_candidate` compute byte-identical cache keys, so Visual Director's re-inspection of a pre-qualified candidate is a cache hit | Required |

---

## 4. Integration Requirements

### 4.1 External Services (Required for MVP)

| Service | Purpose | Auth | Rate/Credits |
|---------|---------|------|--------------|
| OpenRouter | LLM access for all agents | API key | Per-model limits |
| ElevenLabs | Voice generation (primary) — via the official `elevenlabs` Python SDK (ADR 0029; typed `VoiceSettings` + typed alignment) | API key (`ELEVENLABS_API_KEY`) | Free tier: premade voices + Voice Design usable via API; shared Voice-Library voices + Instant/Professional Voice Cloning = paid (Creator+/Pro). Default model `eleven_multilingual_v2` (env-configurable via `ELEVENLABS_MODEL`). |
| Google AI Studio Gemini TTS | Voice generation fallback after ElevenLabs | API key (`GEMINI_API_KEY`) | Google AI Studio quota/limits; default voice `GEMINI_TTS_VOICE_NAME=Kore` |
| Fish Audio | Voice generation fallback after Gemini TTS | API key (`FISHAUDIO_API_KEY`) | No free tier — Plus plan ($11/mo) required for API access |
| Pexels API | Stock video/images fallback + photo search for text card images (`search_photos()`) | API key (free) | 200 requests/hr |
| yt-dlp | Video/audio download from 1000+ sites | None | Site-specific limits |
| ScrapeCreators | TikTok video URLs, creator data, song metadata | API key (`x-api-key`) | 75 free credits; `trim=true` + field extraction reduces 1-2MB raw responses to ~500 chars/result |
| Firecrawl | Web search + structured page scraping | API key | Daily free runs |

### 4.2 Provider Routing

```
Cache → ScrapeCreators (TikTok video/music) + Firecrawl (context/news)
→ If quota exhausted or no usable URL: ask user for source URL
→ If no source URL: Pexels/local asset/generated cards
Stage 2: + Serper. Stage 2+: + DuckDuckGo site-filtered.
```

**Voice provider fallback:** `ElevenLabs → Google AI Studio Gemini TTS → Fish Audio → fail clearly`.
- `ELEVENLABS_API_KEY` set → try `ElevenLabsService` first.
- If ElevenLabs is missing or fails, `GEMINI_API_KEY` set → try `GeminiTTSService` (`gemini-2.5-flash-preview-tts`, default voice `Kore`).
- If Gemini TTS is missing or fails, `FISHAUDIO_API_KEY` set → try `FishAudioService` (s2-pro model, `/v1/tts` endpoint).
- If all providers are missing or fail, pipeline stops with a clear error and sanitized attempts are persisted under the job workspace.

ScrapeCreators credits reserved for TikTok video URLs, creator profiles, engagement data, and song metadata. Results cached with TTL to minimize credit burn. Segment Producer preserves raw ScrapeCreators/Firecrawl payloads and normalized research artifacts under `ASSETS_CACHE/job_{id}/agents/segment_producer/`.

### 4.3 External Services (Future)

| Service | Purpose | Stage |
|---------|---------|-------|
| Cobalt/pybalt | Video download, different engine | Stage 2+ |
| instaloader | Instagram media | Stage 2+ |
| Douyin_TikTok_Download_API | TikTok/Douyin specialist | Stage 2+ |
| Serper API | Backup search | Stage 2 |
| DuckDuckGo site-filtered | Free fallback search | Stage 2+ |

---

## 5. Security Requirements

### 5.1 Secrets Management

- **No secrets stored in database** — only environment variable name references.
- Secrets via `.env` (local) or environment variables (production).
- `.env` loaded centrally via `clipper_agency/bootstrap.py` `load_env()` (idempotent, `override=False`) at three chokepoints: CLI `__main__.py` import-time, Flask `dashboard/app.py` import-time, and `Orchestrator.__init__` (covers dashboard-create + retry + resume). `pydantic-settings` `AppSettings` provides typed access; services read `os.getenv()`. See ADR 0028.
- Dashboard shows `configured ✅` or `missing ❌`, never exposes values.

### 5.2 Authentication & Authorization

| Requirement | MVP | Future |
|-------------|-----|--------|
| Dashboard auth | Basic auth + 2 groups (privileged, creative/ops) | OAuth2 / SSO |
| Role-based access | 2 groups | 4 roles (admin, creative lead, creative user, reviewer) |
| API auth | Not required (local only) | API keys |

### 5.3 Data Protection

- Client revenue, gross profit, margin **restricted** to privileged group.
- Creative users see operational budget only (estimated cost, remaining).
- Budget overrides and approvals logged in audit log.
- Soft deletes for data recovery.

---

## 6. Data Requirements

### 6.1 Database

| Requirement | MVP | Scale |
|-------------|-----|-------|
| Engine | SQLite | PostgreSQL |
| Schema | Same schema | Migrates with Alembic |
| Access | Local file | TCP connection |

### 6.2 Data Entities

| Entity | Description | Sensitive |
|--------|-------------|-----------|
| Jobs | Generation jobs with status, timestamps, config snapshot | No |
| Agent states | Per-agent inputs, outputs, state per job | No |
| Agent configs | Per-agent LLM, prompt, model, voice settings | Yes (API key refs) |
| Niche profiles | Language, tone, rules, video length | No |
| Accounts | TikTok accounts (1 for MVP) | Yes (credentials) |
| Outputs | Final package metadata, paths, scores | No |
| Creative history | Used angles, templates, assets per topic | No |
| Assets | Source metadata, license, hash, provider | No |
| Research cache | Cached research with Time To Live (TTL) (URLs, metadata, entities, tags, facts, risk flags, music) | No |
| Audit log | All actions | Yes (compliance) |
| Config versions | Patches with rollback snapshots | No |
| Prompt versions | Prompt version tracking with diffs | No |
| Templates | Video template definitions (layout, fonts, colors, animations) | No |
| Preflight estimates | Lightweight cost estimate before job | No |
| Job artifact workspace | Per-job intermediate artifacts, agent inputs/outputs, gate results, diagnostics, and manifest under `ASSETS_CACHE/job_{id}` | No |
| Job snapshots | Full reproducibility data | No |

### 6.3 Retention Policy

| Data Type | Duration |
|-----------|----------|
| Job metadata, config snapshots, output metadata | Indefinite |
| Agent inputs/outputs, gate results, manifests, diagnostics | 180 days |
| Raw provider payloads (ScrapeCreators, Firecrawl, TTS attempts metadata) | 90 days |
| Heavy intermediate assets in `ASSETS_CACHE/job_{id}` | 30 days |
| Failed render artifacts and FFmpeg diagnostics | 14 days |
| Final output packages | 365 days |

### 6.4 Audit Requirements

- All budget overrides, config patches, and role changes logged.
- Every approved prompt/config/template change versioned with diff.
- Rollback to any previous config version.

---

## 7. Compliance Requirements

| Area | Requirement |
|------|-------------|
| **Platform policy** | TikTok: target output governed by configurable `content_planning.hard_limit_sec`; 9:16 vertical; caption 150 chars; 5 hashtags max. 60s is MVP product policy, not universal TikTok ToS |
| **Copyright** | Third-party clips <5s, transformed, multi-source, original voiceover |
| **Content safety** | Safety Agent pre-checks before generation (cheapest model). Hard-block illegal/banned/high-risk defamation. Soft-warning for unverified claims. |
| **Unverified claims** | Soft wording required ("dikabarkan" — reported/said to be, "ramai dibahas netizen" — widely discussed by netizens) |
| **FFmpeg output** | Metadata stripping for platform-native appearance |

---

## 8. Deployment Requirements

| Requirement | MVP | Stage 2+ |
|-------------|-----|----------|
| Deployment | Local machine + manual | Docker Compose on VPS |
| Scaling | Single worker, sequential jobs | Parallel workers, DB-backed queue |
| Concurrency | SQLite Write-Ahead Logging (WAL) + advisory lock prevents concurrent CLI runs | DB-backed queue handles concurrency |
| Container | Dockerfile + docker-compose.yml | Same |
| CLI | `python3 cli.py run --topic "..."`; `python3 -m clipper_agency test-agent <AGENT> [OPTS]`; `--log-level` option | Same + `test-agent` for debugging |
| Dashboard | Flask/FastAPI + basic auth + 2 groups | Same + full role auth |
| Voice | ElevenLabs → Gemini TTS → Fish Audio fallback from env vars | Same |

### Scaling Path

```
MVP (1 account)              Scale (10-100)              Full (1000+)
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ Single worker    │     │ Docker Compose   │     │ K8s / Multi-VPS  │
│ Sequential jobs  │ →   │ PostgreSQL       │ →   │ PG + Redis       │
│ SQLite           │     │ DB-backed queue  │     │ RQ/Celery workers│
│ CLI + Dashboard  │     │ 2-3 workers      │     │ Auto-scale       │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

Agent contracts remain identical at all scales. Queue interface abstract. Workers stateless.
