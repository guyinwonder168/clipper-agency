# Visual Director LLM Planning Design

**Date:** 2026-05-31  
**Status:** ✅ Completed  
**Phase:** 16 (Visual Director Intelligence)

## Problem Statement

E2E Run #3 showed Visual Director fails for 5/10 scenes. Root cause: Orchestrator passes ALL research URLs (TikTok videos + Firecrawl news homepages) to Visual Director, which assigns them mechanically without thinking. News URLs go to yt-dlp → silent failure → empty scene paths → card fallback.

The Visual Director doesn't read engagement data, doesn't consume the research brief, and doesn't plan — it just loops through URLs sequentially.

## Design Approach

**Path 1 (Pragmatic MVP):** Keep sequential pipeline, add LLM to Visual Director only. Don't make Orchestrator smart — make agents smart.

### Guiding Principles

1. **Context Compaction** (Azure AI Agent pattern): Pass only signal to LLM, strip noise
2. **Plan Before Generate** (Medium research): Visual Director plans all scenes first, then executes
3. **Magentic mini-manager**: Visual Director builds its own "task ledger" (per-scene plan), then executes it
4. **Data-driven**: Prompt reads from niche config, no hardcoded content angles

---

## Section 1: Data Flow

**Principle:** Orchestrator stays dumb. Visual Director decides what's useful.

```
Orchestrator (dumb relay)
  ├── passes: research_contract.json path
  ├── passes: research_brief.md path  
  ├── passes: scenes from Scriptwriter
  └── NO filtering, NO transformation

Visual Director._plan_with_llm()
  ├── reads research_contract.json + research_brief.md
  ├── COMPACTS: strips CDN URLs, empty content, hashtags, music (noise)
  ├── SORTS: video_sources by engagement (plays descending)
  ├── FORMATS: lean LLM prompt (~500 tokens vs ~15K raw)
  └── sends to LLM → gets back per-scene visual plan (JSON)

Visual Director._execute_plan()
  ├── reads FULL research_contract.json again (with CDN URLs intact)
  └── downloads/generates per-scene visuals per LLM plan
```

### Signal vs Noise for LLM Planning

| Signal (keep) | Noise (strip) |
|---|---|
| `video_sources[].desc` | `video_sources[].video_urls` (CDN links, huge) |
| `video_sources[].plays/likes/shares` | `video_sources[].music` |
| `video_sources[].url` | `video_sources[].hashtags` |
| `video_sources[].author` | `video_sources[].share_url` |
| `context_sources[].title` | `context_sources[].url` (homepages, useless) |
| `context_sources[].description` | `context_sources[].content` (always empty) |
| `research_brief.md` (full) | |

### Researcher Output Anatomy

Files at `data/assets/cache/job_{id}/agents/researcher/`:
- `research_brief.md` — LLM-generated brief with key facts, viral rankings, content suggestions
- `research_contract.json` — `video_sources` (TikTok items with engagement) + `context_sources` (Firecrawl headlines)
- `output.json` — research_brief text + sources array

### Engagement Data (ScrapeCreators)

ScrapeCreators provides rich metrics the current Visual Director ignores:
- Top: 3.86M plays / 81K likes / 4,679 shares
- Dead: 879 plays / 8 likes / 2 shares

LLM will prioritize high-viral clips and skip dead ones.

---

## Section 2: LLM Prompt & Output Schema

### System Prompt (niche-driven)

Reads from `niches/*.yaml`:

```yaml
role: |
  You are a Visual Director for {niche.content_angle} content in {niche.language}.
  Niche config provides: language, tone, content_angle, safety_rules, search_terms, caption_style
```

### Output Schema

LLM returns per-scene JSON:

```json
{
  "scenes": [
    {
      "scene_number": 1,
      "reasoning": "Free text — why this visual choice",
      "action": {
        "type": "tiktok_clip | pexels_video | pexels_image | text_card",
        "source_url": "tiktok URL (if tiktok_clip)",
        "search_query": "Pexels query (if pexels_*)",
        "headline": "Card headline (if text_card)",
        "subtitle": "Card subtitle (if text_card)",
        "style": "news_card | speech_bubble | breaking_news | mock_ui",
        "image_search": "Pexels query for card image",
        "bg_color": "gradient_red | gradient_purple | gradient_blue",
        "border_color": "brand"
      },
      "fallback": {  }
    }
  ]
}
```

### Design Decisions

- `action.type` enum = machine-readable for executor
- `reasoning` = free text, LLM thinks freely (no menu constraint)
- `fallback` required per scene — if TikTok/Pexels fails, always have backup
- `search_query` / `image_search` are LLM-generated (not hardcoded, like claude-auto-tok)
- Every `text_card` gets a relevant image via `image_search` + 3-tier fallback chain

### Text Card Image Fallback Chain

```
image_search: "Nikita Mirzani court trial"
    │
    ├─ 1. Pexels API (search_photos) → found? ✅ done
    │     (likely ❌ for Indonesian celebs — generic stock only)
    │
    ├─ 2. Targeted Firecrawl article search
    │     query: "Nikita Mirzani" site:insertlive.com OR site:grid.id
    │     → gets ARTICLE URL (not homepage)
    │     → scrape that article → extract og:image (celebrity photo)
    │     found relevant image? ✅ done
    │
    └─ 3. Gradient card → styled text on gradient bg, no photo (last resort)
```

