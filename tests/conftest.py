"""Shared pytest fixtures."""
from __future__ import annotations

import pytest

from newsletter_pod import events as events_module


@pytest.fixture(autouse=True)
def _capture_event_logger(caplog):
    """Make the events logger visible to ``caplog``.

    ``newsletter_pod.events`` sets ``propagate = False`` so production emits a
    single pure-JSON line per event (which Cloud Run parses into
    ``jsonPayload``; see the module docstring). A non-propagating logger never
    reaches caplog's root handler, so attach caplog's handler directly for the
    duration of each test — otherwise every ``_captured_events`` assertion
    would see nothing.
    """
    events_module.logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        events_module.logger.removeHandler(caplog.handler)
