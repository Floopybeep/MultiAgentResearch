"""Select assignments dropped at the Lead-to-Worker boundary."""

import random

from ..config import ConnectionDropConfig


def select_dropped(config: ConnectionDropConfig, batch: int, dispatched: int) -> list[int]:
    """Return sorted zero-based positions whose assignments are not delivered."""
    if not config.enabled or batch < config.batch:
        return []
    if batch > config.batch and not config.persistent:
        return []
    count = max(dispatched - config.num_delivered, 0)
    positions = list(range(dispatched))
    if config.select == "last":
        return positions[dispatched - count:]
    return sorted(random.Random(f"{config.seed}:{batch}").sample(positions, count))
