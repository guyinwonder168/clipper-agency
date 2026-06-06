# Visual Director Enhancement — Implementation Plan ✅ COMPLETED

> **Tier 2 complete.** Merged to master via PR #34. 695 tests passing, 93% coverage, SonarCloud Quality Gate PASSED.
>
> **Prerequisite:** Complete study of `tanersener/ffmpeg-video-slideshow-scripts` and `editly` repos (see Task 0) before starting Tasks 1-6. This gives us real FFmpeg filter graph knowledge to bake into the Visual Director prompt.

**Goal:** Transform Visual Director from a simple image-picker into a video production expert that understands FPS rules, scene treatments, transitions, pacing, and outputs rich visual directives that Composer can render.

**Architecture:** Three-layer enhancement: (1) Enrich the Visual Director's output contract with treatment/duration/transition metadata, (2) Rewrite the Visual Director's prompt file to include video production expertise (FPS, pacing, treatments, transitions), (3) Update Composer to read and route on the new treatment fields. Data-driven treatment templates stored as YAML configs.

**Tech Stack:** Python 3.11+, FFmpeg filter graphs (zoompan, drawtext, xfade, fade), YAML treatment templates, pytest + mocker

**Branch:** `phase/18-visual-director-enhancement` (create from latest master after Tier 1 merge)

**Depends on:** Tier 1 (`fix/scene-normalizer-framerate`) must be merged first — this plan extends the normalizer's fps awareness and image handling.

---

## Chunk 0: Research Phase (Pre-Implementation)

### Task 0: Study FFmpeg Video Techniques from Reference Repos

**Goal:** Extract practical FFmpeg filter knowledge from `tanersener/ffmpeg-video-slideshow-scripts` and `editly` that can be baked into the Visual Director's prompt and treatment templates.

**Deliverable:** A knowledge document at `docs/research/ffmpeg-visual-techniques.md` containing:

- [x] **Step 1: Study `tanersener/ffmpeg-video-slideshow-scripts`** ✅
  - Clone/study repo, focus on `advanced_video_scripts/`
  - Extract: zoompan parameters (speed, direction), text animation (moving text, fade-in), transitions (crossfade, wipe), overlay positioning
  - Document the FFmpeg filter chains as reusable patterns

- [x] **Step 2: Study `mifi/editly`** ✅
  - Study the declarative JSON/JS spec format
  - Extract: how it defines clips, layers, transitions, text, audio
  - Document: what "treatment types" map to what FFmpeg filters

- [x] **Step 3: Study `NapoleonWils0n/ffmpeg-scripts` (xfade transitions)** ✅
  - Extract: crossfade, xfade transition types available
  - Document: transition names, durations, FFmpeg filter syntax

- [x] **Step 4: Compile knowledge into `docs/research/ffmpeg-visual-techniques.md`** ✅

  Structure:
  ```
  ## Scene Treatments
  ### ken_burns_zoom_in
  - FFmpeg: zoompan=z='min(zoom+0.001,1.2)':...
  - Duration: 3-7s
  - Use: still images, photos
  
  ### ken_burns_pan_left
  - FFmpeg: zoompan=x='...'
  - Duration: 3-7s
  - Use: wide photos, landscapes
  
  ### lower_third_slide
  - FFmpeg: drawtext=x='if(lt(t,1),-500,20)':...
  - Duration: 2-4s overlay
  - Use: artist names, attribution
  
  ## Transitions
  ### crossfade
  - FFmpeg: xfade=transition=fade:duration=0.5:offset=...
  - Use: default between related scenes
  
  ### wipe_left
  - FFmpeg: xfade=transition=wipeleft:duration=0.5:offset=...
  - Use: topic changes
  
  ## FPS Rules
  - TikTok standard: 30fps
  - All scenes unified before concat
  - Images: zoompan at 30fps, duration 3-7s
  ```
- [x] **Step 5: Commit**

```bash
git add docs/research/ffmpeg-visual-techniques.md
git commit -m "docs: add FFmpeg visual techniques research for Visual Director enhancement"
```

---

## Chunk 1: Treatment Templates (YAML Config)

### Task 1: Create treatment template YAML definitions

**Files:**
- Create: `templates/treatments.yaml`
- Test: `tests/test_treatment_templates.py`

