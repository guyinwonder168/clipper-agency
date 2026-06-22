# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Bug Fixes
- **RC-2 (asymmetric AV-sync hard gate):** the AV-drift hard gate in `ReviewerAgent._check_hard_gates` (`agents/reviewer.py`) was asymmetric — it only hard-failed when `visual_duration_sec < audio_duration_sec`. The opposite drift direction (video LONGER than audio — e.g. a trailing clip / over-long scene) tripped `_check_av_sync` but fell through to the non-deterministic LLM, which could pass it. Added a SYMMETRIC hard-fail branch: when `(visual_duration_sec - audio_duration_sec) > _AV_DRIFT_TOLERANCE_SEC`, hard-fail with the same `av_duration_mismatch` issue type (mirrors the existing shorter-than path; the shorter-than branch is unchanged). ADR 0026 (pure contract enforcement, no new agent/gate/state-machine). Regression tests in `tests/test_reviewer_avsync_and_temporal_match.py`; the stale `test_hard_gate_passes_when_video_covers_audio` premise (which used a 2.0s over-tolerance drift) updated to within-tolerance drift to preserve its original intent under the corrected symmetric contract.
- **RC-4 (temporal_match signal discarded):** `core/semantic_visual_review.py:score_visual_relevance` read only `person_match`/`event_match`/`claim_support`/`visual_quality` and DISCARDED the `temporal_match` signal the VLM returns. Wired `temporal_match` into the weighted sum via `_SCORED_DIMENSIONS`, with a NEW configurable weight `_TEMPORAL_MATCH_WEIGHT = 0.0` (documented single knob for a follow-up PR). At the default 0.0 the term cannot move the score — accept/revise/reject behavior is byte-identical whether `temporal_match` is 0.0 or 1.0 (guard test in `tests/test_reviewer_avsync_and_temporal_match.py`). Raising the weight + asserting a lowering effect is a separate follow-up gated on PR 13 confirming correlation. ADR 0026 (enforce contracts, do not rebuild).
- **RC-9 (Reviewer repair loop blind to rendered scenes):** two persistence/key defects starved the semantic review of scene data. **RC-9a** — `Composer._run_audio_first_render` and `_try_assemble` wrote the agent `output.json` to disk BEFORE attaching `rendered_scene_manifest` (and `generated_text_regions`/`visual_coverage` diagnostics), so the on-disk JSON omitted the manifest; the repair-loop reconstruction (`_run_cached_upstream_repair` → `_reconstruct_upstream_outputs` → `_load_agent_output` reads `output.json`) therefore found no manifest and the loop was blind. Reordered so the single authoritative `write_json` runs AFTER the manifest/diagnostics are attached. **RC-9b** — `core/reviewer_context.py:get_semantic_review_context` read `manifest.get("scenes", [])`, but `RenderedSceneManifest` serializes its entries under the `"entries"` key (already used correctly by `_run_timestamp_semantic_review`), so the review always saw an empty scene list. Corrected to `manifest.get("entries", [])`. Pure persistence/ordering/key fix — ADR 0026 (no new agent/gate/state-machine). Regression tests in `tests/test_rendered_scene_manifest_persistence.py`.
- **RC-5 (canonical-timeline guard — defense-in-depth):** the falsy guards `if beat_timeline:` in `VisualDirectorAgent._run_beat_driven_planning` (`visual_director.py`) and `ComposerAgent._try_audio_first_assemble` (`composer.py`) treated a *present-but-empty* canonical timeline (`beat_timeline=[]`, which `build_canonical_timeline` returns on degenerate/empty input) identically to a missing timeline, silently falling through to each agent's PRIVATE divergent recompute (`_calculate_beat_durations` / `_compute_beat_durations`). This violated the ADR 0020 single-source-of-truth contract that PR #52 intended. Changed both guards to `if beat_timeline is not None:` so the canonical path is honored even when the timeline is empty (`timeline_to_duration_map`/`timeline_to_duration_list` tolerate `[]` safely → `{}`/`[]`). Happy path (non-empty list) is byte-identical. Reachability on real production jobs is UNCONFIRMED — this is defense-in-depth. Regression tests in `tests/test_beat_timeline_canonical_contract.py`. ADR 0026 (pure contract enforcement, no new agent/gate/state-machine).
- **RC-8 (freezedetect never worked):** `Composer._FREEZE_NOISE_THRESHOLD` was `-30.0` with a misleading "dB threshold" comment, but FFmpeg's `freezedetect` `n` parameter is a **noise-tolerance ratio in `[0, 1]`**, not dB. The installed ffmpeg rejected `n=-30.0` with `Value -30.000000 for parameter 'n' out of range [0 - 1]` (rc=1) on every run, so `_safe_detect_freeze` logged "Composer: freeze detection failed" and returned `[]` — freeze detection had never flagged anything. Corrected to the documented ffmpeg default `0.001` (the value that catches truly frozen frames: <0.1% pixel change). This also supersedes the PR #51 changelog claim that `freezedetect=n=-30.0:d=0.1` was "valid FFmpeg syntax" — the syntax parsed but the value was illegal, so the filter never initialized. Regression test added in `tests/test_media_detectors.py` that builds the production filter string and runs it against real ffmpeg (rc==0, no "out of range" error). Corrects `clipper_agency/agents/composer.py`; `media_detectors.py` filter formatting unchanged. ADR 0026 (enforce contracts, do not rebuild).
- **RC-7 (frame sampler offsets unbounded to source media):** `run_frame_inspection_pipeline` (`core/frame_inspection_pipeline.py`) trusted the ffprobe `format.duration` unconditionally and `plan_frame_samples` (`core/frame_sampler.py`) emitted offsets up to that raw value. On some yt-dlp TikTok/YouTube downloads ffprobe reports a stale/huge container duration (e.g. 723.0s for a ~30s clip), so the sampler generated offsets every 0.5s out to 723s — the job_12/job_13 storm of "Failed to extract frame metadata at 502.689s / 723.000s / 465.000s ..." that wasted VLM-bound inspections on out-of-range reads. Fix: `plan_frame_samples` gained an optional `max_offset_sec` that clamps EVERY offset (intervals, trailing duration, scene boundaries) to `[0, max_offset_sec]`; the pipeline computes an effective safe bound — `min(raw_duration or safe_ceiling, DEFAULT_MAX_EXTRACTION_OFFSET_SEC=30.0)` — so a missing/<=0 probed duration falls back to the conservative 30s ceiling instead of leaking into the hundreds of seconds. Pure bounds fix, ADR 0026 (no new agent/gate/state-machine). Regression tests in `tests/test_frame_sampler_source_bounds.py`.
- **RC-8 follow-up (test-only, ECC review cleanups):** the RC-8 fix left two test landmines. (1) `test_real_ffmpeg_accepts_default_freezedetect_noise_threshold` carried only `@requires_ffmpeg` (not `@pytest.mark.integration`), so it silently skipped in the offline gate and left the `[0,1]` contract unguarded there; added a NEW non-skipped pure-unit guard in `tests/test_freezedetect_contract.py` asserting `0.0 <= _FREEZE_NOISE_THRESHOLD <= 1.0` that runs on every offline gate, and marked the real-ffmpeg test `@pytest.mark.integration`. (2) Stale mock-backed and integration assertions in `tests/test_media_detectors.py` / `tests/test_ffmpeg_quality_integration.py` still hardcoded the malformed `-60` / `-55` dB thresholds ffmpeg rejects (false coverage); corrected them to legal ratios (`0.001` mock / `0.01` integration). The freeze-detection integration tests in `TestFreezeFrameDetection` are now marked `@pytest.mark.integration` (real-FFmpeg tier) so they deselect cleanly in the offline gate. TEST-ONLY — zero production code changed. ADR 0026 compliant.

