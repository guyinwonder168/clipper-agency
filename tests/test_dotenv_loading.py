"""Tests for dotenv loading at application startup."""

import os
from unittest.mock import patch


class TestDotenvLoading:
    """Verify that load_dotenv() is called at import time in __main__."""

    def test_load_dotenv_called_in_main_module(self):
        """The __main__ module triggers load_dotenv() at import time.

        __main__ now calls ``clipper_agency.bootstrap.load_env`` (not
        ``dotenv.load_dotenv`` directly), and ``bootstrap`` bound the name at
        its own import time via ``from dotenv import load_dotenv`` — so
        patching ``dotenv.load_dotenv`` would miss the call. Patch the symbol
        ``bootstrap`` actually resolves.
        """
        import importlib

        import clipper_agency.bootstrap as bootstrap

        with patch.object(bootstrap, "load_dotenv", wraps=bootstrap.load_dotenv) as mock_load:
            import clipper_agency.__main__ as main_mod

            importlib.reload(main_mod)
            mock_load.assert_called()

    def test_env_vars_available_after_load_dotenv(self):
        """After load_dotenv(), variables from .env should be in os.environ."""
        # This test verifies the mechanism works when a .env file exists
        import tempfile
        from pathlib import Path

        from dotenv import load_dotenv

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("TEST_CLIPPER_VAR=hello_from_dotenv\n")

            # Point dotenv to our temp .env file
            with patch.dict(os.environ, {}, clear=True):
                loaded = load_dotenv(str(env_file), override=True)
                assert loaded is True
                assert os.getenv("TEST_CLIPPER_VAR") == "hello_from_dotenv"
