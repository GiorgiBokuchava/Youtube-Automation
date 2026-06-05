from __future__ import annotations

"""Lazy singleton wrapper for inaSpeechSegmenter.

Keeps the (heavy) neural-network models in memory across clips so they are
only loaded once per pipeline run.  The module is imported by probe.py but
the Segmenter is only instantiated the first time a clip is analysed.
"""

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_instances: dict[str, Any] = {}
_available: Optional[bool] = None


def is_available() -> bool:
    """Return True if inaSpeechSegmenter is importable on this machine."""
    global _available
    if _available is None:
        try:
            import inaSpeechSegmenter  # noqa: F401

            _available = True
        except ImportError:
            _available = False
    return _available


def get_segmenter(*, vad_engine: str = "smn") -> Any:
    """Return a cached ``Segmenter`` instance for *vad_engine*.

    The first call for a given ``vad_engine`` value loads the CNN models from
    disk (may take a few seconds).  All subsequent calls return immediately.

    Thread-safe: the double-checked locking pattern ensures the model is only
    loaded once even if two threads arrive simultaneously.
    """
    if vad_engine not in _instances:
        with _lock:
            if vad_engine not in _instances:
                from inaSpeechSegmenter import Segmenter

                logger.info(
                    "Loading inaSpeechSegmenter (vad_engine=%s, detect_gender=False)"
                    " — first clip may be slower while CNN models initialise",
                    vad_engine,
                )
                _instances[vad_engine] = Segmenter(
                    vad_engine=vad_engine,
                    detect_gender=False,
                )
                logger.info("inaSpeechSegmenter ready (vad_engine=%s).", vad_engine)
    return _instances[vad_engine]


def reset_for_tests() -> None:
    """Discard all cached instances and the availability flag.

    Only for use inside unit tests — resets module state between test cases.
    """
    global _available
    with _lock:
        _instances.clear()
        _available = None
