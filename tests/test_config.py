"""Tests for configuration loading."""

import os
import tempfile
from pathlib import Path

import pytest

from scholar_watch.config import load_config, _interpolate_env_vars


def test_interpolate_env_vars():
    os.environ["TEST_VAR_123"] = "hello"
    result = _interpolate_env_vars("prefix_${TEST_VAR_123}_suffix")
    assert result == "prefix_hello_suffix"
    del os.environ["TEST_VAR_123"]


def test_interpolate_missing_var_unchanged():
    result = _interpolate_env_vars("${MISSING_VAR_XYZ}")
    assert result == "${MISSING_VAR_XYZ}"


def test_load_default_config():
    config = load_config()
    assert config.database.path == "data/scholar_watch.db"
    assert config.scraping.min_delay == 5.0


def test_load_config_from_yaml():
    yaml_content = """
database:
  path: test.db
scraping:
  min_delay: 1
  max_delay: 2
  proxy:
    type: none
researchers:
  - scholar_id: "abc123"
    name: "Test Person"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        config = load_config(f.name)

    assert config.database.path == "test.db"
    assert config.scraping.min_delay == 1
    assert len(config.researchers) == 1
    assert config.researchers[0].scholar_id == "abc123"

    os.unlink(f.name)
