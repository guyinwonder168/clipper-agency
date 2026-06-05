# Phase 15a Template Rendering Implementation Plan ✅ COMPLETED

> **Status:** All 17 tasks completed, 3 PRs merged to master. Template-driven rendering engine with YAML templates, 3 adapters (News Card, B-Roll Narration, Rapid Update), FFmpeg filter chains, and Composer integration.

**Goal:** Build template-driven MVP rendering for News Card, B-Roll Narration, and Rapid Update templates with deterministic offline tests, Composer integration, diagnostics, and documentation traceability.

**Architecture:** Add a focused `clipper_agency/rendering/` package with strict YAML template loading, typed render contracts, shared rendering primitives, Pillow thumbnail/card generation, a standalone FFmpeg render engine, and thin per-template adapters. Integrate the renderer into Composer only after adapters are covered by deterministic tests, preserving the fixed job-owned output contract and Sonar-safe path handling.

**Tech Stack:** Python 3.11+, Pydantic, PyYAML, Pillow, FFmpeg/ffprobe, pytest, existing `clipper_agency.core` artifact/path/media helpers. No new runtime dependencies.

---

## Pre-Work Rules

- Work only on a feature branch; never commit directly to `master`.
- Use the project virtualenv for all Python commands: `.venv/bin/python3 -m ...`.
- Keep changes surgical and TDD-first.
- Do not add new rendering frameworks or external APIs.
- Keep all filesystem access on application-owned paths:
  - final outputs under `output_dir/job_{job_id}/`
  - diagnostics under `assets_cache/job_{job_id}/agents/composer/`
  - tests under `tmp_path` or repository fixtures
- Preserve the existing package contract: final package contains `video.mp4`, `caption.txt`, `thumbnail.png`, and `metadata.json`.

## Branch and PR Plan

1. PR 1 branch: `phase/15a-template-foundation`
2. PR 2 branch: `phase/15a-template-adapters`
3. PR 3 branch: `phase/15a-composer-template-integration`

Each PR should run its targeted tests before commit and the offline suite before opening/merging the PR:

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected result: all offline tests pass; external/integration-marked tests are deselected.

---

## PR 1 — Template Foundation

Branch: `phase/15a-template-foundation`

Purpose: create the reusable template loading, contracts, primitives, and asset-generation foundation without Composer integration.

### Task 1: Add strict rendering template loader ✅

**Files:**
- Create: `clipper_agency/rendering/__init__.py`
- Create: `clipper_agency/rendering/templates.py`
- Test: `tests/test_rendering_templates.py`

**Step 1: Write failing template-loader tests**

Add tests covering valid templates, unknown template names, malformed template names, missing files, and invalid schema.

Example test shape:

```python
from pathlib import Path

import pytest

from clipper_agency.rendering.templates import TemplateLoadError, load_render_template


def test_load_render_template_reads_existing_yaml():
    template = load_render_template("news_card", Path("templates"))

    assert template.name == "news_card"
    assert template.type == "news_card"
    assert template.layout.resolution == "1080x1920"
    assert template.transitions.type == "fade"


def test_load_render_template_rejects_path_like_name():
    with pytest.raises(TemplateLoadError, match="Invalid template name"):
        load_render_template("../news_card", Path("templates"))
```

**Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_rendering_templates.py -v
```

Expected: FAIL because `clipper_agency.rendering.templates` does not exist.

**Step 3: Implement minimal loader**

Implement `load_render_template(template_name: str, templates_dir: Path | str = Path("templates")) -> RenderTemplateConfig`.

Requirements:
- Accept only names matching `^[a-z][a-z0-9_]*$`.
- Build the path internally as `templates_dir / f"{template_name}.yaml"`.
- Use `yaml.safe_load`.
- Raise `TemplateLoadError` with actionable messages.
- Do not accept arbitrary template file paths from callers.

Minimal implementation shape:

```python
from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError


_TEMPLATE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class TemplateLoadError(ValueError):
    """Raised when a render template cannot be loaded or validated."""


class TemplateLayout(BaseModel):
    resolution: str = "1080x1920"
    background_color: str | None = None
    title_font_size: int | None = None
    subtitle_font_size: int | None = None
    caption_position: str | None = None
    caption_style: str | None = None
    clip_duration: str | None = None


class TemplateTransition(BaseModel):
    type: str = "cut"
    duration: str = "0s"


class RenderTemplateConfig(BaseModel):
    name: str
    type: str
    style: str | None = None
    description: str | None = None
    layout: TemplateLayout = Field(default_factory=TemplateLayout)
    transitions: TemplateTransition = Field(default_factory=TemplateTransition)