- [x] **Step 1: Write the failing test**

```python
"""Tests for treatment template definitions."""
import pytest
import yaml
from pathlib import Path

TEMPLATES_PATH = Path("templates/treatments.yaml")


class TestTreatmentTemplates:
    def test_treatments_file_exists(self):
        assert TEMPLATES_PATH.is_file(), "templates/treatments.yaml must exist"

    def test_treatments_is_valid_yaml(self):
        data = yaml.safe_load(TEMPLATES_PATH.read_text())
        assert isinstance(data, dict)
        assert "treatments" in data

    def test_required_treatments_defined(self):
        data = yaml.safe_load(TEMPLATES_PATH.read_text())
        treatments = data["treatments"]
        required = [
            "ken_burns_zoom_in",
            "ken_burns_pan_left",
            "lower_third_slide",
            "text_card_reveal",
            "cinematic_crop",
            "fade_to_black",
            "hook_big_caption",
        ]
        for name in required:
            assert name in treatments, f"Missing treatment: {name}"

    def test_each_treatment_has_required_fields(self):
        data = yaml.safe_load(TEMPLATES_PATH.read_text())
        for name, treatment in data["treatments"].items():
            assert "description" in treatment, f"{name} missing description"
            assert "target_fps" in treatment, f"{name} missing target_fps"
            assert "default_duration" in treatment, f"{name} missing default_duration"
            assert "input_type" in treatment, f"{name} missing input_type"
            assert treatment["input_type"] in ("image", "video", "text", "any")
            assert treatment["target_fps"] == 30, f"{name} target_fps must be 30"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_treatment_templates.py -v`
Expected: ALL FAIL — `templates/treatments.yaml` does not exist

- [x] **Step 3: Create `templates/treatments.yaml`**

