"""Never let repository tests use the application database from .env."""

import os

import pytest
from psycopg.conninfo import conninfo_to_dict


def pytest_configure(config):
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        options = conninfo_to_dict(url)
        if options.get("host") not in {"127.0.0.1", "localhost", "::1"}:
            raise pytest.UsageError("TEST_DATABASE_URL must target an isolated loopback database")
    # Explicit override also prevents dotenv from loading the production URL later.
    os.environ["DATABASE_URL"] = url or "postgresql://postgres@127.0.0.1:1/pbl4_tests_unconfigured"