def load_render_template(
    template_name: str,
    templates_dir: Path | str = Path("templates"),
) -> RenderTemplateConfig:
    if not _TEMPLATE_NAME_PATTERN.fullmatch(template_name):
        raise TemplateLoadError(f"Invalid template name: {template_name!r}")

    template_path = Path(templates_dir) / f"{template_name}.yaml"
    if not template_path.is_file():
        raise TemplateLoadError(f"Template not found: {template_name}")

    try:
        data = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
        return RenderTemplateConfig.model_validate(data)
    except (OSError, ValidationError, yaml.YAMLError) as exc:
        raise TemplateLoadError(f"Invalid template {template_name}: {exc}") from exc
```

**Step 4: Run tests and verify they pass**

Run:

```bash
.venv/bin/python3 -m pytest tests/test_rendering_templates.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/rendering/__init__.py clipper_agency/rendering/templates.py tests/test_rendering_templates.py
git commit -m "feat: add render template loader"
```

---

### Task 2: Add render contract models ✅

**Files:**
- Create: `clipper_agency/rendering/contracts.py`
- Modify: `clipper_agency/rendering/__init__.py`
- Test: `tests/test_rendering_contracts.py`

**Step 1: Write failing contract tests**

Cover render scene, overlay, caption, thumbnail config, render plan serialization, and boundary validation.

Example:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipper_agency.rendering.contracts import CaptionOverlay, RenderPlan, RenderScene


def test_render_plan_serializes_static_paths_as_strings(tmp_path):
    scene = RenderScene(
        source_path=tmp_path / "scene.mp4",
        duration_seconds=3.0,
        captions=[CaptionOverlay(text="Halo", start_seconds=0.0, end_seconds=1.0)],
    )

    plan = RenderPlan(template_name="news_card", scenes=[scene])

    assert plan.model_dump(mode="json")["template_name"] == "news_card"
    assert plan.model_dump(mode="json")["scenes"][0]["source_path"].endswith("scene.mp4")


def test_caption_overlay_rejects_negative_time():
    with pytest.raises(ValidationError):
        CaptionOverlay(text="bad", start_seconds=-1.0, end_seconds=1.0)
```

**Step 2: Run tests and verify they fail**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_contracts.py -v
```

Expected: FAIL because contracts do not exist.

**Step 3: Implement minimal contracts**

Suggested models:
- `CaptionOverlay(text, start_seconds, end_seconds, position="bottom", style="default")`
- `VisualOverlay(text, kind="lower_third", start_seconds=0.0, end_seconds=None)`
- `RenderScene(source_path, duration_seconds, captions=[], overlays=[], transition="cut")`
- `ThumbnailConfig(title, subtitle=None, template_name, output_path=None)`
- `RenderPlan(template_name, scenes, thumbnail=None, metadata={})`
- `RenderResult(video_path, thumbnail_path, render_plan_path=None, diagnostics_dir=None)`

Validation requirements:
- durations are positive
- start times are non-negative
- `end_seconds > start_seconds` when both are present
- metadata defaults are immutable via `Field(default_factory=dict)`
- lists default with `Field(default_factory=list)`

**Step 4: Run tests and verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_contracts.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/rendering/__init__.py clipper_agency/rendering/contracts.py tests/test_rendering_contracts.py
git commit -m "feat: add render contract models"
```

---

### Task 3: Add shared rendering primitives ✅

**Files:**
- Create: `clipper_agency/rendering/primitives.py`
- Test: `tests/test_rendering_primitives.py`

**Step 1: Write failing primitive tests**

Cover caption splitting, FFmpeg-safe drawtext escaping, lower-third overlay creation, and transition metadata.

Example:

```python
from clipper_agency.rendering.primitives import escape_drawtext, make_caption_overlays


def test_escape_drawtext_escapes_ffmpeg_special_chars():
    assert escape_drawtext("A:B's 100%") == r"A\:B\'s 100%"


def test_make_caption_overlays_splits_words_across_duration():
    captions = make_caption_overlays("satu dua tiga empat", duration_seconds=4.0)

    assert [caption.text for caption in captions] == ["satu dua tiga", "empat"]
    assert captions[0].start_seconds == 0.0
    assert captions[-1].end_seconds == 4.0
```

