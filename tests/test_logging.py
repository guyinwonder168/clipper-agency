"""Tests for centralized logging configuration."""

import logging

from clipper_agency.core.logging import get_logger, setup_logging


def _reset_root_logger() -> None:
    """Remove all handlers from the root logger to isolate tests."""
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()


def test_setup_logging_configures_root_logger():
    _reset_root_logger()
    setup_logging("DEBUG")
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    _reset_root_logger()


def test_setup_logging_default_is_info():
    _reset_root_logger()
    setup_logging()
    root = logging.getLogger()
    assert root.level == logging.INFO
    _reset_root_logger()


def test_setup_logging_is_noop_when_handlers_exist():
    root = logging.getLogger()
    _reset_root_logger()
    root.setLevel(logging.WARNING)
    handler = logging.StreamHandler()
    root.addHandler(handler)
    try:
        setup_logging("DEBUG")
        assert root.level != logging.DEBUG
    finally:
        root.removeHandler(handler)
        _reset_root_logger()


def test_get_logger_returns_named_logger():
    logger = get_logger("test.module")
    assert logger.name == "test.module"


def test_third_party_filter_tags_library_logs():
    """Third-party logger names get [LIB] prefix."""
    from clipper_agency.core.logging import ThirdPartyLogFilter
    import logging

    filt = ThirdPartyLogFilter()
    record = logging.LogRecord("httpcore.connection", logging.DEBUG, "", 0, "msg", (), None)
    filt.filter(record)
    assert "[LIB]" in record.getMessage()


def test_third_party_filter_no_tag_for_pipeline_logs():
    """Pipeline logger names are NOT tagged."""
    from clipper_agency.core.logging import ThirdPartyLogFilter
    import logging

    filt = ThirdPartyLogFilter()
    record = logging.LogRecord("clipper_agency.agents.safety", logging.DEBUG, "", 0, "msg", (), None)
    filt.filter(record)
    assert "[LIB]" not in record.getMessage()


def test_add_job_file_handler_creates_file(tmp_path):
    """add_job_file_handler creates a log file handler."""
    from clipper_agency.core.logging import add_job_file_handler, remove_job_file_handler
    import logging

    _reset_root_logger()
    setup_logging("DEBUG")
    try:
        add_job_file_handler(42, output_dir=str(tmp_path))
        log_file = tmp_path / "job_42" / "debug.log"
        assert log_file.parent.exists()
        remove_job_file_handler()
    finally:
        _reset_root_logger()