```yaml
# Visual treatment templates for scene rendering.
# Each treatment defines how a visual asset is processed by Composer.
# All treatments output 30fps for TikTok concat compatibility.

treatments:
  # --- Image treatments ---
  ken_burns_zoom_in:
    description: "Slow zoom into center of image, 3-7s duration. Classic Ken Burns effect."
    target_fps: 30
    default_duration: 5
    input_type: image
    ffmpeg_filter: "zoompan=z='min(zoom+0.001,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30"
    notes: "Zoom speed 0.001 per frame. Reaches 1.2x zoom. Calm, professional."

  ken_burns_pan_left:
    description: "Slow pan from right to left across image. Good for wide/landscape photos."
    target_fps: 30
    default_duration: 5
    input_type: image
    ffmpeg_filter: "zoompan=z='1.05':x='iw/2-(iw/zoom/2)+on*({frames_w})':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30"
    notes: "zoom=1.05 (very mild), pans left. {frames_w} = (iw-iw/zoom)/{frames}."

  # --- Video treatments ---
  cinematic_crop:
    description: "Crop landscape video to 9:16 vertical, center-biased."
    target_fps: 30
    default_duration: null  # uses source duration
    input_type: video
    ffmpeg_filter: "crop=ih*9/16:ih,scale=1080:1920"
    notes: "Crops center column of landscape video for vertical TikTok."

  broll_standard:
    description: "Standard B-roll: trim to target duration, apply 30fps, strip audio."
    target_fps: 30
    default_duration: null  # uses source duration
    input_type: video
    ffmpeg_filter: null  # normalizer handles this
    notes: "Basic normalization. No special effects."

  slow_motion:
    description: "50% slow motion from 60fps source. Dramatic moments only."
    target_fps: 30
    default_duration: null
    input_type: video
    ffmpeg_filter: "setpts=2.0*PTS"
    notes: "Requires 60fps source. Output is half-speed. Use sparingly."

  # --- Text overlay treatments ---
  lower_third_slide:
    description: "Name/title overlay sliding in from left. Artist names, attribution."
    target_fps: 30
    default_duration: 3
    input_type: text
    ffmpeg_filter: "drawtext=text='{text}':fontfile={font}:fontsize=48:fontcolor=white:x='if(lt(t,0.5),-500-w,20)':y=h-150:box=1:boxcolor=black@0.6:boxborderw=10"
    notes: "Slides in over 0.5s, stays for duration. Semi-transparent black box behind text."

  text_card_reveal:
    description: "Full-screen text card with fade-in text reveal."
    target_fps: 30
    default_duration: 4
    input_type: text
    ffmpeg_filter: "drawtext=text='{text}':fontfile={font}:fontsize=72:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:alpha='if(lt(t,1),t,1)'"
    notes: "Text fades in over 1s. Centered. Usually over blurred image background."

  hook_big_caption:
    description: "Opening hook: large text over blurred background. GRABS ATTENTION in first 1-3s."
    target_fps: 30
    default_duration: 3
    input_type: text
    ffmpeg_filter: "drawtext=text='{text}':fontfile={font}:fontsize=80:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:borderw=4:bordercolor=black"
    notes: "Large centered text with black border for readability. Always scene 1."

  fade_to_black:
    description: "Closing scene: fade video to black over 1s."
    target_fps: 30
    default_duration: null
    input_type: video
    ffmpeg_filter: "fade=t=out:st={duration}-1:d=1"
    notes: "Applied to final scene only. 1-second fade to black."


# --- Transition templates ---
transitions:
  crossfade:
    description: "Smooth blend between scenes. Default transition."
    ffmpeg_xfade: "fade"
    default_duration: 0.5

  hard_cut:
    description: "Instant cut. For punch emphasis or topic change."
    ffmpeg_xfade: null
    default_duration: 0

  wipe_left:
    description: "Wipe from right to left. Timeline/progression feel."
    ffmpeg_xfade: "wipeleft"
    default_duration: 0.5

  dissolve:
    description: "Slow dissolve. Sentimental or dramatic moments."
    ffmpeg_xfade: "dissolve"
    default_duration: 1.0

  circle_open:
    description: "Circle wipe opening. Playful reveal effect."
    ffmpeg_xfade: "circleopen"
    default_duration: 0.5


# --- FPS Rules (for Visual Director prompt) ---
fps_rules:
  target_fps: 30
  rules:
    - "ALL scenes must be 30fps before FFmpeg concat — no exceptions."
    - "Stock footage varies (24/25/30/50/60) — normalizer handles unification."
    - "Images converted to video at 30fps with zoompan animation, duration 3-7s."
    - "60fps source at 30fps output = 50% slow-mo (dramatic effect only)."
    - "Mixed fps in concat = massive frame duplication → FFmpeg appears hung."

# --- Pacing Rules (for Visual Director prompt) ---
pacing_rules:
  tiktok_standard:
    - "Hook: first 1-3 seconds MUST grab attention."
    - "Scene changes every 2-5 seconds for TikTok attention span."
    - "No scene shorter than 2s (except intentional fast cuts)."
    - "Images: 3-7s with Ken Burns motion."
    - "Videos: trim to scene-relevant portion, 3-10s max."
    - "Closing: fade to black over 1s."
```

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_treatment_templates.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add templates/treatments.yaml tests/test_treatment_templates.py
git commit -m "feat: add treatment template YAML definitions for visual rendering"
```

---

## Chunk 2: Enhanced Visual Director Prompt

### Task 2: Rewrite Visual Director prompt with video production expertise

**Files:**
- Modify: `prompts/visual_director.md`
- Test: `tests/test_visual_director_prompt.py` (verify prompt loads + contains required sections)

The prompt becomes the Director's "video expertise brain" — it teaches the LLM about FPS, pacing, treatments, and transitions.

- [x] **Step 1: Write the failing test**

```python
"""Tests for Visual Director prompt — must contain video production knowledge."""
from pathlib import Path
from clipper_agency.agents.prompts import load_prompt, PROMPTS_DIR


