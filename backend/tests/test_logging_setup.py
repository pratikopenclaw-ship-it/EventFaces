"""Log assertions only mean something if the app's loggers are live during tests: running
migrations in-process (conftest, e2e server) must not disable them (alembic/env.py)."""

import importlib
import logging


def test_no_app_logger_is_disabled() -> None:
    for module in ("app.main", "app.workers.tasks"):  # every module that defines a logger
        importlib.import_module(module)

    disabled = sorted(
        name
        for name, logger in logging.root.manager.loggerDict.items()
        if name.startswith("app") and isinstance(logger, logging.Logger) and logger.disabled
    )
    assert disabled == []