**Step 2: Run tests and verify they fail**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_primitives.py -v
```

Expected: FAIL because primitives do not exist.

**Step 3: Implement minimal primitives**

Add pure functions only. Suggested functions:
- `escape_drawtext(text: str) -> str`
- `make_caption_overlays(text: str, duration_seconds: float, words_per_caption: int = 5, position: str = "bottom", style: str = "default") -> list[CaptionOverlay]`
- `make_lower_third(text: str, duration_seconds: float) -> VisualOverlay`
- `transition_for_template(template: RenderTemplateConfig) -> str`

Keep functions deterministic and free of filesystem side effects.

**Step 4: Run tests and verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_primitives.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/rendering/primitives.py tests/test_rendering_primitives.py
git commit -m "feat: add render primitives"
```

---

### Task 4: Add thumbnail/card generator wrapper ✅

**Files:**
- Create: `clipper_agency/rendering/thumbnails.py`
- Test: `tests/test_rendering_thumbnails.py`

**Step 1: Write failing thumbnail tests**

Cover template-specific thumbnail generation, deterministic dimensions, text fallback, and output path creation under caller-owned directory.

Example:

```python
from PIL import Image

from clipper_agency.rendering.contracts import ThumbnailConfig
from clipper_agency.rendering.thumbnails import generate_template_thumbnail


def test_generate_template_thumbnail_creates_1080x1920_png(tmp_path):
    output = tmp_path / "thumbnail.png"
    config = ThumbnailConfig(
        template_name="news_card",
        title="Judul besar",
        subtitle="Subjudul",
        output_path=output,
    )

    result = generate_template_thumbnail(config)

    assert result == output
    with Image.open(output) as image:
        assert image.size == (1080, 1920)
        assert image.format == "PNG"
```

**Step 2: Run tests and verify they fail**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_thumbnails.py -v
```

Expected: FAIL because thumbnail wrapper does not exist.

**Step 3: Implement minimal thumbnail wrapper**

Use existing `clipper_agency.core.card_generator.CardGenerator` where possible.

Requirements:
- Keep the public wrapper small.
- Do not duplicate card drawing logic unnecessarily.
- Choose card type based on template name:
  - `news_card` → headline card
  - `b_roll_narration` → context card
  - `rapid_update` → fact/punchy card
- Create parent directories for the provided output path.

**Step 4: Run tests and verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_thumbnails.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/rendering/thumbnails.py tests/test_rendering_thumbnails.py
git commit -m "feat: add template thumbnail generation"
```

---

### Task 5: Run PR 1 targeted and offline verification ✅

**Files:**
- No new files expected.

**Step 1: Run targeted rendering foundation tests**

```bash
.venv/bin/python3 -m pytest \
  tests/test_rendering_templates.py \
  tests/test_rendering_contracts.py \
  tests/test_rendering_primitives.py \
  tests/test_rendering_thumbnails.py \
  -v
```

Expected: PASS.

**Step 2: Run related legacy tests**

```bash
.venv/bin/python3 -m pytest tests/test_card_generator.py tests/test_config_loader.py -v
```

Expected: PASS.

**Step 3: Run offline suite**

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected: all offline tests pass.

**Step 4: Commit any verification-only doc/test adjustments**

If no files changed, do not create an empty commit.

**Step 5: Open PR 1**

```bash
git status --short
git log --oneline -10
gh pr create --base master --title "Phase 15a: Template rendering foundation" --body "Adds strict template loading, render contracts, shared primitives, and template thumbnail generation."
```

Expected: PR created for branch `phase/15a-template-foundation`.

---

## PR 2 — Template Adapters + Standalone Render Fixtures

Branch: `phase/15a-template-adapters`

Start after PR 1 is merged and local `master` is pulled.

Purpose: implement three thin template adapters and a standalone deterministic FFmpeg renderer before touching Composer.

### Task 6: Add renderer package and News Card adapter ✅

**Files:**
- Create: `clipper_agency/rendering/renderers/__init__.py`
- Create: `clipper_agency/rendering/renderers/news_card.py`
- Test: `tests/test_rendering_adapters.py`

**Step 1: Write failing News Card adapter test**

Example:

```python
from pathlib import Path

from clipper_agency.rendering.renderers.news_card import build_news_card_plan
from clipper_agency.rendering.templates import load_render_template


def test_news_card_adapter_builds_headline_plan(tmp_path):
    template = load_render_template("news_card", Path("templates"))
    source = tmp_path / "source.mp4"
    source.write_bytes(b"placeholder")

    plan = build_news_card_plan(
        template=template,
        source_paths=[source],
        caption="Breaking: artis rilis kabar baru",
        title="Breaking News",
        diagnostics_dir=tmp_path,
    )

    assert plan.template_name == "news_card"
    assert plan.scenes[0].source_path == source
    assert plan.scenes[0].captions
    assert plan.thumbnail.title == "Breaking News"
```

