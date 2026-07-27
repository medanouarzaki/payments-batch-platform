import logging

import pytest

from payments.logging_setup import configure_logging, get_logger


@pytest.fixture(autouse=True)
def reset_root_logger():
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    had_marker = hasattr(root_logger, "_payments_configured")
    marker_value = getattr(root_logger, "_payments_configured", None)
    yield
    root_logger.handlers = original_handlers
    root_logger.setLevel(original_level)
    if had_marker:
        root_logger._payments_configured = marker_value
    elif hasattr(root_logger, "_payments_configured"):
        delattr(root_logger, "_payments_configured")


def test_double_configure_does_not_duplicate_handlers():
    configure_logging("INFO")
    count_after_one = len(logging.getLogger().handlers)
    configure_logging("INFO")
    count_after_two = len(logging.getLogger().handlers)
    assert count_after_two == count_after_one


def test_warning_level_filters_info_messages(capsys):
    configure_logging("WARNING")
    logger = get_logger("payments.test_logging_setup")
    logger.info("this info message must not appear")
    logger.warning("this warning message must appear")
    captured = capsys.readouterr()
    assert "this info message must not appear" not in captured.err
    assert "this warning message must appear" in captured.err