class TestVisualDirectorPrompt:
    def test_prompt_loads_without_error(self):
        text = load_prompt("visual_director", "", PROMPTS_DIR)
        assert len(text) > 200

    def test_prompt_contains_fps_rules(self):
        text = load_prompt("visual_director", "", PROMPTS_DIR)
        assert "30fps" in text
        assert "framerate" in text.lower()

    def test_prompt_contains_treatment_knowledge(self):
        text = load_prompt("visual_director", "", PROMPTS_DIR)
        assert "ken_burns" in text or "zoompan" in text
        assert "treatment" in text.lower()

    def test_prompt_contains_transition_knowledge(self):
        text = load_prompt("visual_director", "", PROMPTS_DIR)
        assert "transition" in text.lower()
        assert "crossfade" in text

    def test_prompt_contains_pacing_rules(self):
        text = load_prompt("visual_director", "", PROMPTS_DIR)
        assert "pacing" in text.lower() or "2-5" in text or "attention" in text.lower()

    def test_prompt_output_includes_treatment_field(self):
        text = load_prompt("visual_director", "", PROMPTS_DIR)
        assert '"treatment"' in text

    def test_prompt_output_includes_duration_field(self):
        text = load_prompt("visual_director", "", PROMPTS_DIR)
        assert '"target_duration"' in text

    def test_prompt_output_includes_transition_field(self):
        text = load_prompt("visual_director", "", PROMPTS_DIR)
        assert '"transition_in"' in text
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_visual_director_prompt.py -v`
Expected: ALL FAIL — current prompt lacks video knowledge sections

- [x] **Step 3: Rewrite `prompts/visual_director.md`**

```markdown
You are a Visual Director for {content_angle} content in {language}.
You are a VIDEO PRODUCTION EXPERT who understands framing, pacing, transitions, FPS rules, and visual storytelling for TikTok/shorts.

## Your Role

You are NOT just picking images. You are DIRECTING the entire visual experience:
- You decide the TREATMENT for each scene (how it looks and moves)
- You control PACING (how long each scene lasts)
- You choose TRANSITIONS (how scenes flow into each other)
- You understand FPS (all output must be 30fps)

## Input

You receive:
1. **Scenes** from the scriptwriter (voiceover text, timing)
2. **Video sources** with engagement metrics (plays, likes, shares)
3. **Context sources** (news headlines, background info)
4. **Research brief** (key facts, viral rankings, content suggestions)

## FPS Rules (MANDATORY)

- **ALL output is 30fps** — this is non-negotiable for TikTok concat compatibility.
- Stock footage comes in 24/25/30/50/60fps — the normalizer handles unification, but YOU must know this.
- **Images → video**: converted at 30fps with Ken Burns zoompan animation, duration 3-7s.
- **Never** output scenes at mixed framerates — this causes FFmpeg to hang.
- 60fps source → 30fps output = 50% slow-motion (use sparingly for dramatic moments).

## Pacing Rules

- **Hook (scene 1)**: Must grab attention in first 1-3 seconds. Use big caption or striking visual.
- **Scene changes**: Every 2-5 seconds for TikTok attention span.
- **Minimum scene duration**: 2 seconds (except intentional fast cuts).
- **Image scenes**: 3-7 seconds with Ken Burns motion.
- **Video scenes**: Trim to relevant portion, 3-10s max.
- **Closing**: Use `fade_to_black` treatment on final scene.

## Available Treatments

Each scene gets a `treatment` — the visual recipe for how it appears:

### For Images (pexels_image, text_card backgrounds)
- `ken_burns_zoom_in` — Slow zoom into center. Calm, professional. **Default for images.**
- `ken_burns_pan_left` — Pan across wide photos. Good for landscapes/groups.

### For Videos (tiktok_clip, pexels_video)
- `broll_standard` — Normal playback. No special effects. **Default for videos.**
- `cinematic_crop` — Landscape video cropped to 9:16 vertical.
- `slow_motion` — 50% speed. Dramatic moments only (requires 60fps source).

### For Text (text_card)
- `hook_big_caption` — Large text over blurred background. **Always use for scene 1.**
- `text_card_reveal` — Fade-in text reveal. Good for quotes/facts.
- `lower_third_slide` — Name/title overlay sliding in from left. For attribution.

### For Closing
- `fade_to_black` — Fade to black over 1s. **Always use for last scene.**

## Transitions

Choose how each scene connects to the next:
- `crossfade` — Smooth blend. **Default** between related scenes.
- `hard_cut` — Instant cut. For punch emphasis or topic change.
- `wipe_left` — Wipe right-to-left. Timeline/progression feel.
- `dissolve` — Slow dissolve. Sentimental/dramatic moments.

## Output Format

