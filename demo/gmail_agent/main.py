"""Entrypoint for the always-on Gmail consumer — `python -m gmail_agent.main`.

Thin wrapper over gmail_agent.consumer.run so the runner has the module path the
workplan specifies. All logic lives in consumer.py (testable without a live
Pub/Sub connection).
"""

from __future__ import annotations

import sys

from gmail_agent.consumer import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
