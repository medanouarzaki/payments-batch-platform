"""The installed package must expose the version its metadata declares."""

from importlib.metadata import version

import payments


def test_package_version_matches_distribution_metadata() -> None:
    assert payments.__version__ == version("payments")
