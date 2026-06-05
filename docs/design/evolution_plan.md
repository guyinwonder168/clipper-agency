# Clipper Agency — Evolution Plan

**Version:** 2.5
**Date:** 2026-06-05
**Status:** MVP Phases 0-19 Complete — Future Scope Updated After Phase 19

---

## Purpose

This document contains all future-stage details that were removed from MVP docs to keep them lean. Every item here is explicitly out of MVP scope. Referenced by `docs/PRD.md` §14.

---

## Deferred MVP+ Items (from Phase 16 Brainstorming)

These items were discussed during Phase 16 design but deferred to keep the phase focused on Visual Director LLM planning. They are near-term improvements that should happen before or during Stage 1.5.

### 1. LLM-powered Orchestrator (Future Evolution)

**Current state:** Orchestrator is sequential and deterministic — it relays data between agents without intelligence. This was a deliberate design choice validated during Phase 16 research: "use the simplest pattern that works. Don't make the orchestrator smart, make agents smart."

**Future state:** If the pipeline evolves beyond sequential execution (e.g., conditional branching, parallel agent execution, dynamic agent selection), an LLM-powered orchestrator could:
- Decide which agents to run based on topic/niche
- Route around failed agents intelligently
- Optimize pipeline cost by skipping unnecessary agents

**Trigger:** When pipeline becomes non-sequential or multi-path.

### 2. Richer text_card Rendering

**Current state:** Composer template engine supports 4 card styles (`news_card`, `speech_bubble`, `breaking_news`, `mock_ui`) with the Visual Director LLM output schema aligning to existing template variables.

**Future state:** Expand card rendering with:
- Animated card transitions (fade/slide between cards)
- Dynamic text sizing based on content length
- Branded color schemes per client/account
- Video clip overlays (engagement badges, watermarks)
- More card templates beyond the current 4

**Trigger:** When content variety demands more visual styles than current templates provide.

### 3. Researcher Smart Caching

**Current state:** Researcher runs on every pipeline invocation, even when niche and topic haven't changed since the last run. For the same topic re-run (e.g., job retry, failed pipeline resume), the research is re-fetched.

**Future state:** Skip Researcher when:
- Same niche + same/similar topic was recently researched (configurable TTL, e.g., 24h)
- Cache key: `{niche}_{topic_normalized}` → research artifacts
- Other agents (composer, scriptwriter, voice, visual director) always produce fresh results per pipeline run

**Rationale:** Researcher calls paid APIs (ScrapeCreators, Firecrawl). Caching saves cost and time when iterating on the same topic.

**Trigger:** When API costs become noticeable or job iteration frequency increases.

### 4. Slow-Motion Treatment Support

**Current state:** The `slow_motion` treatment is defined in `treatments.yaml` with `setpts=2.0*PTS` but is deferred from implementation. The Composer's trim-based duration contract (`trim=duration=X`) assumes treatments don't change playback speed. Applying slow-motion after trim has no effect; applying it before trim requires the trim value to account for the speed factor.

**Technical constraint:** Two `setpts` filters in the same chain can interfere. The pipeline already uses `setpts=PTS-STARTPTS` after trim to reset timestamps. A slow-motion `setpts=2.0*PTS` would need to be applied before trim, and the trim duration adjusted to the stretched length.

**Future state:** Cross-agent coordination to support time-stretching treatments:
- **Visual Director:** multiply `target_duration` by the slow-motion factor when selecting `slow_motion` treatment
- **Composer:** apply `setpts=N*PTS` before trim, adjust trim value to match original `target_duration` (not the stretched one)
- **Audio Sequencer / Voice Producer:** stretch audio to match the longer output duration
- Requires a new `speed_factor` field in treatment metadata (`treatments.yaml`)

**Trigger:** When slow-motion or time-stretch effects are needed for content variety.

### 5. Full Config Hierarchy — Agent → Niche → Account → Job (Level C)

**Current state:** MVP implements Level B — per-agent + per-niche config. Agent defaults can be overridden by niche profile.

**Future state:** Full Level C override chain:
```
Agent defaults (lowest priority)
  → Niche profile overrides
    → Account overrides (different tones for different client accounts)
      → Job-level overrides (one-off adjustments)
```

Use case: Agency model where different clients/accounts under the same niche need different tones, languages, or content strategies.

**Trigger:** When multi-client or multi-account support is needed.

---

## Stage 1.5 — MVP+ Analytics

### Scope

- Post URL input after manual upload
- Public metrics collector (views, likes, comments, shares) from public TikTok post URLs
- Basic snapshot dashboard showing collected metrics over time
- Snapshot schedule: 15m, 1h, 3h, 6h, 24h, 48h, 7d, 30d after posting

