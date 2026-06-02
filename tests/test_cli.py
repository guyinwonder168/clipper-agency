"""Tests for the CLI commands."""

from unittest.mock import patch

from click.testing import CliRunner

from clipper_agency.__main__ import cli


class TestSettingsHelpers:
    """Test _db_path and _output_dir helper functions."""

    @patch("clipper_agency.__main__.load_settings")
    def test_db_path_from_settings(self, mock_load):
        from clipper_agency.__main__ import _db_path
        from clipper_agency.config.schema import AppSettings

        mock_load.return_value = AppSettings(_env_file=None, db_path="/custom/db.db")
        assert _db_path() == "/custom/db.db"

    @patch("clipper_agency.__main__.load_settings")
    def test_db_path_default(self, mock_load):
        from clipper_agency.__main__ import _db_path
        from clipper_agency.config.schema import AppSettings

        with patch.dict("os.environ", {}, clear=True):
            mock_load.return_value = AppSettings(_env_file=None)
            assert _db_path() == "data/clipper.db"

    @patch("clipper_agency.__main__.load_settings")
    def test_output_dir_from_settings(self, mock_load):
        from clipper_agency.__main__ import _output_dir
        from clipper_agency.config.schema import AppSettings

        mock_load.return_value = AppSettings(_env_file=None, output_dir="/custom/out")
        assert _output_dir() == "/custom/out"

    @patch("clipper_agency.__main__.load_settings")
    def test_output_dir_default(self, mock_load):
        from clipper_agency.__main__ import _output_dir
        from clipper_agency.config.schema import AppSettings

        with patch.dict("os.environ", {}, clear=True):
            mock_load.return_value = AppSettings(_env_file=None)
            assert _output_dir() == "outputs"


class TestCliHelp:
    def test_cli_help(self):
        """--help should show usage with Clipper Agency title."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Clipper Agency" in result.output

    def test_run_command_exists(self):
        """'run' subcommand should exist in help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "run" in result.output

    def test_jobs_command_exists(self):
        """'jobs' subcommand should exist in help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "jobs" in result.output


class TestRunCommand:
    def test_run_requires_topic(self):
        """run command should fail without --topic."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "Error" in result.output

    @patch("clipper_agency.orchestrator.engine.Orchestrator.run_pipeline")
    def test_run_with_topic_echoes_input(self, mock_run):
        """run command should echo the topic back."""
        mock_run.return_value = {"status": "completed", "job_id": 1, "output": {}}
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--topic", "Test topic", "--db", ":memory:"])
        assert result.exit_code == 0
        assert "Test topic" in result.output

    @patch("clipper_agency.__main__.load_niche")
    @patch("clipper_agency.orchestrator.engine.Orchestrator.run_pipeline")
    def test_run_with_niche_default(self, mock_run, mock_load_niche):
        """run command should show the niche."""
        mock_run.return_value = {"status": "completed", "job_id": 1, "output": {}}
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--topic", "Test", "--niche", "custom_niche", "--db", ":memory:"])
        assert result.exit_code == 0
        assert "custom_niche" in result.output

    def test_run_dry_run_mode(self):
        """--dry-run should validate inputs without running pipeline."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--topic", "Test", "--dry-run"])
        assert result.exit_code == 0
        assert "Pipeline execution coming soon" in result.output or "dry" in result.output.lower()

    @patch("clipper_agency.__main__.load_niche")
    @patch("clipper_agency.orchestrator.engine.Orchestrator.run_pipeline")
    def test_run_dispatches_to_orchestrator(self, mock_run, mock_load_niche):
        """run command should call Orchestrator.run_pipeline on execution."""
        mock_run.return_value = {
            "status": "completed",
            "job_id": 42,
            "output": {"video_path": "/tmp/v.mp4"},
        }
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", "--topic", "Test topic", "--niche", "test", "--db", ":memory:", "--output-dir", "outputs"],
        )
        assert result.exit_code == 0
        mock_run.assert_called_once_with(
            topic="Test topic", niche="test", output_dir="outputs",
        )

    @patch("clipper_agency.orchestrator.engine.Orchestrator.run_pipeline")
    def test_run_reports_failure(self, mock_run):
        """run command should report pipeline failure."""
        mock_run.return_value = {
            "status": "failed",
            "error": "Something went wrong",
            "job_id": 1,
        }
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--topic", "Bad topic", "--db", ":memory:"])
        assert result.exit_code == 0
        assert "failed" in result.output.lower() or "Pipeline" in result.output


class TestJobsCommand:
    @patch("clipper_agency.db.queries.list_jobs")
    def test_jobs_lists_recent(self, mock_list):
        """jobs command should display recent jobs."""
        mock_list.return_value = [
            {"id": 1, "topic": "Test topic", "status": "COMPLETED", "created_at": "2026-01-01"},
            {"id": 2, "topic": "Another", "status": "FAILED", "created_at": "2026-01-02"},
        ]
        runner = CliRunner()
        result = runner.invoke(cli, ["jobs"])
        assert result.exit_code == 0
        assert "Test topic" in result.output
        assert "COMPLETED" in result.output

    @patch("clipper_agency.db.queries.list_jobs")
    def test_jobs_empty(self, mock_list):
        """jobs command should handle empty job list."""
        mock_list.return_value = []
        runner = CliRunner()
        result = runner.invoke(cli, ["jobs"])
        assert result.exit_code == 0