### Documentation
- Clarified the Codex review gate in `AGENTS.md`: a 👍 (thumbs-up) reaction from `chatgpt-codex-connector[bot]` with no written comments is the Codex **pass** signal. It is a reaction (not a formal `APPROVED` review), so GitHub's `reviewDecision`/`reviews[]` stay empty by design and this does NOT block the merge. Documented in both the step-by-step workflow (Step 6) and the condensed Rules.

### Phase 26: Production Correctness + Canonical Timeline

Multi-PR roadmap fixing 4 confirmed production defects from Job #8, enforcing ADR 0020 canonical timeline, and introducing pre-VD asset qualification. Version stays 2.3.0 until PR 12 (release gate). See `docs/plans/2026-06-15-phase26-production-correctness-asset-qualification.md`.

#### Face Detection — MediaPipe Tasks API Migration (PR 9)
- **Changed:** `core/face_adapter.py` migrated from the legacy `mediapipe.solutions.face_detection` API (removed in `mediapipe>=0.11`, which pinned `protobuf<5`) to the modern **Tasks API** (`mediapipe.tasks.python.vision.face_detector`). Works with current mediapipe (protobuf 7.x / numpy 2.x) — drops the `<0.11` version cap.
- **Added:** the BlazeFace short-range model is downloaded once + cached under `data/models/face_detection/` (on first face-detection call only).
- **Fixed:** the adapter now **degrades gracefully** (logs once, returns empty `model="face_detection_unavailable"`) when mediapipe is absent or the model can't be fetched — instead of raising `ModuleNotFoundError` per frame, which was half of the job_12 log storm.
- **Changed (deps):** `mediapipe` added to `requirements.txt`; opencv standardized on `opencv-contrib-python` (mediapipe hard-requires it) — removed the conflicting `opencv-python-headless`; also pinned `Flask-WTF`/`WTForms` and removed the self-referential `clipper-agency @ file://` line.
- Tests rewritten to a Tasks-API mock layer (no real mediapipe needed); 45 face/layout tests pass.

#### Batch 0 (PR #50) — Job #8 Golden Regression Fixture
- 6 frozen JSON artifacts from Job #8 in `tests/fixtures/job8/` (vd_output, composer_output, visual_coverage, manifest, narrative_structure, voice_producer_output).
- 16 characterization tests in `tests/test_job8_regression.py` documenting 4 confirmed bugs (rejected candidates rendered, absurd durations, fade_to_black at start, missing reviewer artifact).
- ADR 0026 — Contract Enforcement Over Rebuild.

#### PR 1 (#51) — Production Correctness Hotfix
- **Fixed:** rejected candidates no longer rendered — `_apply_best_candidate()` now replaces plan action with fallback text card when all candidates are rejected (was: original LLM action stayed).
- **Fixed:** `fade_to_black` now fades at end of clip — template uses `{fade_out_start}` = `duration - 0.5` (was: `{start_time}` defaulting to `0.0`, fading at clip start).
- **Fixed:** reviewer output now persisted to artifact workspace via `_persist_agent_output()` in both first-pass and repair cycle paths (was: `_run_reviewer()` returned dict, never written to disk).
- **Verified:** freeze-detector threshold format is correct — `freezedetect=n=-30.0:d=0.1` is valid FFmpeg syntax.

#### PR 2 (#52) — Canonical Beat Timeline Enforcement
- ADR 0020 canonical timeline now enforced (was "Proposed" since Phase 18).
- New `core/beat_timeline.py` — `build_canonical_timeline(narrative_structure, timestamps)` produces single source of truth for beat durations.
- Visual Director and Composer now read orchestrator-built timeline instead of independently deriving durations (eliminates fragile string-matching in VD and divergent word_range logic in Composer).
- `BeatTimelineEntry` model added to `config/schema.py`.
- Engine builds timeline after Voice Producer, passes to VD + Composer + Reviewer in all 3 call paths (first-pass, repair, retry).
- **Codex P2 fix:** unsupported `BeatFallback.type` values (e.g. `ken_burns_photo`) now normalized to `text_card` before action assignment — prevents `source: none` scenes.
- AGENTS.md: Codex review gate added to git workflow (must wait for + resolve Codex review before merge).

#### PR 3 — Deterministic Gate Failure → Repair Integration
- **Fixed:** deterministic gate failures (visual_coverage, text_collision, safe_area, package_consistency, timestamp_semantic) now engage the repair loop instead of silently blocking the job (was: hard-failed reviewer had no `repair_plan`, so `_handle_repair_plan` returned None and the job was stuck with `publication=blocked, quality=failed`).
- New `build_gate_failure_repair_plan()` in `core/repair_router.py` — maps gate failure reasons to repair patches routed to the correct agent (VD for visual/text/safe-area/timestamp issues, segment_producer for package consistency).
- Engine `_retry_review_and_package` now falls back to `build_gate_failure_repair_plan` when `_handle_repair_plan` returns None.
- **Codex P2 #1 fix:** segment_producer repair now reruns the full SP→SW→VP→VD→Composer cascade (was: only reset state without regenerating, so cached outputs were reused → same failure). New `_rerun_upstream_cascade()` helper in engine.
- **Codex P2 #2 fix:** multi-gate sequential repair now works — after each repair cycle review, if a different deterministic gate fails, `build_gate_failure_repair_plan` is tried before falling back to manual review (was: only LLM repair_plan checked → different gate failure went to manual review).

#### Post-PR #3 SonarCloud Fixes — Engine Refactor
- **Fixed cognitive complexity (rule: brain-overload):** extracted VD/Composer cached-upstream repair branch from `_execute_single_repair_cycle` (complexity 17 > 15) into new `_run_cached_upstream_repair()` helper method.
- **Removed dead code (rule: cweunused):** `_rerun_upstream_cascade` now returns a 5-tuple (was 6-tuple with unused `visual_output` — VD output is consumed internally by Composer during the cascade, never referenced by the caller or Reviewer per ADR 0020 §4 contracts).
- **Codex P2 fix:** bundled 8+ scalar repair params into `RepairCycleContext` dataclass (was: `_run_cached_upstream_repair` and `_rerun_upstream_cascade` took 7-8 individual scalar params, violating AGENTS.md ">5 scalar params = bundle" rule).
- **AGENTS.md:** strengthened SonarCloud merge gate — Quality Gate passing is necessary but NOT sufficient; PR must also show zero new issues before merge.
- Pure refactor — 1945 tests pass, no behavior change.

#### Repo Hygiene (PR #55) — Untrack .codegraph
- Removed `.codegraph/` from git tracking (was: only `.codegraph/.gitignore` tracked, rest of folder ignored locally).
- Added `.codegraph/` to root `.gitignore`. Local Codegraph MCP data unaffected.