**Step 2: Run test and verify it fails**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_adapters.py::test_news_card_adapter_builds_headline_plan -v
```

Expected: FAIL because adapter does not exist.

**Step 3: Implement minimal adapter**

Implement a pure plan builder. Do not call FFmpeg here.

Suggested signature:

```python
def build_news_card_plan(
    *,
    template: RenderTemplateConfig,
    source_paths: list[Path],
    caption: str,
    title: str,
    diagnostics_dir: Path,
) -> RenderPlan:
    ...
```

Requirements:
- Use `make_caption_overlays`.
- Use template transition settings.
- Create `ThumbnailConfig` with `diagnostics_dir / "thumbnails" / "news_card.png"`.
- Do not read/probe source files in adapter.

**Step 4: Run adapter test and verify it passes**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_adapters.py::test_news_card_adapter_builds_headline_plan -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/rendering/renderers/__init__.py clipper_agency/rendering/renderers/news_card.py tests/test_rendering_adapters.py
git commit -m "feat: add news card render adapter"
```

---

### Task 7: Add B-Roll Narration adapter ✅

**Files:**
- Create: `clipper_agency/rendering/renderers/b_roll_narration.py`
- Modify: `tests/test_rendering_adapters.py`

**Step 1: Write failing B-Roll adapter test**

Cover multi-source scenes, dynamic bottom captions, and crossfade transition metadata.

```python
from clipper_agency.rendering.renderers.b_roll_narration import build_b_roll_narration_plan


def test_b_roll_narration_adapter_uses_multiple_clips(tmp_path):
    sources = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for source in sources:
        source.write_bytes(b"placeholder")

    template = load_render_template("b_roll_narration", Path("templates"))
    plan = build_b_roll_narration_plan(
        template=template,
        source_paths=sources,
        caption="narasi panjang untuk dua klip",
        title="Konteks",
        diagnostics_dir=tmp_path,
    )

    assert len(plan.scenes) == 2
    assert {scene.transition for scene in plan.scenes} == {"crossfade"}
    assert all(scene.captions for scene in plan.scenes)
```

**Step 2: Run test and verify it fails**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_adapters.py::test_b_roll_narration_adapter_uses_multiple_clips -v
```

Expected: FAIL because adapter does not exist.

**Step 3: Implement minimal adapter**

Use one `RenderScene` per source path. Split captions deterministically across scenes.

**Step 4: Run adapter tests and verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_adapters.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/rendering/renderers/b_roll_narration.py tests/test_rendering_adapters.py
git commit -m "feat: add b-roll narration render adapter"
```

---

### Task 8: Add Rapid Update adapter ✅

**Files:**
- Create: `clipper_agency/rendering/renderers/rapid_update.py`
- Modify: `tests/test_rendering_adapters.py`

**Step 1: Write failing Rapid Update adapter test**

Cover punchy centered captions and cut transition metadata.

```python
from clipper_agency.rendering.renderers.rapid_update import build_rapid_update_plan


def test_rapid_update_adapter_uses_punchy_centered_captions(tmp_path):
    source = tmp_path / "rapid.mp4"
    source.write_bytes(b"placeholder")
    template = load_render_template("rapid_update", Path("templates"))

    plan = build_rapid_update_plan(
        template=template,
        source_paths=[source],
        caption="viral sekarang cek faktanya",
        title="Viral",
        diagnostics_dir=tmp_path,
    )

    assert plan.template_name == "rapid_update"
    assert plan.scenes[0].transition == "cut"
    assert {caption.position for caption in plan.scenes[0].captions} == {"center"}
```

**Step 2: Run test and verify it fails**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_adapters.py::test_rapid_update_adapter_uses_punchy_centered_captions -v
```

Expected: FAIL because adapter does not exist.

**Step 3: Implement minimal adapter**

Keep it a pure plan builder. Prefer small helper functions only if duplicated logic appears across adapters.

**Step 4: Run adapter tests and verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_adapters.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/rendering/renderers/rapid_update.py tests/test_rendering_adapters.py
git commit -m "feat: add rapid update render adapter"
```

---

### Task 9: Add standalone FFmpeg render engine ✅

**Files:**
- Create: `clipper_agency/rendering/engine.py`
- Test: `tests/test_rendering_engine.py`

