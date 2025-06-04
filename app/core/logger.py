# app/core/logger.py

import logging
import sys

logger = logging.getLogger("healthcare")
logger.setLevel(logging.INFO)
logger.propagate = False  # Prevent log duplication

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
