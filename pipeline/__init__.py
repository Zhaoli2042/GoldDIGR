"""Gold Pipeline – systematic mining of supplementary information."""
__version__ = "0.1.0"

import logging
import sys
from pathlib import Path
from typing import Sequence


def setup_logging(
    verbose: bool = False,
    log_filename: str = "pipeline.log",
    quiet_loggers: Sequence[str] = (),
) -> None:
    """Configure logging for both pipeline and plugin entry points.

    Parameters
    ----------
    verbose : bool
        If True, set level to DEBUG; otherwise INFO.
    log_filename : str
        Name of the log file written under data/db/ (e.g. "pipeline.log"
        or "plugin.log").
    quiet_loggers : sequence of str
        Logger names to suppress to WARNING level (e.g. "selenium", "torch").
    """
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [logging.StreamHandler(sys.stdout)]

    # Try container path first, fall back to local
    for log_dir in [Path("/app/data/db"), Path("data/db")]:
        if log_dir.exists() or log_dir.parent.exists():
            log_dir.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(str(log_dir / log_filename), mode="a"))
            break

    logging.basicConfig(
        level=level,
        format="%(asctime)s │ %(name)-25s │ %(levelname)-7s │ %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )

    for name in quiet_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)