**Step 1: Write failing engine command-construction tests**

Patch `subprocess.run` and `clipper_agency.core.media_probe.probe_video` so tests are offline and deterministic.

```python
from pathlib import Path
from unittest.mock import Mock

from clipper_agency.rendering.contracts import CaptionOverlay, RenderPlan, RenderScene, ThumbnailConfig
from clipper_agency.rendering.engine import render_plan


def test_render_plan_persists_diagnostics_and_runs_ffmpeg(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake")
    output = tmp_path / "video.mp4"
    diagnostics = tmp_path / "diagnostics"
    plan = RenderPlan(
        template_name="news_card",
        scenes=[RenderScene(
            source_path=source,
            duration_seconds=1.0,
            captions=[CaptionOverlay(text="Halo", start_seconds=0.0, end_seconds=1.0)],
        )],
        thumbnail=ThumbnailConfig(template_name="news_card", title="Halo", output_path=diagnostics / "thumbnail.png"),
    )

    completed = Mock(returncode=0, stderr="", stdout="")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: completed)
    monkeypatch.setattr("clipper_agency.rendering.engine.probe_video", lambda *args, **kwargs: object())
    monkeypatch.setattr("clipper_agency.rendering.engine.generate_template_thumbnail", lambda config: config.output_path)

    result = render_plan(plan, output_path=output, diagnostics_dir=diagnostics)

    assert result.video_path == output
    assert (diagnostics / "render_plan.json").is_file()
    assert (diagnostics / "ffmpeg_command.txt").is_file()
```

**Step 2: Run test and verify it fails**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_engine.py -v
```

Expected: FAIL because engine does not exist.

**Step 3: Implement minimal engine**

Requirements:
- Public function: `render_plan(plan: RenderPlan, output_path: Path, diagnostics_dir: Path) -> RenderResult`.
- Write:
  - `render_plan.json`
  - `ffmpeg_filtergraph.txt`
  - `ffmpeg_command.txt`
  - `ffmpeg_stderr.log` only when FFmpeg fails or emits stderr worth preserving
- Build FFmpeg args as a list; use `shell=False`.
- Use drawtext filters from caption overlays.
- Generate thumbnail through `generate_template_thumbnail`.
- Probe final output with `probe_video(output_path, output_path.parent)` after FFmpeg succeeds.
- Raise `TemplateRenderError` on FFmpeg failure.
- Do not use caller-provided arbitrary paths outside `output_path` and `diagnostics_dir`.

**Step 4: Run engine tests and verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_engine.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/rendering/engine.py tests/test_rendering_engine.py
git commit -m "feat: add standalone render engine"
```

---

### Task 10: Add deterministic standalone render fixture tests ✅

**Files:**
- Modify: `tests/test_rendering_engine.py`
- Optionally create: `tests/fixtures/rendering/README.md`

**Step 1: Write failing small fixture tests**

Create tests that generate local synthetic inputs with FFmpeg or Pillow under `tmp_path`, then run one short render per template. Keep duration tiny to avoid slow tests.

Example structure:

```python
import subprocess

import pytest

from clipper_agency.core.media_probe import probe_video


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg not installed")
def test_standalone_renderer_outputs_valid_video_for_news_card(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=1",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", source,
    ], check=True)
    # build plan via adapter, render, then probe
```

**Step 2: Run fixture test and verify it fails for missing wiring**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_engine.py -v
```

Expected: FAIL if standalone fixture path is incomplete; skip only if FFmpeg is unavailable.

**Step 3: Implement minimal fixture support**

If needed, add small helpers inside the test module. Do not add production code unless the failing test exposes a production gap.

**Step 4: Run PR 2 targeted tests**

```bash
.venv/bin/python3 -m pytest tests/test_rendering_adapters.py tests/test_rendering_engine.py -v
```

Expected: PASS, with fixture tests skipped only when FFmpeg is unavailable.

**Step 5: Run offline suite and commit**

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
git add tests/test_rendering_engine.py tests/fixtures/rendering/README.md
git commit -m "test: add deterministic render fixtures"
```

If `tests/fixtures/rendering/README.md` was not created, omit it from `git add`.

---

## PR 3 — Composer Integration + Documentation

Branch: `phase/15a-composer-template-integration`

Start after PR 2 is merged and local `master` is pulled.

Purpose: route Composer through template rendering, persist diagnostics, update package metadata, and update docs/ADR/traceability.

### Task 11: Integrate template plan selection into Composer ✅

**Files:**
- Modify: `clipper_agency/agents/composer.py`
- Test: `tests/test_agents_composer.py`

