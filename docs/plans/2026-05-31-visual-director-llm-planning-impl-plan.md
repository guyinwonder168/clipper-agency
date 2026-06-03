# Visual Director LLM Planning Implementation Plan

**Status:** ✅ Completed

> ~~**For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.~~

**Goal:** Replace Visual Director's dumb sequential URL assignment with LLM-driven per-scene visual planning that reads research data, engagement metrics, and the research brief.

**Architecture:** Visual Director gains 3 new methods: `_compact_research_data()` (strips noise from research), `_plan_with_llm()` (LLM plans per-scene visuals), `_execute_plan()` (downloads/generates per plan). Orchestrator passes raw research paths instead of extracted URLs. New `search_photos()` added to PexelsService. Prompt file extension migrated from `.txt` to `.md`.

**Tech Stack:** Python 3.11+, OpenRouter LLM API, Pexels API (videos + photos), Firecrawl API (image fallback), yt-dlp, Pillow (cards), pytest-mock

**Design doc:** `docs/plans/2026-05-31-visual-director-llm-planning-design.md`

---

### Task 1: Rename prompt files .txt → .md

**Files:**
- Rename: `prompts/safety.txt` → `prompts/safety.md`
- Rename: `prompts/researcher.txt` → `prompts/researcher.md`
- Rename: `prompts/scriptwriter.txt` → `prompts/scriptwriter.md`
- Rename: `prompts/reviewer.txt` → `prompts/reviewer.md`
- Modify: `clipper_agency/agents/prompts.py:15`

**Step 1: Update prompts.py to look for .md files**

In `clipper_agency/agents/prompts.py`, change line 15:

```python
# Before:
    prompt_path = prompts_dir / f"{agent_name}.txt"
# After:
    prompt_path = prompts_dir / f"{agent_name}.md"
```

**Step 2: Rename all prompt files**

```bash
git mv prompts/safety.txt prompts/safety.md
git mv prompts/researcher.txt prompts/researcher.md
git mv prompts/scriptwriter.txt prompts/scriptwriter.md
git mv prompts/reviewer.txt prompts/reviewer.md
```

**Step 3: Run tests to verify nothing broke**

Run: `.venv/bin/python3 -m pytest -x -q`
Expected: 613 passed, 2 deselected (same as before)

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename prompt files from .txt to .md for better editor support"
```

---

### Task 2: Add `search_photos()` to PexelsService

**Files:**
- Modify: `clipper_agency/services/pexels.py`
- Test: `tests/test_services_pexels.py` (extend existing or create if missing)

**Step 1: Write the failing test**

In `tests/test_services_pexels.py` (create if not exists):

```python
"""Tests for PexelsService photo search."""

import pytest
from unittest.mock import patch, MagicMock
from clipper_agency.services.pexels import PexelsService


