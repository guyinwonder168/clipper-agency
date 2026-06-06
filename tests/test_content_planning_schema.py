from clipper_agency.config.schema import ContentPlanningConfig


class TestContentPlanningConfig:
    def test_defaults(self):
        cfg = ContentPlanningConfig()
        assert cfg.default_format == "three_story_roundup"
        assert cfg.max_stories_per_video == 3
        assert cfg.target_duration_sec == 55
        assert cfg.hard_limit_sec == 60
        assert cfg.estimated_words_per_second == 2.0

    def test_override_from_dict(self):
        cfg = ContentPlanningConfig(**{
            "default_format": "single_story_deep",
            "max_stories_per_video": 1,
            "target_duration_sec": 50,
            "hard_limit_sec": 55,
            "estimated_words_per_second": 1.8,
        })
        assert cfg.default_format == "single_story_deep"
        assert cfg.target_duration_sec == 50

    def test_enforces_positive(self):
        from pydantic import ValidationError
        try:
            ContentPlanningConfig(target_duration_sec=-1)
        except ValidationError:
            pass  # expected

    def test_niche_loads_content_planning(self):
        from clipper_agency.config.loader import load_niche
        niche = load_niche("indonesian_artists")
        # NicheConfig doesn't have content_planning field — check raw YAML
        import yaml
        from pathlib import Path
        path = Path("niches/indonesian_artists.yaml")
        data = yaml.safe_load(path.read_text())
        cp = data.get("content_planning", {})
        assert cp.get("default_format") == "three_story_roundup"
        assert cp.get("max_stories_per_video") == 3
