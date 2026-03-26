from __future__ import annotations

import logging
import re

from ha_autoupgrade.utils.logging_utils import TextFormatter


def test_text_formatter_starts_with_date_and_time() -> None:
    formatter = TextFormatter()
    record = logging.LogRecord(
        name="ha_autoupgrade.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="sample message",
        args=(),
        exc_info=None,
    )

    formatted = formatter.format(record)

    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO \[ha_autoupgrade\.test\] sample message",
        formatted,
    )