class TestPexelsPhotoSearch:
    """Photo search method for text card images."""

    def test_search_photos_returns_list(self):
        """search_photos returns list of photo dicts with id and src."""
        service = PexelsService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "photos": [
                {"id": 1, "src": {"medium": "https://images.pexels.com/1.jpg"}},
                {"id": 2, "src": {"medium": "https://images.pexels.com/2.jpg"}},
            ]
        }
        with patch.object(service, "api_key", "test-key"):
            with patch("clipper_agency.services.pexels.httpx.Client") as MockClient:
                mock_client = MagicMock()
                mock_client.get.return_value = mock_resp
                MockClient.return_value.__enter__ = lambda s: mock_client
                MockClient.return_value.__exit__ = MagicMock(return_value=False)
                result = service.search_photos("courtroom", per_page=3)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert "src" in result[0]

    def test_search_photos_raises_without_api_key(self):
        """search_photos raises ValueError if PEXELS_API_KEY not set."""
        service = PexelsService()
        service.api_key = None
        with pytest.raises(ValueError, match="PEXELS_API_KEY"):
            service.search_photos("test")
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_services_pexels.py -v -k "photo"`
Expected: FAIL — `AttributeError: 'PexelsService' object has no attribute 'search_photos'`

**Step 3: Implement `search_photos()`**

In `clipper_agency/services/pexels.py`, add after `download_video()`:

```python
    def search_photos(
        self, query: str, per_page: int = 5
    ) -> list[dict[str, Any]]:
        """Search for stock photos matching the query.

        Returns:
            List of photo metadata dicts with id and src URLs.
        """
        if not self.api_key:
            raise ValueError("PEXELS_API_KEY not set")

        logger.info("Pexels: searching photos (per_page=%d)", per_page)
        with httpx.Client(base_url=self.BASE_URL) as client:
            resp = client.get(
                "/search",
                headers={"Authorization": self.api_key},
                params={
                    "query": query,
                    "per_page": per_page,
                    "orientation": "portrait",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            photos = data.get("photos", [])
            logger.info("Pexels: found %d photos", len(photos))
            return [
                {
                    "id": p["id"],
                    "src": p.get("src", {}),
                }
                for p in photos
            ]
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_services_pexels.py -v -k "photo"`
Expected: PASS

**Step 5: Run all tests**

Run: `.venv/bin/python3 -m pytest -x -q`
Expected: 615 passed, 2 deselected (2 new tests added)

**Step 6: Commit**

```bash
git add clipper_agency/services/pexels.py tests/test_services_pexels.py
git commit -m "feat: add search_photos() to PexelsService for text card images"
```

---

### Task 3: Create visual_director.md prompt

**Files:**
- Create: `prompts/visual_director.md`

**Step 1: Create the prompt file**

Write `prompts/visual_director.md`:

```markdown
You are a Visual Director for {content_angle} content in {language}.

## Your Task

You receive:
1. **Scenes** from the scriptwriter (voiceover text, timing)
2. **Video sources** with engagement metrics (plays, likes, shares)
3. **Context sources** (news headlines, background info)
4. **Research brief** (key facts, viral rankings, content suggestions)

For EACH scene, decide the best visual approach. Think like a creative director — consider:
- Which video clips have the highest engagement for viral moments
- When to use text cards for dramatic reveals or breaking news
- When stock footage can fill gaps (courtroom, generic scenes)
- Every text card MUST have a relevant image — never plain text on flat background

## Output Format

Return ONLY valid JSON:
```json
{{
  "scenes": [
    {{
      "scene_number": 1,
      "reasoning": "Why this visual choice",
      "action": {{
        "type": "tiktok_clip",
        "source_url": "tiktok URL here"
      }},
      "fallback": {{
        "type": "pexels_video",
        "search_query": "descriptive search term"
      }}
    }}
  ]
}}
```

## Action Types

- `tiktok_clip`: Use a TikTok video. Requires `source_url`.
- `pexels_video`: Stock video. Requires `search_query`.
- `pexels_image`: Stock image as full-frame visual. Requires `search_query`.
- `text_card`: Headline card with image. Requires `headline`, `image_search`, `style`.

## Text Card Fields
- `headline`: Bold text (short, punchy)
- `subtitle`: Secondary text (optional)
- `style`: `news_card` | `speech_bubble` | `breaking_news` | `mock_ui`
- `image_search`: Pexels search query for background image
- `bg_color`: `gradient_red` | `gradient_purple` | `gradient_blue` (optional)
- `border_color`: `brand` (optional)

## Rules

- ALWAYS include a `fallback` for every scene
- Prioritize high-engagement video clips (check plays/likes/shares)
- Match scene tone to visual style (scandal=red, legal=blue, viral=purple)
- Never assign a TikTok URL if no relevant video exists for that scene
- Generate specific, descriptive search queries — not generic terms
- Every text_card must have `image_search` filled in

## Safety

{safety_rules_text}
```

**Step 2: Commit**

```bash
git add prompts/visual_director.md
git commit -m "feat: add LLM visual planning prompt for Visual Director"
```

---

### Task 4: Add `_compact_research_data()` to Visual Director

**Files:**
- Modify: `clipper_agency/agents/visual_director.py`
- Modify: `tests/test_agents_visual.py`

**Step 1: Write the failing tests**

Add to `tests/test_agents_visual.py`:

```python
class TestCompactResearchData:
    """Research data compaction for LLM planning."""

    def test_strips_noise_keeps_signal(self, tmp_path):
        """Compaction strips CDN URLs, music, hashtags, empty content."""
        import json
        agent = VisualDirectorAgent()

        contract = {
            "video_sources": [
                {
                    "url": "https://tiktok.com/@user/v/1",
                    "desc": "Denise Chariesta viral",
                    "plays": 3860000,
                    "likes": 81000,
                    "shares": 4679,
                    "author": "@denise",
                    "music": "some song",
                    "hashtags": ["#viral"],
                    "share_url": "https://share.tiktok.com/1",
                    "video_urls": ["https://cdn.tiktok.com/big.mp4"],
                }
            ],
            "context_sources": [
                {
                    "title": "Insertlive",
                    "description": "Nikita Mirzani goes to court",
                    "url": "https://insertlive.com",
                    "content": "",
                }
            ],
        }
        brief = "# Research Brief\n\nKey facts here."

        contract_path = tmp_path / "research_contract.json"
        contract_path.write_text(json.dumps(contract))
        brief_path = tmp_path / "research_brief.md"
        brief_path.write_text(brief)

        result = agent._compact_research_data(str(contract_path), str(brief_path))

        # Signal preserved
        assert result["video_sources"][0]["url"] == "https://tiktok.com/@user/v/1"
        assert result["video_sources"][0]["desc"] == "Denise Chariesta viral"
        assert result["video_sources"][0]["plays"] == 3860000
        assert result["context_sources"][0]["description"] == "Nikita Mirzani goes to court"
        assert "research_brief" in result

        # Noise stripped
        vs = result["video_sources"][0]
        assert "music" not in vs
        assert "hashtags" not in vs
        assert "share_url" not in vs
        assert "video_urls" not in vs

        cs = result["context_sources"][0]
        assert "url" not in cs
        assert "content" not in cs

    def test_sorts_video_sources_by_engagement(self, tmp_path):
        """Video sources sorted by plays descending."""
        import json
        agent = VisualDirectorAgent()

        contract = {
            "video_sources": [
                {"url": "https://tiktok.com/1", "desc": "low", "plays": 100},
                {"url": "https://tiktok.com/2", "desc": "high", "plays": 5000000},
                {"url": "https://tiktok.com/3", "desc": "mid", "plays": 50000},
            ],
            "context_sources": [],
        }

        contract_path = tmp_path / "research_contract.json"
        contract_path.write_text(json.dumps(contract))

        result = agent._compact_research_data(str(contract_path), "")

        assert result["video_sources"][0]["plays"] == 5000000
        assert result["video_sources"][1]["plays"] == 50000
        assert result["video_sources"][2]["plays"] == 100

    def test_handles_missing_files_gracefully(self):
        """Returns minimal dict when files don't exist."""
        agent = VisualDirectorAgent()
        result = agent._compact_research_data("/nonexistent.json", "/nonexistent.md")
        assert result == {"video_sources": [], "context_sources": []}
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_agents_visual.py -v -k "compact"`
Expected: FAIL — `AttributeError`

**Step 3: Implement `_compact_research_data()`**

In `clipper_agency/agents/visual_director.py`, add after `_build_provenance()`:

```python
    def _compact_research_data(
        self, contract_path: str, brief_path: str,
    ) -> dict[str, Any]:
        """Strip noise, keep signal for LLM planning prompt."""
        try:
            contract = json.loads(Path(contract_path).read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {"video_sources": [], "context_sources": []}

        # Compact video sources: keep signal, strip noise
        compact_videos = []
        for v in contract.get("video_sources", []):
            compact_videos.append({
                k: v[k] for k in ("url", "desc", "plays", "likes", "shares", "author")
                if k in v
            })

        # Sort by plays descending
        compact_videos.sort(key=lambda x: x.get("plays", 0), reverse=True)

        # Compact context sources: keep title + description only
        compact_contexts = []
        for c in contract.get("context_sources", []):
            compact_contexts.append({
                k: c[k] for k in ("title", "description")
                if k in c
            })

        result: dict[str, Any] = {
            "video_sources": compact_videos,
            "context_sources": compact_contexts,
        }

        # Read research brief if available
        try:
            brief = Path(brief_path).read_text(encoding="utf-8").strip()
            if brief:
                result["research_brief"] = brief
        except FileNotFoundError:
            pass

        return result
```

Add `import json` at the top of the file if not already present.

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_agents_visual.py -v -k "compact"`
Expected: 3 PASS

**Step 5: Run all tests**

Run: `.venv/bin/python3 -m pytest -x -q`
Expected: All pass

**Step 6: Commit**

```bash
git add clipper_agency/agents/visual_director.py tests/test_agents_visual.py
git commit -m "feat: add _compact_research_data() to Visual Director"
```

---

### Task 5: Add `_plan_with_llm()` to Visual Director

**Files:**
- Modify: `clipper_agency/agents/visual_director.py`
- Modify: `tests/test_agents_visual.py`

**Step 1: Write the failing tests**

Add to `tests/test_agents_visual.py`:

```python
class TestPlanWithLLM:
    """LLM-driven visual planning."""

    def test_plan_with_llm_returns_per_scene_plan(self, mocker):
        """LLM returns a valid per-scene visual plan."""
        agent = VisualDirectorAgent()

        mock_llm_response = {
            "content": json.dumps({
                "scenes": [
                    {
                        "scene_number": 1,
                        "reasoning": "High engagement TikTok clip",
                        "action": {"type": "tiktok_clip", "source_url": "https://tiktok.com/@user/v/1"},
                        "fallback": {"type": "pexels_video", "search_query": "courtroom drama"},
                    },
                    {
                        "scene_number": 2,
                        "reasoning": "No relevant video, use text card",
                        "action": {
                            "type": "text_card",
                            "headline": "BREAKING NEWS",
                            "style": "breaking_news",
                            "image_search": "news anchor desk",
                            "bg_color": "gradient_red",
                        },
                        "fallback": {"type": "text_card", "headline": "UPDATE", "style": "news_card", "image_search": "news"},
                    },
                ]
            }),
            "model": "test-model",
            "usage": {},
        }
        mock_llm = mocker.patch(
            "clipper_agency.agents.visual_director.OpenRouterClient"
        )
        mock_llm.return_value.chat.return_value = mock_llm_response

        # Mock load_prompt to return a simple prompt
        mocker.patch(
            "clipper_agency.agents.visual_director.load_prompt",
            return_value="You are a Visual Director for {content_angle} content.",
        )
        # Mock load_settings
        mocker.patch(
            "clipper_agency.agents.visual_director.load_settings",
        )

        scenes = [
            {"scene": 1, "text": "Hook about viral video", "duration": 5},
            {"scene": 2, "text": "Breaking news reveal", "duration": 4},
        ]
        compact_data = {
            "video_sources": [{"url": "https://tiktok.com/@user/v/1", "plays": 3860000}],
            "context_sources": [],
        }

        plan = agent._plan_with_llm(scenes, compact_data)

        assert len(plan) == 2
        assert plan[0]["action"]["type"] == "tiktok_clip"
        assert plan[1]["action"]["type"] == "text_card"

    def test_plan_with_llm_falls_back_on_invalid_json(self, mocker):
        """If LLM returns garbage, fall back to old _plan_scenes behavior."""
        agent = VisualDirectorAgent()

        mock_llm = mocker.patch(
            "clipper_agency.agents.visual_director.OpenRouterClient"
        )
        mock_llm.return_value.chat.return_value = {
            "content": "NOT JSON AT ALL {{{",
            "model": "test",
            "usage": {},
        }
        mocker.patch(
            "clipper_agency.agents.visual_director.load_prompt",
            return_value="You are a Visual Director.",
        )
        mocker.patch(
            "clipper_agency.agents.visual_director.load_settings",
        )

        scenes = [{"scene": 1, "text": "Test", "duration": 5}]
        compact_data = {"video_sources": [], "context_sources": []}

        plan = agent._plan_with_llm(scenes, compact_data)

        # Should fall back to sequential plan with pexels/none
        assert len(plan) == 1
        assert plan[0]["source"] in ("pexels", "none")
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_agents_visual.py -v -k "plan_with_llm"`
Expected: FAIL — `AttributeError`

**Step 3: Implement `_plan_with_llm()`**

In `clipper_agency/agents/visual_director.py`, add after `_compact_research_data()`:

```python
    def _plan_with_llm(
        self, scenes: list[dict], compact_data: dict,
    ) -> list[dict]:
        """LLM plans per-scene visual strategy. Falls back to sequential."""
        try:
            from clipper_agency.agents.prompts import PROMPTS_DIR, load_prompt
            from clipper_agency.config.loader import load_settings
            from clipper_agency.llm.client import OpenRouterClient

            settings = load_settings()
            llm = OpenRouterClient()
            prompt_text = load_prompt(
                "visual_director", "", PROMPTS_DIR,
            )
            safety_rules = getattr(settings, "safety_rules", [])
            safety_rules_text = "\n".join(f"- {r}" for r in safety_rules) if safety_rules else "None"

            user_content = json.dumps({
                "scenes": scenes,
                "research": compact_data,
            }, ensure_ascii=False)

            response = llm.chat(
                model=settings.researcher_model,  # use cheapest model from hierarchy
                messages=[
                    {
                        "role": "system",
                        "content": prompt_text.format(
                            content_angle="TikTok infotainment",
                            language="Indonesian",
                            safety_rules_text=safety_rules_text,
                        ),
                    },
                    {"role": "user", "content": user_content},
                ],
                temperature=0.5,
                max_tokens=2048,
            )

            parsed = json.loads(
                response["content"].strip().strip("```json").strip("```").strip()
            )
            return parsed.get("scenes", [])

        except (json.JSONDecodeError, KeyError, Exception) as e:
            logger.warning("LLM planning failed, falling back to sequential: %s", e)
            # Fallback: old sequential assignment
            urls = [v["url"] for v in compact_data.get("video_sources", [])]
            return self._plan_scenes(scenes, urls, [])
```

Also add the import for `load_prompt` at the top of `visual_director.py` if not present — but it's used inside the method, so the local import above is sufficient.

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_agents_visual.py -v -k "plan_with_llm"`
Expected: 2 PASS

**Step 5: Run all tests**

Run: `.venv/bin/python3 -m pytest -x -q`
Expected: All pass

**Step 6: Commit**

```bash
git add clipper_agency/agents/visual_director.py tests/test_agents_visual.py
git commit -m "feat: add _plan_with_llm() to Visual Director with fallback"
```

---

### Task 6: Add `_execute_plan()` with image fallback chain

**Files:**
- Modify: `clipper_agency/agents/visual_director.py`
- Modify: `tests/test_agents_visual.py`

**Step 1: Write the failing tests**

Add to `tests/test_agents_visual.py`:

```python
class TestExecutePlan:
    """LLM plan execution with image fallback chain."""

    def test_execute_tiktok_clip(self, mocker, tmp_path):
        """tiktok_clip action downloads via yt-dlp."""
        agent = VisualDirectorAgent()
        mock_ytdlp = mocker.patch(
            "clipper_agency.agents.visual_director.YtDlpService"
        )
        mock_ytdlp.return_value.download.return_value = DownloadResult(
            path=str(tmp_path / "scene_1.mp4")
        )

        plan = [{
            "scene_number": 1,
            "action": {"type": "tiktok_clip", "source_url": "https://tiktok.com/v/1"},
        }]
        result = agent._execute_plan(plan, str(tmp_path))
        assert result[0]["source"] == "tiktok_clip"
        assert result[0]["path"] == str(tmp_path / "scene_1.mp4")

    def test_execute_pexels_video(self, mocker, tmp_path):
        """pexels_video action searches and downloads."""
        agent = VisualDirectorAgent()
        mock_pexels = mocker.patch(
            "clipper_agency.agents.visual_director.PexelsService"
        )
        mock_pexels.return_value.search_videos.return_value = [
            {"id": 1, "video_files": [{"link": "https://video.pexels.com/1.mp4"}]},
        ]
        mock_pexels.return_value.download_video.return_value = str(tmp_path / "scene_1.mp4")

        plan = [{
            "scene_number": 1,
            "action": {"type": "pexels_video", "search_query": "courtroom"},
        }]
        result = agent._execute_plan(plan, str(tmp_path))
        assert result[0]["source"] == "pexels_video"

    def test_execute_text_card_with_pexels_image(self, mocker, tmp_path):
        """text_card action finds image via Pexels first."""
        agent = VisualDirectorAgent()
        mock_pexels = mocker.patch(
            "clipper_agency.agents.visual_director.PexelsService"
        )
        mock_pexels.return_value.search_photos.return_value = [
            {"id": 1, "src": {"medium": "https://images.pexels.com/1.jpg"}},
        ]
        # Mock httpx for image download
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"fake_image_data"
        mock_response.raise_for_status = mocker.MagicMock()
        with patch("clipper_agency.agents.visual_director.httpx.Client") as MockClient:
            mock_client = mocker.MagicMock()
            mock_client.get.return_value = mock_response
            MockClient.return_value.__enter__ = lambda s: mock_client
            MockClient.return_value.__exit__ = mocker.MagicMock(return_value=False)

            plan = [{
                "scene_number": 1,
                "action": {
                    "type": "text_card",
                    "headline": "BREAKING",
                    "style": "breaking_news",
                    "image_search": "news desk",
                    "bg_color": "gradient_red",
                },
            }]
            result = agent._execute_plan(plan, str(tmp_path))
            assert result[0]["source"] == "text_card"
            assert result[0]["path"] != ""

    def test_execute_uses_fallback_on_failure(self, mocker, tmp_path):
        """When primary action fails, fallback is used."""
        agent = VisualDirectorAgent()
        mock_ytdlp = mocker.patch(
            "clipper_agency.agents.visual_director.YtDlpService"
        )
        mock_ytdlp.return_value.download.return_value = None  # TikTok fails

        mock_pexels = mocker.patch(
            "clipper_agency.agents.visual_director.PexelsService"
        )
        mock_pexels.return_value.search_videos.return_value = [
            {"id": 1, "video_files": [{"link": "https://video.pexels.com/1.mp4"}]},
        ]
        mock_pexels.return_value.download_video.return_value = str(tmp_path / "scene_1.mp4")

        plan = [{
            "scene_number": 1,
            "action": {"type": "tiktok_clip", "source_url": "https://tiktok.com/v/1"},
            "fallback": {"type": "pexels_video", "search_query": "drama"},
        }]
        result = agent._execute_plan(plan, str(tmp_path))
        assert result[0]["source"] == "pexels_video"  # fell back
```

**Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_agents_visual.py -v -k "execute_plan"`
Expected: FAIL — `AttributeError`

**Step 3: Implement `_execute_plan()`**

In `clipper_agency/agents/visual_director.py`, add after `_plan_with_llm()`:

```python
    def _execute_plan(
        self, plan: list[dict], scenes_dir: str,
    ) -> list[dict]:
        """Execute the LLM-generated visual plan with fallback chain."""
        import httpx

        pexels = PexelsService()
        ytdlp = YtDlpService()
        Path(scenes_dir).mkdir(parents=True, exist_ok=True)

        assets: list[dict] = []
        for item in plan:
            scene_id = item["scene_number"]
            action = item.get("action", {})
            fallback = item.get("fallback")
            action_type = action.get("type", "none")

            result = self._execute_action(action, scene_id, scenes_dir, pexels, ytdlp)

            if result is None and fallback:
                logger.info("Scene %d: primary failed, using fallback", scene_id)
                result = self._execute_action(fallback, scene_id, scenes_dir, pexels, ytdlp)

            if result:
                assets.append({"scene": scene_id, **result})
            else:
                assets.append({"scene": scene_id, "source": "none", "path": ""})

        return assets

    def _execute_action(
        self, action: dict, scene_id: int, scenes_dir: str,
        pexels: PexelsService, ytdlp: YtDlpService,
    ) -> dict | None:
        """Execute a single action. Returns {source, path} or None on failure."""
        action_type = action.get("type", "none")

        if action_type == "tiktok_clip":
            url = action.get("source_url", "")
            if not url:
                return None
            output_path = f"{scenes_dir}/scene_{scene_id}.mp4"
            result = ytdlp.download(url, output_path)
            return {"source": "tiktok_clip", "path": result.path} if result else None

        elif action_type == "pexels_video":
            query = action.get("search_query", "")
            if not query:
                return None
            try:
                videos = pexels.search_videos(query, per_page=1)
                if videos and videos[0].get("video_files"):
                    video_url = videos[0]["video_files"][0]["link"]
                    path = pexels.download_video(video_url, scenes_dir, f"scene_{scene_id}.mp4")
                    return {"source": "pexels_video", "path": path} if path else None
            except Exception:
                pass
            return None

        elif action_type == "pexels_image":
            query = action.get("search_query", "")
            return self._fetch_image(query, scene_id, scenes_dir, pexels)

        elif action_type == "text_card":
            image_search = action.get("image_search", "")
            image_result = self._fetch_image(image_search, scene_id, scenes_dir, pexels)
            return {
                "source": "text_card",
                "path": image_result.get("path", "") if image_result else "",
                "headline": action.get("headline", ""),
                "style": action.get("style", "news_card"),
                "bg_color": action.get("bg_color", ""),
            }

        return None

    def _fetch_image(
        self, query: str, scene_id: int, scenes_dir: str,
        pexels: PexelsService,
    ) -> dict | None:
        """3-tier image fallback: Pexels → Firecrawl → gradient."""
        import httpx

        # Tier 1: Pexels photos
        if query:
            try:
                photos = pexels.search_photos(query, per_page=1)
                if photos:
                    img_url = photos[0].get("src", {}).get("medium", "")
                    if img_url:
                        path = Path(scenes_dir) / f"scene_{scene_id}_img.jpg"
                        try:
                            with httpx.Client(timeout=30) as client:
                                resp = client.get(img_url)
                                resp.raise_for_status()
                                path.write_bytes(resp.content)
                            return {"source": "pexels_image", "path": str(path)}
                        except Exception:
                            pass
            except Exception:
                pass

        # Tier 2: Firecrawl article search → og:image
        if query:
            try:
                from clipper_agency.services.firecrawl_service import FirecrawlService
                fc = FirecrawlService()
                results = fc.search(query, max_results=1)
                if results:
                    article = fc.scrape(results[0]["url"])
                    if article:
                        # Extract og:image from markdown or metadata
                        content = article.get("markdown", "")
                        import re
                        og_match = re.search(r'!\[.*?\]\((https://[^)]+\.(?:jpg|png|webp))', content)
                        if og_match:
                            img_url = og_match.group(1)
                            path = Path(scenes_dir) / f"scene_{scene_id}_img.jpg"
                            try:
                                with httpx.Client(timeout=30) as client:
                                    resp = client.get(img_url)
                                    resp.raise_for_status()
                                    path.write_bytes(resp.content)
                                return {"source": "firecrawl_image", "path": str(path)}
                            except Exception:
                                pass
            except Exception:
                pass

        # Tier 3: Gradient card (no image)
        return None
```

Also add the import at top of `visual_director.py`:
```python
import json
import httpx
```

**Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_agents_visual.py -v -k "execute_plan"`
Expected: 4 PASS

**Step 5: Run all tests**

Run: `.venv/bin/python3 -m pytest -x -q`
Expected: All pass

**Step 6: Commit**

```bash
git add clipper_agency/agents/visual_director.py tests/test_agents_visual.py
git commit -m "feat: add _execute_plan() with image fallback chain to Visual Director"
```

---

### Task 7: Wire up new methods in `execute()` + update engine.py

**Files:**
- Modify: `clipper_agency/agents/visual_director.py` (execute method)
- Modify: `clipper_agency/orchestrator/engine.py`
- Modify: `tests/test_agents_visual.py`

**Step 1: Write the failing integration test**

Add to `tests/test_agents_visual.py`:

```python
class TestLLMPlanningIntegration:
    """Full execute() flow with LLM planning."""

    def test_execute_uses_llm_when_research_paths_provided(self, mocker, tmp_path):
        """When research_contract_path is provided, LLM planning is used."""
        import json

        # Setup research files
        contract = {
            "video_sources": [
                {"url": "https://tiktok.com/@user/v/1", "desc": "viral", "plays": 1000000},
            ],
            "context_sources": [],
        }
        contract_path = tmp_path / "research_contract.json"
        contract_path.write_text(json.dumps(contract))
        brief_path = tmp_path / "research_brief.md"
        brief_path.write_text("# Brief")

        # Mock LLM
        mock_llm = mocker.patch(
            "clipper_agency.agents.visual_director.OpenRouterClient"
        )
        mock_llm.return_value.chat.return_value = {
            "content": json.dumps({
                "scenes": [
                    {
                        "scene_number": 1,
                        "reasoning": "Use viral TikTok",
                        "action": {"type": "pexels_video", "search_query": "drama"},
                        "fallback": {"type": "text_card", "headline": "NEWS", "style": "news_card", "image_search": "news"},
                    }
                ]
            }),
            "model": "test",
            "usage": {},
        }
        mocker.patch(
            "clipper_agency.agents.visual_director.load_prompt",
            return_value="You are a Visual Director.",
        )
        mocker.patch(
            "clipper_agency.agents.visual_director.load_settings",
        )

        # Mock services
        mock_pexels = mocker.patch(
            "clipper_agency.services.pexels.PexelsService.search_videos",
            return_value=[{"id": 1, "video_files": [{"link": "https://video.pexels.com/1.mp4"}]}],
        )
        mocker.patch(
            "clipper_agency.services.pexels.PexelsService.download_video",
            return_value=str(tmp_path / "scene_1.mp4"),
        )

        agent = VisualDirectorAgent()
        result = agent.execute(
            job_id=1,
            script=[{"scene": 1, "text": "Hook", "duration": 5}],
            topic="Test topic",
            output_dir=str(tmp_path),
            research_contract_path=str(contract_path),
            research_brief_path=str(brief_path),
        )

        assert result["status"] == "completed"
        assert len(result["assets"]) == 1
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_agents_visual.py -v -k "integration"`
Expected: FAIL — new kwargs not wired

**Step 3: Update `execute()` in visual_director.py**

In `execute()`, add the new kwargs and branch logic:

```python
    def execute(
        self,
        job_id: int,
        script: list[dict] | None = None,
        topic: str = "",
        source_urls: list[str] | None = None,
        output_dir: str = "",
        research_contract_path: str = "",
        research_brief_path: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        scenes = script or []

        assets_cache = kwargs.get("assets_cache", "")
        agent_dir = ""
        if assets_cache:
            agent_dir = ensure_agent_dir(assets_cache, job_id, "visual_director")
            write_json(agent_input_file(assets_cache, job_id, "visual_director"), {
                "job_id": job_id,
                "scene_count": len(scenes),
                "topic": topic,
                "has_research_data": bool(research_contract_path),
            })

        logger.info(
            "Visual: scenes=%d has_research=%s",
            len(scenes), bool(research_contract_path),
        )

        try:
            if research_contract_path:
                # NEW: LLM-driven planning
                compact_data = self._compact_research_data(
                    research_contract_path, research_brief_path,
                )
                plan = self._plan_with_llm(scenes, compact_data)
                if agent_dir:
                    write_json(f"{agent_dir}/scene_plan.json", plan)

                scenes_dir = f"{agent_dir}/scenes" if agent_dir else f"{output_dir or 'outputs'}/job_{job_id}"
                Path(scenes_dir).mkdir(parents=True, exist_ok=True)
                assets = self._execute_plan(plan, scenes_dir)
            else:
                # LEGACY: sequential assignment (backward compat)
                urls = source_urls or []
                pexels_videos = self._search_pexels(topic)
                plan = self._plan_scenes(scenes, urls, pexels_videos)
                if agent_dir:
                    write_json(f"{agent_dir}/scene_plan.json", plan)

                scenes_dir = f"{agent_dir}/scenes" if agent_dir else f"{output_dir or 'outputs'}/job_{job_id}"
                Path(scenes_dir).mkdir(parents=True, exist_ok=True)
                assets = self._download_assets(plan, job_id, scenes_dir)

            clips = self._build_provenance(assets)
            output = {"status": "completed", "assets": assets}

            if agent_dir:
                write_json(agent_output_file(assets_cache, job_id, "visual_director"), output)
                write_json(f"{agent_dir}/provenance.json", {
                    "topic": topic,
                    "scene_count": len(plan),
                    "clips": clips,
                })

            logger.info("Visual: completed %d assets", len(assets))
            return output
        except Exception as e:
            logger.exception("Visual: asset sourcing failed")
            return {"status": "failed", "error": str(e), "assets": []}
```

**Step 4: Update `engine.py` to pass research paths**

In `_run_visual_director_phase()` (line ~429), replace URL extraction with path passing:

```python
    def _run_visual_director_phase(
        self, conn: Any, job_id: int, topic: str,
        research_output: dict[str, Any], script_output: dict[str, Any],
        output_dir: str, assets_cache: str,
    ) -> dict[str, Any]:
        """Run Visual Director agent: sources → visual output → complete."""
        mark_agent_running(conn, job_id, "visual_director")

        # Pass research paths — let Visual Director decide what's useful
        research_contract_path = ""
        research_brief_path = ""
        if assets_cache:
            from clipper_agency.core.paths import agent_dir
            rd = agent_dir(assets_cache, job_id, "researcher")
            cp = Path(rd) / "research_contract.json"
            bp = Path(rd) / "research_brief.md"
            if cp.exists():
                research_contract_path = str(cp)
            if bp.exists():
                research_brief_path = str(bp)

        visual_output = self._run_visual_director(
            job_id=job_id, script=script_output.get("script", []),
            topic=topic,
            output_dir=output_dir, assets_cache=assets_cache,
            research_contract_path=research_contract_path,
            research_brief_path=research_brief_path,
        )
        if visual_output.get("status") != "failed":
            self._complete_agent(conn, assets_cache, job_id, "visual_director")
        return visual_output
```

Also add `from pathlib import Path` import at top of engine.py if not present.

**Step 5: Update `_run_visual_director()` to pass through new kwargs**

The `_run_visual_director()` method already has `**kwargs` so it passes through automatically. Verify this is the case at line ~809.

**Step 6: Run all tests**

Run: `.venv/bin/python3 -m pytest -x -q`
Expected: All pass

**Step 7: Commit**

```bash
git add clipper_agency/agents/visual_director.py clipper_agency/orchestrator/engine.py tests/test_agents_visual.py
git commit -m "feat: wire LLM planning into Visual Director execute() and engine"
```

---

### Task 8: Run full test suite + verify coverage

**Step 1: Run full test suite**

Run: `.venv/bin/python3 -m pytest -x -q`
Expected: All pass, 0 failures

**Step 2: Check coverage for visual_director.py**

Run: `.venv/bin/python3 -m pytest --cov=clipper_agency.agents.visual_director tests/ -q`
Expected: Coverage > 85% for visual_director.py

**Step 3: Commit (no changes, just verification)**

If any tests fail: STOP. Report failure. Do NOT auto-fix.

---

### Task Summary

| Task | Files | New Lines | Description |
|---|---|---|---|
| 1 | prompts.py + 4 renames | 1 change | .txt → .md migration |
| 2 | pexels.py | ~20 | Add `search_photos()` |
| 3 | visual_director.md | ~60 | New LLM prompt |
| 4 | visual_director.py | ~30 | `_compact_research_data()` |
| 5 | visual_director.py | ~40 | `_plan_with_llm()` |
| 6 | visual_director.py | ~80 | `_execute_plan()` + `_fetch_image()` |
| 7 | visual_director.py + engine.py | ~30 | Wire up + engine changes |
| 8 | — | 0 | Verification |
| **Total** | **8 files** | **~260 new lines** |

---

## Completion Note

All 8 tasks verified as implemented and merged into `master`. Key evidence:
- `prompts/` — all prompt files are `.md` (Task 1), `visual_director.md` exists with action types (Task 3)
- `pexels.py` — `search_photos()` at line 85 (Task 2)
- `visual_director.py` — `_compact_research_data()` (L178), `_plan_with_llm()` (L222), `_execute_plan()` (L348), `_fetch_image()` (L440) (Tasks 4-6)
- `engine.py` — resolves and passes `research_contract_path`/`research_brief_path` to Visual Director (Task 7)
- `tests/test_agents_visual.py` — `TestCompactResearchData`, `TestPlanWithLLM`, `TestExecutePlan`, `TestLLMPlanningIntegration` all passing (Task 8)
- **642 offline tests pass** (2 deselected, same as baseline) |