**Step 1: Write failing Composer template-selection test**

Patch the standalone renderer so this test does not invoke FFmpeg.

```python
from pathlib import Path


def test_composer_uses_template_renderer_when_template_name_is_provided(tmp_path, monkeypatch):
    calls = {}

    def fake_render_plan(plan, output_path, diagnostics_dir):
        calls["template_name"] = plan.template_name
        output_path.write_bytes(b"video")
        return type("Result", (), {
            "video_path": output_path,
            "thumbnail_path": diagnostics_dir / "thumbnails" / "news_card.png",
            "diagnostics_dir": diagnostics_dir,
        })()

    monkeypatch.setattr("clipper_agency.agents.composer.render_plan", fake_render_plan)
    # patch FFmpeg preflight/probe as existing tests do

    result = ComposerAgent().execute(
        job_id=123,
        assets=[str(tmp_path / "asset.mp4")],
        audio_files=[],
        output_dir=str(tmp_path / "outputs"),
        assets_cache=str(tmp_path / "cache"),
        caption="Halo dunia",
        template_name="news_card",
    )

    assert calls["template_name"] == "news_card"
    assert result["template_name"] == "news_card"
```

**Step 2: Run test and verify it fails**

```bash
.venv/bin/python3 -m pytest tests/test_agents_composer.py::test_composer_uses_template_renderer_when_template_name_is_provided -v
```

Expected: FAIL because Composer does not route to template renderer yet.

**Step 3: Implement minimal Composer routing**

Requirements:
- Add optional `template_name: str | None = None` and `caption: str | None = None` handling if not already present through `**kwargs`.
- If `template_name` is provided and supported, load template, choose adapter, build plan, and call `render_plan`.
- If no template is provided, preserve current Composer behavior.
- Keep existing preflight and fallback behavior intact unless the template path explicitly supersedes it.
- Write output to `output_dir/job_{job_id}/video.mp4`.
- Use diagnostics dir from `ensure_agent_dir(Path(assets_cache), job_id, "composer")` when `assets_cache` is provided.

**Step 4: Run Composer template-selection test and verify it passes**

```bash
.venv/bin/python3 -m pytest tests/test_agents_composer.py::test_composer_uses_template_renderer_when_template_name_is_provided -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/agents/composer.py tests/test_agents_composer.py
git commit -m "feat: route composer through template renderer"
```

---

### Task 12: Persist Composer template diagnostics ✅

**Files:**
- Modify: `clipper_agency/agents/composer.py`
- Modify: `tests/test_composer.py`

**Step 1: Write failing diagnostics test**

Cover expected diagnostics files under `assets_cache/job_{job_id}/agents/composer/`.

```python
def test_composer_persists_template_diagnostics(tmp_path, monkeypatch):
    # patch render_plan to write expected diagnostics files
    result = ComposerAgent().execute(
        job_id=456,
        assets=[str(tmp_path / "asset.mp4")],
        audio_files=[],
        output_dir=str(tmp_path / "outputs"),
        assets_cache=str(tmp_path / "assets_cache"),
        caption="Caption",
        template_name="rapid_update",
    )

    composer_dir = tmp_path / "assets_cache" / "job_456" / "agents" / "composer"
    assert (composer_dir / "input.json").is_file()
    assert (composer_dir / "output.json").is_file()
    assert (composer_dir / "render_plan.json").is_file()
    assert result["diagnostics_dir"] == str(composer_dir)
```

**Step 2: Run test and verify it fails**

```bash
.venv/bin/python3 -m pytest tests/test_composer.py::test_composer_persists_template_diagnostics -v
```

Expected: FAIL until Composer copies/produces all template diagnostics.

**Step 3: Implement diagnostics persistence**

Requirements:
- Keep current `input.json` and `output.json` behavior.
- Ensure template path writes:
  - `template_config.json`
  - `render_plan.json`
  - `ffmpeg_filtergraph.txt`
  - `ffmpeg_command.txt`
  - `ffmpeg_stderr.log` on FFmpeg failure/stderr
  - `overlays/`, `cards/`, `thumbnails/` as applicable
- Do not introduce arbitrary filesystem paths; build diagnostics from `assets_cache`, integer `job_id`, and static names.