**Why this order:** Pexels won't have Indonesian celebrities. Targeted Firecrawl article search is the PRIMARY image source for this niche. Pexels is bonus for generic scenes (courtroom, handcuffs, etc.).

**Lazy/on-demand:** Don't pre-fetch during research. Only pay Firecrawl credits when Pexels fails.

### Visual Style Reference

Techniques from Infographics Show + Tribunnews Shorts analysis:

| Technique | Implementation |
|---|---|
| Photo + Headline Card | `text_card` style: `news_card` — photo top 60%, headline bottom 40% |
| Speech Bubble Overlay | `text_card` style: `speech_bubble` — character + rounded bubble |
| Breaking News Banner | `text_card` style: `breaking_news` — bold UPPERCASE on red/dark |
| Gradient Backgrounds | Mood-driven: red=scandal, blue=legal, purple=viral |
| Branded Border Frame | Thick colored border around entire 9:16 frame |
| Mock UI Screenshot | `text_card` style: `mock_ui` — fake app notification |
| Engagement Badge | "3.6M views 🔥" overlay on video clips |

---

## Section 3: Files Changed

### Existing Infrastructure Reused (zero new code)

| What | Where | Reuse |
|---|---|---|
| LLM Client | `llm/client.py` → `OpenRouterClient.chat()` | `_plan_with_llm()` calls same as Scriptwriter |
| Model config | `config/hierarchy.py` line 15 | `visual_director.model` already exists |
| Prompt loader | `agents/prompts.py` → `load_prompt()` | Same pattern as all agents |
| yt-dlp download | `services/ytdlp.py` → `YtDlpService.download()` | For `tiktok_clip` scenes |
| Pexels video | `services/pexels.py` → `PexelsService.search_videos()` + `download_video()` | For `pexels_video` scenes |
| Firecrawl search | `services/firecrawl_service.py` → `search()` | Image fallback tier 2 |
| Firecrawl scrape | `services/firecrawl_service.py` → `scrape()` | Image fallback tier 2 |
| Artifact writing | `core/artifacts.py` → `write_json()` | scene_plan.json, provenance.json |
| Media probe | `core/media_probe.py` → `probe_video()` | Provenance tracking |
| Settings loader | `config/loader.py` → `load_settings()` | Model selection |

### Files Changed

| File | Lines | What | New vs Reuse |
|---|---|---|---|
| `agents/visual_director.py` | ~70 lines | Add `_compact_research_data()`, `_plan_with_llm()`, `_execute_plan()` | Reuses: `OpenRouterClient`, `load_prompt()`, `load_settings()`, `PexelsService`, `YtDlpService`, `FirecrawlService`. New: compaction logic, LLM call, image fallback |
| `orchestrator/engine.py` | ~8 lines | Pass research paths instead of extracted URLs | Refactor of existing lines 436-444 |
| `services/pexels.py` | ~15 lines | Add `search_photos()` | New method, same API pattern as `search_videos()` |
| `agents/prompts.py` | 1 line | `.txt` → `.md` extension | Extension change only |
| `prompts/safety.md` | rename | `safety.txt` → `safety.md` (content unchanged) |
| `prompts/researcher.md` | rename | `researcher.txt` → `researcher.md` |
| `prompts/scriptwriter.md` | rename | `scriptwriter.txt` → `scriptwriter.md` |
| `prompts/reviewer.md` | rename | `reviewer.txt` → `reviewer.md` |
| `prompts/visual_director.md` | new | LLM system prompt for visual planning |
| `tests/test_agents_visual.py` | ~40 lines | Tests for compaction, LLM planning, execution, edge cases |

### Files UNCHANGED

- `researcher.py` — no changes
- `scriptwriter.py` — no changes
- `voice_producer.py` — no changes
- `composer.py` — no changes (receives same asset format)
- `reviewer.py` — no changes
- All services except `pexels.py` — no changes
- All 613 existing tests — no changes

### Cost

| Item | Estimate |
|---|---|
| LLM call (model from hierarchy) | ~$0.002 per run |
| Firecrawl (text_card scenes only, when Pexels misses) | ~1-2 calls × $0.001 |
| Pexels API | Free tier (200 req/hr) |
| **Total per run** | **~$0.003-0.005** |
| Latency added | +3-5 seconds |

### Edge Case Handling

| Scenario | Behavior |
|---|---|
| LLM returns invalid JSON | Retry once with schema reminder, then fall back to old sequential assignment |
| All TikTok downloads fail | Every scene has `fallback` → Pexels or text_card |
| 0 ScrapeCreators results | LLM sees empty video_sources, plans all Pexels/text_card |
| Research files missing | Fall back to old `_plan_scenes()` behavior |
| Pexels API rate limited | Skip to Firecrawl image search or gradient card |

---

## Future Work (Deferred)

1. **Prompt deduplication** — Remove hardcoded "Indonesian artist infotainment" from 4 existing prompt files, replace with niche config variables. Separate phase.
2. **LLM-powered Orchestrator** — Research validated: use simplest pattern that works. Our pipeline is sequential/deterministic — don't make orchestrator smart, make agents smart. Can evolve later.
3. **text_card rendering** — Composer template engine already supports cards. The LLM output schema aligns with existing Composer template variables. No Composer changes needed now.

---

## Completion Note

Design fully implemented as of earlier phases (Phase 16). All deferred items remain valid for future phases:
- Prompt deduplication → ✅ Completed in Phase 17
- LLM-powered Orchestrator → Stays deferred
- text_card rendering → Already supported via Composer templates