### New Tables

| Table | Purpose |
|-------|---------|
| `posted_videos` | post_id, platform, account_id, post_url, posted_at, job_id, thumbnail_url |
| `analytics_snapshots` | video_id, collected_at, views, likes, comments, shares, source, source_method |

### Input

Manual: user enters post URL + platform + account + posted_at + job_id after uploading.

---

## Stage 2 — Dashboard, Approval, Providers, Budget

### Scope

- Improved dashboard with job history and advanced approval workflow
- Serper API as backup search when Firecrawl daily quota exhausted (2,500 free credits)
- CSV import for Creator Studio / Insights export
- Budget envelope with daily/monthly limits per client/account
- Actual cost tracking per agent/tool per job
- Full preflight cost/risk estimator (not just lightweight warning)
- Creative Director Agent: proposes new angles/templates when variation exhausted
- Full observability dashboard beyond Phase 12's debug-first internal pages

### Full Observability Dashboard and CLI

The debug-first dashboard (Phase 12) and read-only CLI commands (Phase 12-13) give operators basic job visibility. A production-useful observability upgrade was originally planned as Phase 15 caps 6-8 but was recognized as scope creep beyond the MVP debug-first requirement (SRS FR-14). This full observability suite remains Stage 2 scope:

#### Dashboard
- polished pipeline timeline with visual status icons
- retry-from-step controls (built on Phase 13 retry/resume engine)
- artifact browser with download buttons
- video/audio preview
- thumbnail preview
- research brief preview
- script preview
- provider attempts timeline
- provider latency and cost summaries
- gate explanation panels
- filtered job history with search
- searchable logs
- dashboard notifications
- approval workflow integration hooks

#### CLI Parity
Commands matching dashboard observability:

```bash
.venv/bin/python3 -m clipper_agency job-timeline 125
.venv/bin/python3 -m clipper_agency job-open-artifact 125 --path agents/composer/ffmpeg_stderr.log
.venv/bin/python3 -m clipper_agency job-export-debug-bundle 125
```

#### Debug Bundle Export
Create a zip/tar for support and debugging:

```text
job metadata
manifest
agent inputs/outputs
gate results
logs
research brief
script
provider attempts
ffmpeg logs
final package metadata
```

Exclude secrets and large binaries by default unless explicitly requested.

### Phase 13 Retry/Resume and Cache Reuse

Phase 12 intentionally stops at read-only observability: jobs now expose persisted agent states, gate results, manifests, and artifact paths, but operators still cannot mutate a failed job from the debug UI/CLI. Write-enabled retry/resume moves to Phase 13 because it depends on reliable persisted state and reusable artifact contracts.

Planned operator commands:

```text
python3 -m clipper_agency job-retry 125 --from composer
python3 -m clipper_agency job-resume 125
python3 -m clipper_agency job-retry 125 --from voice_producer --use-cache
```

Prerequisites before enabling retry/resume:

- `agent_states` accurately transitions `pending`/`running`/`completed`/`failed`
- gate results are persisted and enforce hard-fail stops
- job config snapshot is stored and reused
- agent input/output artifacts are persisted
- paid provider calls can be skipped when valid cached artifacts exist
- retry policy remains human-triggered only

### Budget Envelope

```yaml
budget_governance:
  monthly_visible_budget_for_creatives: $50
  per_job_creative_approval_limit: $0.50
  daily_spend_limit: $5.00
  emergency_override:
    max_per_day: 1
    max_multiplier: 2x
    requires_reason: true
    alerts_admin: true
```

### New Tables

| Table | Purpose |
|-------|---------|
| `budget_envelopes` | Per-client/account limits and spend |
| `actual_costs` | Per-agent/per-tool actual cost |
| `client_financials` | Payment, revenue, margin (restricted) |
| `agent_proposals` | Creative Director proposals for approval |

### Full Role Model

| Role | Access |
|------|--------|
| Admin | Everything + financial data |
| Creative Lead | Approve jobs, emergency override, operational budget |
| Creative User | Create jobs, see estimated cost |
| Reviewer | Approve/reject output packages |

### Media Provider Expansion

- Cobalt/pybalt (Layer 2, different download engine)
- Serper API for backup search

### Cost Tracking

Estimated vs actual cost per job, per agent, per tool. Enables profitability calculation.

---

## Stage 2+ — Official API Connectors, Baselines, Outlier Detection

### Scope

- Official API connectors with OAuth:
  - TikTok Display API (video.list → view_count, like_count, comment_count, share_count)
  - Instagram Graph API (media insights → views, likes, comments, saved, shares, reach)
  - YouTube Data + Analytics API (views, likes, comments, engagedViews, averageViewDuration)
