"""CLI composition root; the ingestion slice owns the implementation."""

import logging

from app.features.ingestion.seed import cli

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    cli()