Return ONLY valid JSON:
```json
{{
  "scenes": [
    {{
      "scene_number": 1,
      "reasoning": "Why this visual + treatment choice",
      "action": {{
        "type": "tiktok_clip",
        "source_url": "tiktok URL here"
      }},
      "fallback": {{
        "type": "pexels_video",
        "search_query": "descriptive search term"
      }},
      "treatment": "hook_big_caption",
      "target_duration": 3,
      "transition_in": "hard_cut",
      "transition_out": "crossfade"
    }}
  ]
}}
```

## Treatment Selection Rules

1. **Scene 1 (hook)**: Always use `hook_big_caption` or striking visual. Transition: `hard_cut`.
2. **Image scenes**: Default to `ken_burns_zoom_in`. Duration 3-7s.
3. **Video scenes**: Default to `broll_standard` or `cinematic_crop` if landscape.
4. **Artist names**: Use `lower_third_slide` overlay on the scene.
5. **Key facts/quotes**: Use `text_card_reveal` treatment.
6. **Final scene**: Always use `fade_to_black`. Transition: `crossfade`.
7. **Topic change**: Use `hard_cut` or `wipe_left` transition.

## Action Types

- `tiktok_clip`: TikTok video. Requires `source_url`.
- `pexels_video`: Stock video. Requires `search_query`.
- `pexels_image`: Stock image (gets Ken Burns animation). Requires `search_query`.
- `text_card`: Headline card with image. Requires `headline`, `image_search`, `style`.

## Text Card Fields
- `headline`: Bold text (short, punchy)
- `subtitle`: Secondary text (optional)
- `style`: `news_card` | `speech_bubble` | `breaking_news` | `mock_ui`
- `image_search`: Pexels search query for background image
- `bg_color`: `gradient_red` | `gradient_purple` | `gradient_blue` (optional)
- `border_color`: `brand` (optional)

## Rules

- ALWAYS include a `fallback` for every scene.
- ALWAYS include `treatment`, `target_duration`, `transition_in`, and `transition_out`.
- Prioritize high-engagement video clips (check plays/likes/shares).
- Match scene tone to visual style (scandal=red, legal=blue, viral=purple).
- Never assign a TikTok URL if no relevant video exists for that scene.
- Generate specific, descriptive search queries — not generic terms.
- Every text_card must have `image_search` filled in.

## Safety

{safety_rules_text}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_visual_director_prompt.py -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add prompts/visual_director.md tests/test_visual_director_prompt.py
git commit -m "feat: rewrite visual director prompt with video production expertise"
```

---

## Chunk 3: Enhanced Output Contract

### Task 3: Update Visual Director output contract with treatment metadata

**Files:**
- Modify: `clipper_agency/agents/visual_director.py` (`_execute_plan()`, `_execute_action()`)
- Test: `tests/test_visual_director.py`

The Director must pass through `treatment`, `target_duration`, and `transition` fields from the LLM plan into the final assets dict.

- [x] **Step 1: Write the failing test**

```python
def test_execute_plan_includes_treatment_metadata(self):
    """LLM plan with treatment/duration/transition fields should pass through to assets."""
    plan = [
        {
            "scene_number": 1,
            "action": {"type": "text_card", "headline": "Test", "image_search": "test", "style": "news_card"},
            "fallback": None,
            "treatment": "hook_big_caption",
            "target_duration": 3,
            "transition_in": "hard_cut",
            "transition_out": "crossfade",
        },
        {
            "scene_number": 2,
            "action": {"type": "pexels_image", "search_query": "concert"},
            "fallback": None,
            "treatment": "ken_burns_zoom_in",
            "target_duration": 5,
            "transition_in": "crossfade",
            "transition_out": "crossfade",
        },
    ]
    # Mock _execute_action to return simple results
    agent = VisualDirectorAgent()
    mocker.patch.object(agent, "_execute_action", side_effect=[
        {"source": "text_card", "path": "", "headline": "Test", "style": "news_card"},
        {"source": "pexels_image", "path": "/tmp/scene_2_img.jpg"},
    ])

    assets = agent._execute_plan(plan, "/tmp/scenes")

    assert assets[0]["treatment"] == "hook_big_caption"
    assert assets[0]["target_duration"] == 3
    assert assets[0]["transition_in"] == "hard_cut"
    assert assets[0]["transition_out"] == "crossfade"
    assert assets[1]["treatment"] == "ken_burns_zoom_in"
    assert assets[1]["target_duration"] == 5
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python3 -m pytest tests/test_visual_director.py::test_execute_plan_includes_treatment_metadata -v`
Expected: FAIL — assets don't include treatment fields

- [x] **Step 3: Update `_execute_plan()` to pass through treatment metadata**

In `visual_director.py`, update the `_execute_plan()` method to merge treatment fields into each asset:

```python
    def _execute_plan(self, plan: list[dict], scenes_dir: str) -> list[dict]:
        """Execute the LLM-generated visual plan with fallback chain."""
        pexels = PexelsService()
        ytdlp = YtDlpService()
        Path(scenes_dir).mkdir(parents=True, exist_ok=True)

        assets: list[dict] = []
        for item in plan:
            scene_id = item["scene_number"]
            action = item.get("action", {})
            fallback = item.get("fallback")
            result = self._execute_action(action, scene_id, scenes_dir, pexels, ytdlp)

            if result is None and fallback:
                logger.info("Scene %d: primary failed, using fallback", scene_id)
                result = self._execute_action(fallback, scene_id, scenes_dir, pexels, ytdlp)

            if result:
                asset = {"scene": scene_id, **result}
            else:
                asset = {"scene": scene_id, "source": "none", "path": ""}

            # Pass through treatment metadata from LLM plan
            for field in ("treatment", "target_duration", "transition_in", "transition_out"):
                if field in item:
                    asset[field] = item[field]

            assets.append(asset)

        return assets
