"""Logging configuration for the AVA backend."""

import logging
import sys

# ============================================================
# BEGIN: Logging Configuration
# ============================================================


def configure_logging(level: str = "info") -> None:
    """Configure root logging for the AVA backend.

    Args:
        level: Log level string (e.g. "info", "debug").
    """
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        stream=sys.stdout,
        force=True,
    )


# ============================================================
# END: Logging Configuration
# ============================================================
