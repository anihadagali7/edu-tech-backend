#!/usr/bin/env python3
"""CLI script for running the LLM worker.

This script provides a simple interface for running the worker in different modes.
"""

import sys
import os

# Add the project root to the Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

if __name__ == "__main__":
    # Prefer the app-integrated worker implementation which uses app.db and app models
    from app.features.llm.worker import main

    # `main()` in the app-integrated worker is a synchronous entrypoint that
    # calls asyncio.run(_amain()). Calling asyncio.run(main()) here would
    # attempt to nest event loops. Call `main()` directly.
    sys.exit(main())