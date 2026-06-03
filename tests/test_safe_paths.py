"""Tests for safe filesystem path resolution."""

from clipper_agency.core.safe_paths import resolve_existing_file_under


class TestResolveExistingFileUnder:
    def test_returns_resolved_child_file_inside_base(self, tmp_path):
        base = tmp_path / "job_1"
        base.mkdir()
        video = base / "video.mp4"
        video.write_bytes(b"video")

        resolved = resolve_existing_file_under(base, "video.mp4")

        assert resolved == video.resolve()

    def test_rejects_parent_traversal_outside_base(self, tmp_path):
        base = tmp_path / "job_1"
        base.mkdir()
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"video")

        resolved = resolve_existing_file_under(base, "../outside.mp4")

        assert resolved is None

    def test_rejects_absolute_file_outside_base(self, tmp_path):
        base = tmp_path / "job_1"
        base.mkdir()
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"video")

        resolved = resolve_existing_file_under(base, outside)

        assert resolved is None

    def test_rejects_missing_file_inside_base(self, tmp_path):
        base = tmp_path / "job_1"
        base.mkdir()

        resolved = resolve_existing_file_under(base, "missing.mp4")

        assert resolved is None

    def test_accepts_relative_path_containing_base_prefix(self, tmp_path,
                                                          monkeypatch):
        """Regression: G10 passes "data/outputs/job_N/video.mp4" as
        candidate with base set to Path(candidate).parent.  The resolved
        file must still be found when the candidate sits inside base."""
        job_dir = tmp_path / "data" / "outputs" / "job_2"
        job_dir.mkdir(parents=True)
        video = job_dir / "video.mp4"
        video.write_bytes(b"video")

        # Simulate cwd so the relative path resolves correctly.
        monkeypatch.chdir(tmp_path)

        resolved = resolve_existing_file_under(
            job_dir, "data/outputs/job_2/video.mp4",
        )
        assert resolved == video.resolve()

    def test_relative_cwd_outside_base_still_rejected(self, tmp_path,
                                                       monkeypatch):
        """Relative candidate that exists in CWD but is NOT inside base
        must still be rejected — path-containment safety preserved."""
        base = tmp_path / "job_1"
        base.mkdir()
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"video")

        monkeypatch.chdir(tmp_path)

        resolved = resolve_existing_file_under(base, "outside.mp4")
        assert resolved is None