```

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python3 -m pytest tests/test_visual_director.py::test_execute_plan_includes_treatment_metadata -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add clipper_agency/agents/visual_director.py tests/test_visual_director.py
git commit -m "feat: pass through treatment/duration/transition metadata in visual director output"
```

---

### Task 4: Add default treatment values when LLM omits them

**Files:**
- Modify: `clipper_agency/agents/visual_director.py` (add `_apply_default_treatment()`)
- Test: `tests/test_visual_director.py`

The LLM may not always include treatment fields. We need sensible defaults based on asset source type.

- [x] **Step 1: Write the failing test**

```python
def test_default_treatment_for_image_is_ken_burns(self):
    """Image assets without treatment get ken_burns_zoom_in by default."""
    agent = VisualDirectorAgent()
    asset = {"scene": 1, "source": "pexels_image", "path": "/tmp/scene_1.jpg"}
    result = agent._apply_default_treatment(asset)
    assert result["treatment"] == "ken_burns_zoom_in"
    assert result["target_duration"] == 5
    assert "transition_in" in result
    assert "transition_out" in result

def test_default_treatment_for_video_is_broll(self):
    """Video assets without treatment get broll_standard by default."""
    agent = VisualDirectorAgent()
    asset = {"scene": 2, "source": "tiktok_clip", "path": "/tmp/scene_2.mp4"}
    result = agent._apply_default_treatment(asset)
    assert result["treatment"] == "broll_standard"

def test_default_treatment_for_text_card_is_reveal(self):
    """Text card assets without treatment get text_card_reveal by default."""
    agent = VisualDirectorAgent()
    asset = {"scene": 3, "source": "text_card", "path": "", "headline": "Test"}
    result = agent._apply_default_treatment(asset)
    assert result["treatment"] == "text_card_reveal"
    assert result["target_duration"] == 4
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python3 -m pytest tests/test_visual_director.py -k "default_treatment" -v`
Expected: ALL FAIL — `_apply_default_treatment()` doesn't exist

- [x] **Step 3: Implement `_apply_default_treatment()`**

```python
    _IMAGE_SOURCES = frozenset({"pexels_image"})
    _VIDEO_SOURCES = frozenset({"tiktok_clip", "pexels_video", "tiktok", "pexels"})

    def _apply_default_treatment(self, asset: dict) -> dict:
        """Fill in missing treatment metadata with sensible defaults."""
        source = asset.get("source", "")

        defaults = {
            "transition_in": "crossfade",
            "transition_out": "crossfade",
        }

        if source in self._IMAGE_SOURCES:
            defaults["treatment"] = "ken_burns_zoom_in"
            defaults["target_duration"] = 5
        elif source in self._VIDEO_SOURCES:
            defaults["treatment"] = "broll_standard"
            defaults["target_duration"] = 5
        elif source == "text_card":
            defaults["treatment"] = "text_card_reveal"
            defaults["target_duration"] = 4
        else:
            defaults["treatment"] = "broll_standard"
            defaults["target_duration"] = 5

        for key, value in defaults.items():
            asset.setdefault(key, value)

        return asset
```