**Step 4: Run diagnostics tests and verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_composer.py tests/test_agents_composer.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/agents/composer.py tests/test_composer.py tests/test_agents_composer.py
git commit -m "feat: persist template render diagnostics"
```

---

### Task 13: Update final package metadata and thumbnail treatment ✅

**Files:**
- Modify: `clipper_agency/orchestrator/engine.py`
- Modify: `clipper_agency/output/packager.py` only if metadata merge behavior needs adjustment
- Test: `tests/test_output_packager.py`
- Test: existing orchestrator/engine tests if present for package metadata

**Step 1: Write failing metadata test**

Prefer testing the smallest boundary. If `OutputPackager.package()` already preserves arbitrary metadata, add/adjust orchestrator test instead.

Example packager-level expectation:

```python
def test_output_packager_metadata_includes_template_info(tmp_path, monkeypatch):
    # arrange fixed job-owned output_dir/job_77/video.mp4 and patched probe
    result = OutputPackager().package(
        job_id=77,
        video_path=str(tmp_path / "outputs" / "job_77" / "video.mp4"),
        caption="caption",
        thumbnail_path=str(tmp_path / "thumb.png"),
        metadata={"topic": "topic", "niche": "artist", "template_name": "news_card"},
        output_dir=str(tmp_path / "outputs"),
    )

    metadata = json.loads(Path(result["metadata_path"]).read_text())
    assert metadata["template_name"] == "news_card"