- Account baseline tracking (rolling median of key metrics per account per platform)
- View velocity calculation
- Outlier detection
- DuckDuckGo site-filtered search (unlimited, free fallback)

### Source Priority Chain for Analytics

```
1. Official API → 2. Public scraper → 3. CSV import → 4. Manual correction
```

### New Tables

| Table | Purpose |
|-------|---------|
| `account_baselines` | Rolling median views/likes/comments per account per platform |
| `analytics_collection_runs` | Collector run history, errors, retries per post |

### Derived Metrics

```text
engagement_rate  = (likes + comments + shares + saves) / views
view_velocity    = (views_now - views_prev) / hours_since_previous
outlier_score    = views / account_median_views_at_same_age
growth_accel     = current_velocity / previous_velocity
```

### Trending Status Logic

| Status | Rule |
|--------|------|
| New | Posted < 1h |
| Rising | velocity > 1.5x baseline AND < 3x |
| Trending | velocity > 3x baseline AND engagement_rate > baseline |
| Outlier | outlier_score > 2x |
| Flat | Velocity decays 2+ consecutive snapshots |
| Underperforming | views < 50% median after 24h |

### Metrics Availability

| Metric | Public Scraper | Official API | CSV Export |
|--------|---------------|-------------|-----------|
| views, likes, comments, shares | ✅ | ✅ | ✅ |
| saves, reach, impressions | ❌ | ✅ | ✅ |
| watch time, retention | ❌ | ✅ (limited) | ✅ |
| profile visits, follows | ❌ | ✅ (permissions) | ✅ |

### Media Provider Expansion

- instaloader (Instagram specialist, Layer 3)
- Douyin_TikTok_Download_API (TikTok/Douyin specialist, Layer 3)
- gallery-dl (image galleries, Layer 3)

### Selection Flow (Stage 2+)

URL → extract platform → try specialist → try yt-dlp → try Cobalt → fallback to Pexels. All config-driven, all optional via toggle.

---

## Stage 3 — Automation, Multi-Account, Learning Loop

### Scope

- Scheduled automated content generation
- Multi-account management per client
- TikTok Direct Post API integration (requires 3-4 week approval)
- Posting automation with auto-track after upload
- Job queues with DB-backed queue
- Learning loop: analytics feeds Creative Memory
- Parallel workers (2-3)

### Learning Loop

```text
analytics_snapshots
    → content_performance_by: hook_type, template, topic, video_length, posting_time, asset_source
    → Creative Memory: hard-avoid underperforming patterns
    → Template Selection: recommend best-performing template per topic
    → Posting Schedule: recommend optimal posting hour per account
    → Niche Profile: auto-adjust rules based on what works
```

### Deployment

Docker Compose on VPS. PostgreSQL. DB-backed queue. 2-3 parallel workers. Per-account limiter.

### Automatic Input (Stage 3+)

Researcher finds trending topics without user input via:
- Google Trends RSS
- News RSS feeds
- Deeper creator history/profile research via ScrapeCreators

---

## Stage 3+ — Multi-Platform, Multilogin

### Scope

- Multi-platform publishing (Instagram Reels, YouTube Shorts)
- Multilogin + Playwright for per-account workspace isolation
- Browser automation for dashboard-only metrics fallback
- Automated upload via browser automation

### Analytics Configuration (Full Example)

```yaml
analytics:
  collection_enabled: true
  schedule_hours: [0.25, 1, 3, 6, 24, 48, 168, 720]
  sources:
    official_api:
      tiktok_display: true
      instagram_graph: true
      youtube_analytics: true
    public_scraper:
      enabled: true
    csv_import:
      enabled: true
    multilogin_browser:
      enabled: true
  baselines:
    min_videos_for_baseline: 10
    recalculate_days: 7
    outlier_threshold: 2.0
    trending_velocity_multiplier: 3.0
    rising_velocity_multiplier: 1.5
```

---

## Stage 4+ — Client Portal, Billing, Scale

### Scope

- Client-facing portal
- Billing and invoicing
- Scale to 1,000+ accounts across multiple niches
- Kubernetes / multi-VPS deployment
- PostgreSQL + Redis
- RQ/Celery workers with auto-scale
- Object storage for final outputs
- Monitoring dashboard
- Full compliance controls and immutable audit logging
- Per-client workspace isolation
- Rate-limit manager
- Advanced retry dashboard and observability

### Deployment

```
Full (1000+)
┌──────────────────┐
│ K8s / Multi-VPS  │
│ PG + Redis       │
│ RQ/Celery workers│
│ Auto-scale       │
│ Object storage   │
│ Monitoring       │
└──────────────────┘
```