Update `_execute_plan()` to call `_apply_default_treatment()` after building the asset:

```python
            asset = self._apply_default_treatment(asset)
            assets.append(asset)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python3 -m pytest tests/test_visual_director.py -k "default_treatment" -v`
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add clipper_agency/agents/visual_director.py tests/test_visual_director.py
git commit -m "feat: add default treatment values for assets without LLM-specified treatments"
```

---

## Chunk 4: Composer Reads Treatment Metadata

### Task 5: Update Composer to use treatment field from assets

**Files:**
- Modify: `clipper_agency/agents/composer.py` (`_process_scene()`, normalization routing)
- Test: `tests/test_composer.py`

Composer currently normalizes everything the same way. After this task, it routes on `treatment`:
- `ken_burns_*` → image normalization (zoompan)
- `broll_standard` / `cinematic_crop` → video normalization with `-r 30`
- `text_card_reveal` / `hook_big_caption` → card generation + treatment applied

- [x] **Step 1: Write the failing test**

```python
def test_composer_routes_image_treatment_to_image_normalizer(self, tmp_path, mocker):
    """Asset with treatment=ken_burns_zoom_in routes to image normalization path."""
    mocker.patch("clipper_agency.core.scene_normalizer.SceneNormalizer.normalize",
                  return_value=NormalizeResult(path="out.mp4", success=True))
    # ... setup composer with asset that has treatment="ken_burns_zoom_in"
    # Assert normalizer received the image path and output path correctly
```

```python
def test_composer_preserves_treatment_in_output(self, tmp_path, mocker):
    """Composer preserves treatment metadata from visual director in its output."""
    # ... setup and run composer with assets containing treatment fields
    # Assert output metadata includes treatment field
```

- [x] **Step 2: Run tests to verify they fail**

- [x] **Step 3: Update Composer's `_process_scene()` to read `treatment`**

In `composer.py`, update `_process_scene()` to check the asset's `treatment` field and route accordingly. The normalizer already handles image detection by extension (from Tier 1), so the main change is:

1. Read `treatment` from asset dict
2. Pass it through to output metadata
3. Use `target_duration` from asset if available (for image duration)

- [x] **Step 4: Run tests to verify they pass**

- [x] **Step 5: Commit**

```bash
git add clipper_agency/agents/composer.py tests/test_composer.py
git commit -m "feat: composer reads treatment metadata from visual director assets"
```

---

### Task 6: Full integration verification — ✅ COMPLETE

- [x] **Step 1: Run full offline test suite** — 695 passed, 2 deselected in 51.41s ✅
- [x] **Step 2: Run coverage check** — 93% (3297 statements, 190 missing) ✅
- [x] **Step 3: Update AGENTS.md** — Repository State updated to reflect Phase 18 completion ✅

**Phase 18 complete.** All 6 tasks across 4 batches implemented and verified.

---

## Summary of Changes

| File | Change |
|------|--------|
| `docs/research/ffmpeg-visual-techniques.md` | NEW — FFmpeg filter knowledge from research repos |
| `templates/treatments.yaml` | NEW — treatment + transition definitions |
| `prompts/visual_director.md` | REWRITE — video production expertise, treatment rules, FPS knowledge |
| `clipper_agency/agents/visual_director.py` | Pass through treatment metadata, add `_apply_default_treatment()` |
| `clipper_agency/agents/composer.py` | Read treatment metadata, route normalization |
| `tests/test_treatment_templates.py` | NEW — treatment YAML validation |
| `tests/test_visual_director_prompt.py` | NEW — prompt knowledge verification |
| `tests/test_visual_director.py` | Updated — treatment metadata tests |
| `tests/test_composer.py` | Updated — treatment routing tests |

**Execution order:** Task 0 (research) → Tasks 1-4 (can partially parallel: 1+2 independent, 3+4 depend on 2) → Task 5 (depends on 3+4) → Task 6 (verification)

---
