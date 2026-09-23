"""LiveKit Agents worker entry — real implementation is Sprint 3 (docs/11_BUILD_PLAN.md S3.1).

Sprint 0 ships this stub only so `docker compose up` can bring up an `agent` container (matching
docs/10_DEPLOYMENT_AND_OPS.md §2's service list) without a crash loop, while carrying zero call-
handling logic ahead of its sprint.
"""

from __future__ import annotations

import time

from app.core.logging import configure_logging, get_logger


def main() -> None:
    configure_logging()
    logger = get_logger()
    logger.info("agent.stub.started", note="LiveKit agent runtime lands in Sprint 3 (S3.1)")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
