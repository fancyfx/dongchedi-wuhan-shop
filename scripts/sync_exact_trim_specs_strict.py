#!/usr/bin/env python3
"""CI entrypoint: exact-trim sync from AutoHome current + historical data.

Dongchedi runner endpoints are intentionally not used here because GitHub-hosted
runners receive incomplete/blocked responses. The old resilient synchronizer is
kept for manual diagnostics only.
"""
from sync_exact_trim_specs_autohome import main

if __name__ == "__main__":
    main()
