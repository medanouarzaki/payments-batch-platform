"""The package must be importable from an installed environment."""

import importlib


def test_payments_package_is_importable() -> None:
    module = importlib.import_module("payments")
    assert module.__name__ == "payments"