#### PR 4 — Segment Producer Precision Upgrade
- **Fixed:** global `asset_candidates` are now distributed to `story_beats[].asset_candidates` via keyword matching (was: SP produced 31 global candidates but VD only reads per-beat candidates → VD had nothing to inspect when LLM didn't populate per-beat candidates → fell back to text_cards).
- New `_distribute_candidates_to_beats()` — post-hoc distribution using keyword overlap from `visual_must_show + caption_keywords + spoken_point`. Skips beats that already have LLM-provided candidates. Sets `related_beat_id` on distributed candidates.
- New `_extract_beat_keywords()` and `_score_candidate_for_beat()` helpers.
- **Added:** provider attempt history tracking — `_discover_multi_source_assets()` now returns `(sources, attempts)` tuple; attempts persisted as `agents/segment_producer/normalized/provider_attempts.json` artifact.
- 24 new tests in `tests/test_segment_producer_precision.py`.
- Step 5 (Pre-VD Qualification Boundary) deferred — investigation found VD already qualifies per-beat via `_do_inspect_and_select`; Step 4's distribution fix removes the root cause that made Step 5 seem necessary.

#### PR 4 (remaining) — SP Precision + Persistence Completeness
- **Fixed (4e):** `_distribute_candidates_to_beats()` now MERGES global candidates into beats with existing LLM candidates (was: skipped them → no-op when LLM populated candidates, all global candidates ignored).
- **Fixed (4e):** `_merge_candidates()` now INTERLEAVES existing + new candidates (was: append-then-slice → no-op when beat already full at `max_per_beat`).
- **Fixed (4e):** Distribution score persisted on each candidate as `distribution_score` for debugging (was: score calculated but discarded).
- **Fixed (4e):** Min score threshold (`0.1`) filters out noise candidates (was: any `>0.0` match accepted).
- **Fixed (4e):** URL-based dedup when merging LLM + global candidates (was: potential duplicates).
- **Fixed (4a):** `_parse_synthesis_response()` now extracts `entities` and `risk_flags` from LLM output (was: silently dropped even if LLM returned them).
- **Fixed (4a):** `_synthesize_research()` now propagates `entities` and `risk_flags` to `execute()` (was: stripped at synthesis boundary, Codex P1 fix).
- **Fixed (4a):** `_extract_beat_keywords()` now filters Indonesian + English stop words (was: only filtered words <3 chars, leaving noise like "yang", "the", "di").
- **Fixed (4b):** `_build_search_queries()` now generates per-beat queries from `visual_must_show` + `spoken_point` when beats are available (was: topic-level only, missed specific beat context).
- **Fixed (4b):** `execute()` now passes `beats=` to `_discover_multi_source_assets()` so per-beat queries run in production (was: param existed but call site omitted it, Codex P2 fix).
- **Fixed (4f-SP):** `entities.json` and `risk_flags.json` artifacts now persist actual LLM-extracted values (was: hardcoded `{}` and `[]`).
- **Fixed (4f-SP):** SP output `result["risk_flags"]` now passes synthesis values (was: hardcoded `[]`). `result["entities"]` added (was: missing entirely — CodeReviewer catch).
- **Refactored (SonarCloud):** Extracted `_per_beat_queries()`, `_entity_list_queries()` from `_build_search_queries()` (cognitive complexity 22→<10).
- **Refactored (SonarCloud):** Extracted `_score_and_filter_candidates()`, `_merge_candidates()` from `_distribute_candidates_to_beats()` (cognitive complexity 21→<10).
- **Fixed (Codex P2):** `entities` parameter type changed from `dict` to `list` across `_build_search_queries()` + `_discover_multi_source_assets()` to match parser output shape (was: type mismatch caused entities to be silently ignored).
- **Updated:** `segment_producer.md` prompt now requests structured `entities[]` and `risk_flags[]` fields.
- 20 new tests in `tests/test_segment_producer_precision.py` (44 total).

#### PR 4 (4f artifact correctness) — Reviewer checks + inspection cache keying
- **Fixed (4f-Reviewer):** the 4 programmatic checks (`av_sync`, `caption_quality`, `fact_safety`, `narrative_structure`) are now persisted in `programmatic_checks` even when a deterministic gate hard-fails before the LLM review runs (was: 6 early-return `_fail_if_*` paths returned `programmatic_checks: {}`, discarding the already-computed checks). `execute()` now injects `checks` into whichever fail dict it returns.
- **Fixed (4f-VD):** the inspection cache is now keyed by candidate content identity via new `compute_asset_content_hash()` (`type`/`url`/`source_type`), passed as `asset_hash` in `compute_cache_key` (was: `asset_hash=""`, so the cache keyed only on URL+claim and was reused unchanged across reruns — Job #8 rerun on Jun 15 reused Jun 10/11 decisions, and `candidate_frames/` stayed empty because cache hits skipped frame extraction). SP-regenerated candidates now invalidate stale entries → fresh inspection → frames extracted; identical candidates (e.g. resumed runs) still hit the cache.
- **Confirmed (4d):** source-tier escalation stays deferred — `_discover_multi_source_assets()` already queries every provider additively (YouTube always; Tavily/Brave when keys exist) and unions results, so there is no tier-1→tier-2 path to build. `SOURCE_QUALITY_TIERS` is a ranking score, not an execution tier. Job #8 root cause was candidate rejection (7/8), not provider failure/scarcity.
- Type-honesty fix: `_fail_if_package_consistency_failed` `main_entities` param widened to `list[str] | None` (matches `main_entities or []` body + `list[str] | None` call site).
- 10 new tests (`tests/test_agents_reviewer.py` + `tests/test_inspection_cache.py`); 1 cache test updated to the new content-hashed key.

#### PR 5 — Pre-VD Asset Qualification Boundary + Source Recovery
- **Added:** new `core/asset_qualification.py` module scores image candidates per beat BEFORE the Visual Director consumes them — the real Job #8 fix. Root cause was candidate REJECTION (VD rejected ~7 of 8 candidates → text cards), not scarcity.
- **Added:** engine seam `_apply_asset_qualification()` in `Orchestrator._run_visual_director_phase` (design §6) — qualifies each beat, IMMUTABLY rewrites `beat.asset_candidates` to the qualified set only (rejected candidates never reach VD's live per-beat surface), applies defense-in-depth filtering on the flat candidate pool, and writes a `qualification_report.json` artifact documenting verdicts (`qualified`/`recovered`/`exhausted_text_card`) + `recovery_outcome` + `reject_reasons`.
- **Added:** RECOVER stage runs before the text-card fallback — when a beat has zero qualified candidates, Segment Producer discovery is re-run for fresh candidates and re-scored (`MAX_RECOVERY_CYCLES=1`, bounded — no loop) instead of immediately degrading to a text card.
- **Added:** SLICE 1 cache-key parity hard gate — `asset_qualification._score_candidate` and `VD._score_one_candidate` compute byte-identical cache keys, so VD's re-inspection of a pre-qualified candidate is a cache hit → 0 double-VLM spend.
- **Added:** SLICE 12 HARD merge gate proves M<N (recovery strictly reduces text-card fallbacks vs the all-reject baseline) on the real frozen Job #8 research contract.
- **Changed:** Visual Director phase now receives pre-qualified candidates; recovery-before-text-card ordering is enforced at the qualification boundary.
- ADR 0026 — Contract Enforcement Over Rebuild (pure orchestration: NO new agent, NO new gate, NO schema change, NO state-machine change).
- ADR 0027 — Asset-Qualification Inspection Delegation (cache-miss inspection delegates to VD's own bound `_run_multimodal_inspection` → byte-identical cached output, no cache-namespace drift, frame ownership stays in VD).
- 2031 offline tests pass, 18 deselected; ruff clean; 93%+ coverage. Existing 69 VD tests pass UNMODIFIED (VD source untouched — blast-radius contained).
- Version stays 2.3.0 (PR 12 owns the 2.4.0 bump).

#### PR 6 — Source Transcript & Clip-Window Selector (Minimal, Contract-First)
- **Added:** new `core/clip_window.py` module — frozen `ClipWindow` dataclass + pluggable `WindowSelector` Protocol + `KeywordOverlapWindowSelector` (PR 6 v1 default, conservative: returns the full-clip window `ClipWindow(0.0, None)` for every candidate because keyword overlap cannot localize a spoken point to a timestamp). Contract-first: the data-flow shape is frozen now, the localizing backend is deferred.
- **Added:** `AssetCandidate` (`config/schema.py`) gained optional `source_start_sec: float = 0.0` and `source_end_sec: float | None = None`. Additive — defaults preserve today's from-zero trim. Excluded from the inspection content hash, so PR 5's cache-key parity holds (no VLM double-spend).
- **Added:** end-to-end propagation — qualification seam (`Orchestrator._apply_asset_qualification` invokes the selector + attaches the window to kept candidates) → Visual Director (`_attach_candidate_windows` re-attaches by `source_url`; `_exec_tiktok_clip` carries it into the asset dict) → Composer (`_smart_trim` clamps the window to source bounds — degenerate ⇒ full clip — and `_trim_long_clip`/`_stretch_short_clip` emit `-ss <start>`).
- **Deferred (post-v2.4.0):** the transcript/whisper backend (faster-whisper behind a config flag), yt-dlp auto-caption extraction, and keyframe-precise snapping. Blocked by ADR 0026 (do-not-rebuild), the GPU-forbidden constraint, no existing transcript infra, and the fact that the v2.4.0 release gate does NOT require clip-windowing. The "trimmed segment matches beat's spoken point" verification criterion waits for this backend (documented honestly).
- ADR 0026 — Contract Enforcement Over Rebuild (pure orchestration: NO new agent, NO new gate, NO state-machine change).
- 2054 offline tests pass, 18 deselected; ruff clean; 93%+ coverage. Version stays 2.3.0 (PR 12 owns the 2.4.0 bump).

#### PR 7 — Model Resolution Correctness (Slug + Cache + Startup Preflight)
- **Fixed:** the `budget_east` preset (`config/hierarchy.py`) used bare slugs — `mimo-v2-flash`, `glm-4.7-flash`, `qwen3-32b`, `gemini-2.5-flash`. OpenRouter requires canonical `vendor/model` slugs; bare slugs 404 with "No endpoints found" (job_9 root cause, surfacing mid-pipeline after paid research). Corrected to `xiaomi/mimo-v2.5` (segment_producer + visual_director — also the migration target for the removed `xiaomi/mimo-v2-flash`, job_11 root cause), `z-ai/glm-4.7-flash`, `qwen/qwen3-32b`, `google/gemini-2.5-flash`. Live-verified against the OpenRouter catalog (340 models) via the new preflight.
- **Fixed:** `model_cache._load_cache()` only refreshed when the cache file was MISSING — the 7-day `_TTL_SECONDS` check was effectively dead code, so a present-but-stale cache (with removed/deprecated models) was never refreshed. Now staleness triggers a `force=True` refresh; `refresh_model_cache` swallows network errors so this degrades to the stale cache offline.
- **Fixed (Codex P2#2):** `refresh_model_cache` now dedupes refresh attempts within a 30s window (even when forced), so an offline `run --dry-run` can't stack several 30s `/models` timeouts across cache reads before degrading.
- **Added:** `model_cache.list_catalog_models()` public helper returning the cached `{model_id: metadata}` catalog (empty when unavailable).
- **Added:** startup preflight `config/preflight.py` → `preflight_agent_models()` — force-refreshes the cache, resolves every LLM-backed agent's model via `get_agent_config`, and validates each slug is a key in the live catalog. Fails fast (clear `RuntimeError` → failed status / exit 1) on a populated-catalog miss BEFORE billing research credits; degrades to a warning when no catalog is reachable. Resolves the job_9/job_11 class of mid-pipeline 404s.
- **Fixed (Codex P2#1):** preflight runs at the `Orchestrator.run_pipeline` / `run_pipeline_from` chokepoint (single source of truth covering CLI, dashboard create, retry, AND resume) plus `__main__.py` dry-run — previously only the CLI `run` command was guarded, so dashboard/retry/resume users could still hit a mid-pipeline 404 from a bad `*_MODEL` override.
- **Removed:** dead `llm/router.py` (`ModelPreset`/`PRESET_MODELS`/`resolve_model`, 0 production consumers — only its own test imported it) and `tests/test_llm_router.py`. It carried the same bare-slug mistake. `llm/__init__.py` pruned to export only `OpenRouterClient`.
- **Changed:** `.env.example` per-agent model section now shows canonical slugs + adds the previously-missing `VISUAL_DIRECTOR_MODEL`. `.env` (personal/gitignored) left untouched.
- ADR 0026 — Contract Enforcement Over Rebuild (pure fixes: NO new agent, NO new gate, NO schema change, no new heavy dependency).
- Offline suite green, ruff clean, ≥93% coverage. Version stays 2.3.0 (PR 12 owns the 2.4.0 bump).

#### PR 8 — Asset-Qualification Cost Optimization (job_11 storm fix)
- **Context:** the PR 5 qualification boundary had NO cheap filter before the VLM — `candidate_semantic_ranker` is post-VLM arithmetic and `asset_qualification._score_candidate` IS the VLM (cache-key parity proves it). job_11 spent ~9,078 FFmpeg frame extractions + thousands of Gemini VLM calls, ~all `claim_support=0.00`. Three additive knobs cut the cost without changing the qualification contract.
- **Added (option 1 — pre-VLM skip gate):** `asset_qualification._score_candidate` now computes `KeywordOverlapWindowSelector().relevance_score(candidate.model_dump(), beat)` on a cache MISS and returns `None` WITHOUT calling the VLM when overlap ≤ `_PREFILTER_MIN_OVERLAP` (default **0.0** — skips only literally-zero-overlap candidates, minimal recall risk). Cached candidates are never re-decided (the gate sits between the cache lookup and `_run_inspection`). Reuses PR 6's pure string-overlap scorer — no new heavy dep.
- **Added (option 2 — frame multiplier):** `AppSettings.frame_inspection_max_frames` (default **48**, was 120) + `frame_inspection_interval_sec` (default **1.0**, was 0.5) — threaded into Visual Director's `run_frame_inspection_pipeline` call (~7.5× fewer VLM-bound frames). Tunable via env; validated `ge=1` / `gt=0` so a bad deployment value fails fast instead of hanging `frame_sampler` (Codex P2#2).
- **Added (option 9 — RECOVER cap):** `_qualify_beat` ranks recovered candidates by keyword-overlap relevance to the failing beat, then slices to `MAX_RECOVERED_PER_BEAT` (default **8**) before scoring — so one all-reject beat can't flood N fresh VLM inspections AND the most relevant recovered candidate isn't lost to provider ordering (Codex P2#1).
- ADR 0026 / 0027 compliant (pure-python keyword-overlap reuse; no torch/embeddings; no new gate; qualification contract unchanged).
- Offline suite green, ruff clean, ≥93% coverage. Version stays 2.3.0 (PR 12 owns the 2.4.0 bump).

#### PR 10 — ffmpeg_runner DEBUG-log quieting
- **Fixed:** `ffmpeg_runner` no longer logs raw FFmpeg `stderr` line-by-line at DEBUG. The job_12 debug log was a 536k-line flood of one `log.debug` per stderr line, swamping logs and obscuring real signal. The runner now emits a one-line summary per invocation and writes the full captured stderr to the tail buffer, surfaced only on failure (tail-on-failure). Extraction/encode behavior is unchanged — only the DEBUG logging volume is reduced.

### Phase 25: Dead Code Removal (PR #49)

Removed superseded `core/multimodal_provider.py` — 0 production consumers, deliberately excluded from wiring in Phase 23 plan (`multimodal_client.py` serves the same purpose and is wired into Visual Director). Eliminated 0.1% code duplication.

- Deleted `core/multimodal_provider.py` + `tests/test_multimodal_provider.py`.
- Removed import smoke-test from `test_phase23_wiring_verification.py`.
- Fixed 3 stale doc references (SRS FR-62, technical_design §rendering, README core/ listing).
- Repo hygiene: untracked `.codegraph/daemon.pid` + `.coverage`, added nested `.codegraph/.gitignore`.
- ADR 0025 — Drop Multimodal Provider Abstraction (defer until 2nd concrete provider exists).

### Phase 24: Composer Probe Blocker Fix (PR #48)

Fixed SonarCloud Reliability E Blocker (python:S930) in `composer.py:157` — `_run_empty_frame_detection` called `probe_video(video_path)` missing `allowed_base_dir` argument + treated `VideoInfo` dataclass as dict via `info.get("format", {})`. Bug masked by `_safe_detect_empty` swallowing exceptions.

- `probe_video()` now called with `allowed_base_dir=str(Path(video_path).parent)`.
- `VideoInfo` fields accessed via attributes (`info.duration`), not dict `.get()`.
- Reliability rating: E → A (0 blockers on new code).

## [2.3.0] — 2026-06-11

### Phase 23: Wire Unwired Modules Into Production Pipeline

All 17 core modules from Phases 21 & 22 that were built but never called from production are now wired into actual agent runtime call sites. Every module is config-gated (disabled → backward compat, no-op). No new modules. No new agents.

#### Wired Modules (17)

**Visual Director — Pre-Render Inspection (6):**
- `run_frame_inspection_pipeline` — keyframe extraction before VLM candidate inspection, frame paths fed to `MultimodalInspectionClient.inspect_asset()`.
- `PaddleOCRAdapter` — OCR text detection on extracted keyframes, OCR regions passed to VLM.
- `MediaPipeFaceDetector` — face region detection on keyframes.
- `score_source_cleanliness` — cleanliness scoring fed into candidate ranking via `candidate_semantic_ranker`.
- `candidate_inspection_dir` from `inspection_paths` — persisted inspection artifacts.
- `frame_sampler`, `frame_extractor`, `frame_hash` — pipeline support modules wired.

**Composer — Post-Render Diagnostics (4):**
- `detect_empty_segments` — replaces hardcoded `empty_segments=[]` with actual frame variance analysis.
- `build_generated_text_regions` — persists subtitle/headline/overlay bounding boxes for Reviewer collision checks.
- `build_rendered_scene_manifest` — builds scene-beat-timing manifest (Reviewer receives non-None).
- `final_layout_inspection` — post-render layout validation wired.

**Reviewer — Actual Detection Calls (2):**
- `detect_text_collisions` + `detect_source_text_density` — Reviewer now calls actual detection functions instead of checking empty dicts. Text collision data built by `_populate_actual_detection_diagnostics()`.
- `detect_safe_area_issues` — actual safe zone region checks replacing null-dict gate.

**Observability — All 7 Agents (1):**
- `LLMTraceWriter` — engine creates singleton trace writer gated by `observability.llm_traces.enabled`. All 7 agents accept `trace_writer` kwarg and call `chat_traced()` when available.

**Cross-Cutting (3):**
- `text_detection`, `source_cleanliness`, `multimodal_provider` — import chains verified.
- `generated_text_manifest`, `rendered_scene_manifest` — manifest contracts verified.
- `llm_trace` + `chat_traced()` — all agents wired.

#### Reviewer Context Contract (Batch 0)
- `_retry_review_and_package()` and repair rerun `_run_reviewer()` pass `story_beats`, `word_timestamps`, `rendered_scene_manifest`, and `diagnostics` from Composer output.
- `RenderedSceneManifest` serialized before reviewer consumption.
- Gate chain: `visual_coverage → text_collision → safe_area → package_consistency → timestamp_semantic → semantic_review → LLM`.

#### Config-Driven Gating
- `quality.runtime_inspection.enabled` — gates frame extraction, OCR, face detection, cleanliness.
- `quality.ocr.enabled` / `quality.face_detection.enabled` — per-feature gates.
- `quality.text_collision` / `quality.safe_area` — Reviewer detection gates.
- `observability.llm_traces.enabled` — trace writer gate.
- All disabled by default → backward compatible. All failures caught + logged, not fatal.

#### Codex + Bug Fixes
- P1 — `_build_scene_manifest()` serializes `RenderedSceneManifest` via `.model_dump()`.
- P1 — engine forwards `compose_output["diagnostics"]` to Reviewer in both paths.
- OCR adapter deprecated API fix + LLM trace wiring in all 7 agents.

#### Tests
- **53 new** E2E wiring verification tests in `tests/test_phase23_wiring_verification.py`.
- Full offline suite: **1890 passed**, 18 deselected (up from 1837).
- Coverage: 92%.

#### Documentation
- PRD v3.3, SRS v3.3, technical_design v5.3, requirements_traceability v4.3.
- ADR 0024 — Reviewer Context and Diagnostics Enforcement Contract.
- Implementation plan: `docs/plans/2026-06-10-phase23-wire-unwired-modules.md`.

## [2.2.0] — 2026-06-11

### Phase 23: Reviewer Context + Diagnostics Enforcement Contract

Reviewer deterministic gates now receive the Composer diagnostics and rendered scene manifest produced by the engine. This closes the runtime enforcement gap where visual coverage, text collision, safe-area, package consistency, and timestamp-level semantic review could skip evidence in production pipeline runs.

#### Reviewer Context Contract
- `_retry_review_and_package()` and the repair rerun `_run_reviewer()` call site pass `story_beats`, `word_timestamps`, `rendered_scene_manifest`, and `diagnostics` from Composer output.
- `RenderedSceneManifest` is serialized before reviewer consumption so gate code can safely read `rendered_scene_manifest.get("entries")`.
- Reviewer gate chain now enforces `visual_coverage → text_collision → safe_area → package_consistency → timestamp_semantic → semantic_review → LLM`.

#### Bug Fixes (Codex Review)
- P1 — `_build_scene_manifest()` serializes `RenderedSceneManifest` via `.model_dump()` before `.get("entries")`.
- P1 — engine forwards `compose_output["diagnostics"]` to Reviewer in both normal and repair rerun paths.

#### Tests
- Reviewer + engine regression tests: 125 passed.
- Offline suite: 1837 passed, 18 deselected.

#### Documentation
- PRD v3.3, SRS v3.3, technical_design v5.3, requirements_traceability v4.3.
- ADR 0024 — Reviewer Context and Diagnostics Enforcement Contract.

## [2.1.0] — 2026-06-09

### Phase 21: Deterministic Quality Gates + Repair Routing

Deterministic visual quality gates, package consistency, semantic visual relevance, evidence contracts, and structured repair routing — addressing all 4 Job #4 output issue categories (black/freeze frames, text collisions, package-scope mismatches, claim-to-visual irrelevance).

#### New Modules (10)

- **`core/visual_coverage.py`** — `evaluate_visual_coverage()` scores frame-level completeness via sampled thumbnails. Detects black/freeze frames, blank regions, insufficient visual content.
- **`core/frame_sampler.py`** — `plan_frame_samples()` + `deduplicate_samples_by_hash()` produce deterministic sampling schedules for coverage analysis.
- **`core/text_detection.py`** — `normalize_text_region()` standardizes OCR bounding boxes for consistent collision checks.
- **`core/text_collision.py`** — `detect_text_collisions()` identifies overlapping text bounding boxes from captions, overlays, and source clip text. `detect_source_text_density()` flags dense on-screen text.
- **`core/safe_area.py`** — `detect_safe_area_issues()` validates caption/overlay placement against TikTok safe zones with face overlap detection.
- **`core/story_mode.py`** — `classify_story_mode()` deterministically determines narrative structure (single_deep_dive, three_roundup, two_highlight) and validates consistency with actual composition.
- **`core/duration_budget.py`** — `allocate_duration_budget()` distributes total video duration across beats by role weight (hook, main_claim, evidence, reaction, closing_cta).
- **`core/package_consistency.py`** — `evaluate_package_consistency()` validates story mode, scene count, clip types, and visual hierarchy match declared format_decision.
- **`core/semantic_visual_review.py`** — `score_visual_relevance()` scores claim-to-visual alignment using keyword overlap and evidence contracts on StoryBeat.
- **`core/repair_router.py`** — `route_repair()` + `build_repair_plan()` map quality gate failures to the correct existing agent: visual_coverage→Composer, text_collision/safe_area→Visual Director, consistency/relevance→Segment Producer.

#### Reviewer Gate Chain

```
visual_coverage → text_collision → safe_area → package_consistency → semantic_review → LLM
```

Sequential deterministic gate chain before LLM multimodal review. Each gate owns a specific quality dimension. Evidence contracts on StoryBeat verify claim-to-visual alignment. Composer emits structured visual quality diagnostics.

#### Repair Routing

- Engine `_handle_repair_plan()` routes repair plans to correct agent via repair_router.
- Repair patches preserve beat window (`timestamp_start_sec`, `timestamp_end_sec`) and replacement visual intent (`required_visual`).
- Pipeline returns `"awaiting_repair"` instead of packaging when repair is needed.
- Codex review: 3 issues (2 P1, 1 P2) — all resolved in follow-up commit.

#### Config & Schema

- Quality gate configuration defaults in niche YAML.
- `RepairPatch`, `RepairPlan` models in `config/schema.py`.
- Evidence contract fields on StoryBeat model.

#### Bug Fixes (SonarCloud + Codex)

- S3776 CRITICAL — extracted `_check_zone_overlaps()` / `_check_face_overlaps()` from safe_area.py (→ cognitive complexity ~4).
- S107 — bundled 8 `execute()` params into `ReviewContext` TypedDict.
- S1172×3 — prefixed unused params with `_` in package_consistency.py.
- S5852 — replaced ReDoS regex with string-based split in story_mode.py.
- Codex P1 — repair routing wired into pipeline (was dead code).
- Codex P1 — reject severity caught alongside hard_fail in gate filters.
- Codex P2 — repair patch timing/visual fields preserved in construction.

#### Tests

- 1170 → 1222 total tests (+52 new).
- New test files: `test_visual_coverage` (325), `test_frame_sampler` (51), `test_text_detection` (62), `test_text_collision` (106), `test_safe_area` (136), `test_story_mode` (89), `test_duration_budget` (72), `test_package_consistency` (83), `test_semantic_visual_review` (30), `test_repair_router` (35), `test_job4_quality_regression` (145).
- All 1210+ offline tests pass + 12 new post-merge Codex fix tests.

#### Documentation

- PRD v3.1 (PR-30), SRS v3.1 (FR-43–FR-50), technical_design v5.1 (§13), requirements_traceability v4.1 (facts #154–166).
- ADR 0023 — Job4 Quality Gates and Repair Routing.

### Phase 20: Job #4 Quality Fixes

Scoped quality improvements from Job #4 output analysis — addressing config aliases, intro card contract, and introducing regression test fixture for 6 defect types.

#### Changes

- **Config aliases** — shortcut env var names for common settings, improved `.env.example`.
- **Intro card contract** — structured metadata for opening card image generation.
- **SonarCloud fixes** — S3776 (cognitive complexity), S1172 (unused param), S107 (too many params) in engine.py.
- **Job #4 regression fixture** — `test_job4_quality_regression.py` covers 6 defect types as failing baseline for Phase 21.

## [2.0.0] — 2026-06-07

### Audio-First Continuous Voiceover Architecture (v2.0.0)

Complete architecture overhaul from per-scene sequential processing to audio-first continuous voiceover pipeline. Single TTS call (87.5% cost reduction), beat-driven Visual Director, sequential voice→visual execution.

#### Architectural Changes

- **Segment Producer** — Researcher renamed with 5 sub-roles: Fact Checker, Viral Analyst, Clip Scout, Story Producer, Edit Planner. Outputs edit blueprint with story_beats (visual_must_show/must_not_show, asset_candidates, overlay_text, caption_keywords), format_decision, verified_facts, unverified_claims, do_not_use list.
- **Continuous Voiceover** — Single TTS call replaces 8 per-scene calls (87.5% cost reduction). ElevenLabs `/with-timestamps` returns character-level word timestamps. Fallback: Gemini TTS (silence detection) → Fish Audio → fail clearly.
- **Sequential Voice→Visual** — Voice Producer must complete before Visual Director starts. Removed parallel `asyncio.gather` from engine.
- **Beat-Driven Visual Director** — Consumes story_beats + word timestamps + visual rules (must_show/must_not_show). Each beat has exact audio duration from timestamps.
- **Smart Scene Trimming** — ffprobe keyframe boundary detection (±15% tolerance), speed adjustment ±20%.
- **Keyword Captions** — Max 6 words, beat-aligned, bottom-positioned. Replace full-sentence subtitles.
- **Reviewer Enhancement** — 4 programmatic quality checks: (1) AV sync (drift < 0.5s), (2) caption quality (max 6 words), (3) fact safety (safe wording for unverified claims), (4) narrative structure (beat completeness).

#### Shared Schema Contract

- 11 Pydantic models in `config/schema.py`: StoryBeat, FormatDecision, VerifiedFact, UnverifiedClaim, VisualInstruction, AssetCandidate, KeywordCaption, VoiceSettings, VoiceProviderResult, ContentBrief, NarrativeSection.

#### Agent Changes

- **Segment Producer** — renamed from researcher.py; outputs edit blueprint with beat-level visual instructions.
- **Scriptwriter** — continuous voiceover narration (75-110 words, no emojis, spoken-word style). Outputs narrative_structure mapping beats to word ranges.
- **Voice Producer** — single TTS call with word-level timestamps via ElevenLabs `/with-timestamps`.
- **Visual Director** — beat-driven planning from story_beats + timestamps + visual rules.
- **Composer** — single audio timeline (voiceover.mp3 immutable anchor), smart trimming, keyword captions.
- **Reviewer** — 4 programmatic checks + multimodal. Timeline reconciler removed from engine.
- All backward-compat files removed (researcher.py, researcher.md, 2 test wrappers).

#### Tests

- 990 → 1170 tests (+180 new, -7 dead, net +173).
- 93%+ line coverage maintained.

#### Documentation

- PRD v3.0, SRS v3.0, technical_design v5.0, requirements_traceability v4.0.
- ADR 0021 — Audio-First Continuous Voiceover.
- All prompt files: segment_producer.md (renamed, rewritten), scriptwriter.md (rewritten for voiceover).

## [1.3.0] — 2026-06-06

### Tier 4: Timeline-Aware Agent Orchestration

Canonical timeline contract ensuring cross-agent timing consistency — resolving audio/video sync drift, missing subtitles, and retry path data loss discovered during job 2 retest.

#### New Modules (3)

- **`orchestrator/validator.py`** — Format validator for Researcher's `content_direction`. Validates format against allowed set, coerces/clamps story counts, falls back to `ContentPlanningConfig` defaults.
- **`orchestrator/duration_gate.py`** — Script duration budget checker. Estimates scene duration from word count × WPS rate, fails fast when over configurable hard limit.
- **`orchestrator/timeline.py`** — Timeline reconciler. Merges script scenes + ffprobe audio metadata into canonical timeline with cumulative start/end times, duration fallback, and hard-limit enforcement.

#### Config & Schema

- **`ContentPlanningConfig`** pydantic model — `default_format`, `max_stories_per_video`, `target_duration_sec`, `hard_limit_sec`, `estimated_words_per_second`.
- Niche YAML defaults for Indonesian artists.

#### Agent Changes

- **Researcher** — Emits `content_direction` (format, story selection) from existing LLM synthesis call. Zero extra LLM cost.
- **Scriptwriter** — Emits `role`, `word_count`, `estimated_duration_sec` per scene. Backward-compatible `duration` field retained.
- **Voice Producer** — Measures actual audio duration via `ffprobe`, returns `audio_metadata` list.
- **Visual Director** — Timeline-aware: uses reconciled timeline durations as source-of-truth when available.
- **Composer** — Timeline-obedient: applies timeline durations to video assets, builds audio map from timeline.

#### Pipeline Integration

- `_stage_research()` → `validate_content_direction()` after Researcher.
- `_run_content_scriptwriter()` → `check_script_duration_budget()` after Scriptwriter. Fails fast on over-budget.
- `_stage_content()` → `reconcile_timeline()` after Voice Producer. Returns 3-tuple (script, voice, timeline). Fails pipeline if over hard limit.
- `_stage_composition()` → passes timeline to Visual Director + Composer.
- `_retry_composer_stage()` → rebuilds timeline from persisted artifacts.
- `_retry_downstream_stages()` → stops on duration-gate failure, builds timeline for downstream.
- G10 duration limit now configurable via `ContentPlanningConfig.hard_limit_sec`.

#### Bug Fixes

- **Retry path missing subtitles** — `_retry_composer_stage()` now loads scriptwriter output and passes `script_scenes` kwarg.
- **Log injection (CWE-117)** — `_sanitize_for_log()` strips control characters from agent error messages before logging.

#### Tests

- 783 → 844 tests (+61 new).
- New test files: `test_content_planning_schema` (4), `test_researcher_content_direction` (3), `test_voice_producer_duration_metadata` (4), `test_format_validator` (6), `test_duration_gate` (8), `test_timeline_reconciler` (6), `test_scriptwriter_budget` (4), `test_visual_director_timeline_aware` (3), `test_composer_timeline_obedient` (5), `test_retry_timeline` (8), `test_engine_timeline_wiring` (6), `test_tier4_timeline_e2e` (2 integration).

#### Documentation

- PRD v2.9, SRS v2.9, technical_design v4.0, requirements_traceability v3.0.
- ADR 0020 — Canonical Timeline Contract (Proposed).
- Design doc: `docs/plans/2026-06-06-timeline-aware-agent-orchestration.md`.

## [1.2.0] — 2026-06-05

### Phase 19: Composer Treatment & Transition Engine

Complete overhaul of the Composer agent's video assembly pipeline — replacing broken `amix` audio mixing with per-scene audio pairing, adding xfade transition support, timed subtitle overlays, and TikTok-ready production output.

#### New Modules (4)

- **`rendering/treatment_config.py`** — Frozen dataclass YAML loader for treatment/transition definitions. `TreatmentDef` and `TransitionDef` with immutable access via `TreatmentConfig`.
- **`rendering/treatment_filters.py`** — Per-scene FFmpeg filter string builder with variable substitution (`{frames}`, `{text}`, `{duration}`, `{start_time}`) and input-type rules (image+zoompan prepend scale, post-scale/crop append setsar).
- **`rendering/audio_sequencer.py`** — Per-scene audio+video concat filter builder. Mode A (paired when no xfade), Mode B (audio-only when xfade handles video). Pads missing audio with silence.
- **`rendering/subtitle_engine.py`** — Script text to timed `CaptionOverlay` conversion with absolute timestamps. Hook overlay (first 3s). TikTok output validation (6 FFmpeg flags).

#### Composer Overhaul

- Replaced broken `amix=inputs=N` (all voices played simultaneously) with per-scene `concat` filter pairing each voice file with its scene.
- Added xfade/concat mixed transition chain with offset calculation (`cumulative_duration - trans_duration - safety_margin`), duration clamping, and fallback to crossfade for unknown transitions.
- Integrated treatment filter chains into assembly — treatment filters prepended before trim when present.
- Added timed subtitle drawtext overlays from scriptwriter text, chained with `enable='between(t,start,end)'` and `escape_drawtext()`.
- Threaded `script_scenes` from orchestrator through Composer pipeline.
- Added production output flags: `-pix_fmt yuv420p`, `-movflags +faststart`.
- Removed dead `_build_filter()` code (broken amix pattern, zero callers).

#### Tests

- 699 → 783 tests (+84 new, -7 dead removed, net +77).
- 93%+ line coverage maintained.
- New test classes: `TestComposerTreatmentFilters` (5), `TestComposerTransitions` (8), `TestComposerAudioSequencer` (6), `TestComposerSubtitles` (5), `TestComposerUnifiedPipeline` (6), `TestComposerEdgeCases` (10), `TestTreatmentConfig` (9), `TestTreatmentFilters` (13), `TestAudioSequencer` (8), `TestSubtitleEngine` (17), expanded `TestTreatmentTemplates` (7→11).

#### Documentation

- All 6 spec docs updated (PRD v2.8, SRS v2.8, technical_design v3.9, requirements_traceability v2.9, README, AGENTS.md).
- New PR-28, FR-34/35/36, facts #123-129, edge cases E26a-E26d.
- Slow-motion treatment deferred to evolution plan (technical constraint with trim-based duration contract).

---

## [1.1.0] — 2026-06-04

### Phase 13: Retry/Resume + Cache Reuse

- CLI `job-retry <id> --from <agent>` and `job-resume <id>` for human-triggered retry from any agent.
- Dashboard POST `/jobs/<id>/retry` and `/jobs/<id>/resume` with CSRF protection.
- Job config snapshot frozen at creation; retries use same snapshot.
- `validate_agent_cache()` skips paid provider calls when valid cached artifacts exist.

### Phase 12: Artifact Contracts + Debug Observability

- Canonical job workspace paths (`ASSETS_CACHE/job_{id}/agents/{agent}/`).
- Artifact writer helpers for persisting agent input.json, output.json, gate results.
- Safety, Researcher, Scriptwriter, Voice Producer, Visual Director artifacts all persisted.
- Job manifest for full reproducibility.

### Phase 11: Logging, Model Config, ScrapeCreators Cache

- Structured logging for all agents, services, and LLM client (model, tokens, cost, latency).
- Per-agent model configuration via environment variables (`SAFETY_MODEL`, `RESEARCHER_MODEL`, etc.).
- ScrapeCreators response caching with `trim=true` + `_extract_fields()`.
- `test-agent` CLI subcommand for independent agent debugging.
- All 14 SonarCloud issues resolved (log injection, exception logging, complexity).

### Phase 10: .env Config Fix

- `pydantic-settings` `AppSettings` for typed config access.
- `load_dotenv()` called at CLI entry (`__main__.py`).
- Test isolation with `AppSettings(_env_file=None)` + `patch.dict(os.environ, clear=True)`.

### Phase 9: Docker Deployment

- Dockerfile + docker-compose.yml for VPS deployment.
- Integration smoke test for full pipeline.
- CI push trigger for master branch SonarCloud analysis.

### Phase 8: Configurable Prompts & Templates

- YAML-based prompt and template configuration.
- Configurable niche profiles, video templates, agent prompts.

### Phase 7: Web Dashboard

- Flask web dashboard with basic auth (2 groups: privileged, creative/ops).
- Job listing, agent observability, configuration editing.
- CSRF-protected POST routes.

### Phase 6: Orchestrator Engine

- Gated state machine with 10 gates (G1-G10) — pass/soft-fail/hard-fail at every transition.
- CLI interface: `python3 -m clipper_agency run --topic "..." --niche indonesian_artists`.
- 216 tests, 97% line coverage.

### Phase 5: Individual Agents

- 7 agents: Safety, Researcher, Scriptwriter, Voice Producer, Visual Director, Composer, Reviewer.
- Output Packager: `video.mp4` + `caption.txt` + `thumbnail.png` + `metadata.json`.
- Base agent class with DB state tracking.

### Phase 4: Agent Framework

- Base agent class with lifecycle management.
- Job state machine with transition validation.
- All 10 gate definitions (G1-G10).

### Phase 3: External Service Integrations

- OpenRouter LLM client with model routing.
- ElevenLabs voice generation service.
- yt-dlp media download service.
- Pexels stock media service.
- Firecrawl web search service.
- ScrapeCreators TikTok data service.

### Phase 2: Database Layer

- SQLite schema with 15 tables (WAL mode, advisory locks).
- Connection management, CRUD queries.
- Multi-tenant schema from day one.

### Phase 1: Configuration System

- Config hierarchy: Agent → Niche → Account → Job-level overrides.
- YAML-based niche and account configuration.

### Phase 0: Project Scaffolding

- Package skeleton with CLI entry point.
- Test infrastructure with conftest.
- CI/CD: GitHub Actions + SonarCloud + GitGuardian.
- Product documentation (PRD, SRS, technical design, traceability matrix).

---

## [1.1.0] — 2026-06-04

### Phase 18: Visual Director Enhancement

- Treatment metadata pipeline: Visual Director selects per-scene treatments and transitions from `templates/treatments.yaml`.
- 9 visual treatments (Ken Burns zoom/pan, cinematic crop, B-roll, slow-motion, lower-third, text card reveal, hook caption, fade-to-black) and 5 transitions (crossfade, hard_cut, wipe_left, dissolve, circle_open).
- Per-scene `target_duration` applied as `trim=duration=X` in Composer assembly.
- Rewritten Visual Director prompt with video production expertise (FPS rules, pacing, treatment selection, default routing).
- FFmpeg visual techniques research document added.

### Phase 17: Niche Wiring + Prompt Deduplication

- Niche config wired through orchestrator — `channel_description`, `safety_rules`, `search_terms` derived from YAML.
- CLI validates niche exists before pipeline start.
- Individual niche fields as prompt template variables replacing hardcoded text.
- `content_angle`, `search_terms`, `max_hashtags` added to NicheConfig schema.
- All prompt files renamed `.txt` → `.md` for editor support.
- ADR 0014 (Visual Director LLM), ADR 0015 (artifact workspace), ADR 0016 (OWASP path traversal).

### Phase 16: Visual Director LLM Planning

- LLM-driven per-scene visual planning replacing blind sequential URL assignment.
- `_compact_research_data()` strips noise, `_plan_with_llm()` creates structured plan, `_execute_plan()` dispatches via action table.
- 4 action types: `tiktok_clip`, `pexels_video`, `pexels_image`, `text_card`.
- 3-tier image fallback for text cards: Pexels photo search → Firecrawl article image → gradient background.
- `search_photos()` added to PexelsService.
- Graceful fallback to legacy sequential planning on LLM failure.

### Phase 15b: E2E Pipeline Bugfixes

- Fixed voice producer partial completion (Gemini TTS 429 backoff).
- SAR normalization in scene normalizer.
- Agent failure status checks for voice_producer, visual_director, composer.
- `_fail_agent` deduplication — extracted shared failure handler.
- Composer FFmpeg progress logging and timeout.

### Phase 15a: Template Rendering Engine

- YAML template system under `clipper_agency/rendering/` with 3 adapters (News Card, B-Roll Narration, Rapid Update).
- Typed render contracts (`contracts.py`), shared FFmpeg primitives (`primitives.py`), template-aware thumbnails (`thumbnails.py`).
- `RenderEngine` orchestrates FFmpeg filter graph from primitives + adapter output.
- Composer template routing with diagnostics.

### Phase 14: Media/Composer Correctness

- FFmpeg preflight diagnostic (ffmpeg, ffprobe, libx264, aac, mp3).
- Generated card fallback (Pillow-rendered 1080x1920 text cards).
- Deterministic video validation (G10): resolution, duration, codec, audio track check before Reviewer.
- Fixed-contract packager (S6549 safe paths).
- Repetitive failure patterns documented (`docs/repetitive-failure-patterns.md`).