```

**Step 2: Run test and verify it fails only if behavior is missing**

```bash
.venv/bin/python3 -m pytest tests/test_output_packager.py -v
```

Expected: FAIL if template metadata is not preserved/passed through. If packager already passes, move test to orchestrator metadata propagation.

**Step 3: Implement minimal metadata propagation**

Requirements:
- Include `template_name` and optionally `template_style` in final `metadata.json`.
- Preserve fixed job-owned packager path contract.
- Do not make Packager open arbitrary video paths.
- Ensure template thumbnail path becomes final `thumbnail.png` through existing package flow.

**Step 4: Run metadata tests and verify they pass**

```bash
.venv/bin/python3 -m pytest tests/test_output_packager.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add clipper_agency/orchestrator/engine.py clipper_agency/output/packager.py tests/test_output_packager.py
git commit -m "feat: include template metadata in output package"
```

Only include `clipper_agency/output/packager.py` if it changed.

---

### Task 14: Update product and technical docs where needed ✅

**Files:**
- Modify: `docs/plans/2026-05-27-MVP Pipeline Repair Roadmap — Phases 12-15.md`
- Modify: `docs/PRD.md` if template rendering requirements/status need updates
- Modify: `docs/SRS.md` if functional requirement wording/status needs updates
- Modify: `docs/technical_design.md` for rendering architecture
- Modify: `docs/plans/2026-05-29-phase-15a-template-rendering-task-plan.md`

**Step 1: Inspect current docs before editing**

Read relevant sections only. Look for Phase 15a, template rendering, Composer, output package, and traceability references.

**Step 2: Update docs surgically**

Requirements:
- Keep PRD, SRS, and technical design separate.
- Do not move Stage 2 observability back into MVP Phase 15a.
- Document why hybrid YAML + FFmpeg + Pillow was chosen.
- Update task-plan status only enough to point to implementation progress.

**Step 3: Verify docs contain no contradictory Phase 15/15a scope**

Use targeted searches:

```bash
grep -R "Phase 15" docs/PRD.md docs/SRS.md docs/technical_design.md docs/plans | grep -E "observability|template|15a"
```

Expected: Phase 15a references template rendering; observability remains Stage 2/deferred.

**Step 4: Commit**

```bash
git add docs/PRD.md docs/SRS.md docs/technical_design.md "docs/plans/2026-05-27-MVP Pipeline Repair Roadmap — Phases 12-15.md" docs/plans/2026-05-29-phase-15a-template-rendering-task-plan.md
git commit -m "docs: update phase 15a template rendering docs"
```

Only include files that changed.

---

### Task 15: Add ADR for template-driven rendering architecture ✅

**Files:**
- Create: `docs/adr/0013-use-yaml-ffmpeg-pillow-template-rendering.md`

**Step 1: Write ADR**

Use existing ADR format: Context → Decision → Alternatives Considered → Consequences.

Must include:
- Context: Phase 15a needs deterministic MVP template rendering.
- Decision: YAML templates + shared primitives + FFmpeg/Pillow engine + per-template adapters.
- Alternatives:
  - full rendering framework
  - hardcoded Composer-only templates
  - browser/HTML rendering
- Consequences:
  - offline-test friendly
  - low dependency risk
  - some FFmpeg filter complexity remains
  - Stage 2 observability remains deferred

**Step 2: Verify ADR path and title**

```bash
ls docs/adr
```

Expected: new ADR number does not collide with existing files. If `0013` already exists, use the next available number and update references.

**Step 3: Commit**

```bash
git add docs/adr/0013-use-yaml-ffmpeg-pillow-template-rendering.md
git commit -m "docs: add template rendering ADR"
```

---

### Task 16: Update requirements traceability ✅

**Files:**
- Modify: `docs/requirements_traceability.md`

**Step 1: Identify exact requirements to update**

Find existing template/rendering/output-package rows and any Phase 15a requirement IDs.

**Step 2: Update traceability rows**

Each relevant row should map to:
- implementation files:
  - `clipper_agency/rendering/templates.py`
  - `clipper_agency/rendering/contracts.py`
  - `clipper_agency/rendering/primitives.py`
  - `clipper_agency/rendering/thumbnails.py`
  - `clipper_agency/rendering/engine.py`
  - `clipper_agency/rendering/renderers/*.py`
  - `clipper_agency/agents/composer.py`
  - `clipper_agency/orchestrator/engine.py`
- tests:
  - `tests/test_rendering_templates.py`
  - `tests/test_rendering_contracts.py`
  - `tests/test_rendering_primitives.py`
  - `tests/test_rendering_thumbnails.py`
  - `tests/test_rendering_adapters.py`
  - `tests/test_rendering_engine.py`
  - `tests/test_composer.py`
  - `tests/test_agents_composer.py`
  - `tests/test_output_packager.py`

**Step 3: Verify traceability mentions Phase 15a and not Stage 2 observability as complete**

```bash
grep -n "15a\|template\|observability" docs/requirements_traceability.md
```

Expected: template rendering marked implemented/tested; Stage 2 observability not marked as MVP complete.

**Step 4: Commit**

```bash
git add docs/requirements_traceability.md
git commit -m "docs: trace phase 15a template rendering"
```

---

### Task 17: Full PR 3 verification and PR creation ✅

**Files:**
- No new files expected.

**Step 1: Run targeted rendering tests**

```bash
.venv/bin/python3 -m pytest \
  tests/test_rendering_templates.py \
  tests/test_rendering_contracts.py \
  tests/test_rendering_primitives.py \
  tests/test_rendering_thumbnails.py \
  tests/test_rendering_adapters.py \
  tests/test_rendering_engine.py \
  -v
```

Expected: PASS.

**Step 2: Run Composer and packaging tests**

```bash
.venv/bin/python3 -m pytest \
  tests/test_composer.py \
  tests/test_agents_composer.py \
  tests/test_output_packager.py \
  -v
```

Expected: PASS.

**Step 3: Run offline suite**

```bash
.venv/bin/python3 -m pytest -m "not external and not integration" -q
```

Expected: all offline tests pass; external/integration-marked tests deselected.

**Step 4: Inspect git status and diff**

```bash
git status --short
git diff --stat
git log --oneline -10
```

Expected: only Phase 15a files changed, with commits already created for each task group.

**Step 5: Open PR 3**

```bash
gh pr create --base master --title "Phase 15a: Composer template rendering integration" --body "Integrates template-driven rendering into Composer, persists diagnostics, updates final metadata, and documents Phase 15a traceability."
```

Expected: PR created for branch `phase/15a-composer-template-integration`.

---

## Final Acceptance Criteria

- `templates/news_card.yaml`, `templates/b_roll_narration.yaml`, and `templates/rapid_update.yaml` load through strict rendering-template validation.
- Each template has a thin adapter that produces a deterministic `RenderPlan`.
- Shared primitives handle captions, overlay metadata, FFmpeg drawtext escaping, and transition metadata.
- Standalone renderer can produce a valid short `video.mp4` from deterministic local fixtures.
- Composer can render with a selected template and still preserves the existing no-template behavior.
- Composer diagnostics are persisted under `ASSETS_CACHE/job_{id}/agents/composer/`.
- Final output package remains `video.mp4`, `caption.txt`, `thumbnail.png`, `metadata.json` under `OUTPUT_DIR/job_{id}/`.
- Final metadata includes template information.
- PRD/SRS/technical design/roadmap/task plan/ADR/traceability reflect Phase 15a accurately.
- Offline suite passes with `.venv/bin/python3 -m pytest -m "not external and not integration" -q`.

## Execution Handoff

When implementing this plan, use `superpowers:executing-plans` in a fresh session or `superpowers:subagent-driven-development` in this session. Execute task-by-task, verify after every task, and stop on failures before proposing fixes.
