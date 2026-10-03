import hashlib

ARM_CONTROL = "control"
ARM_CANDIDATE = "candidate"
_ARM_ORDER = (ARM_CONTROL, ARM_CANDIDATE)


def pick_arm(key: str, weights: dict[str, int]) -> str:
    """The arm a run keyed by ``key`` belongs to, stable for that key.

    ``weights`` are whole percentages summing to 100. A run keeps its arm for
    its whole life (follow-ups, retries, continuations reuse the task id), so
    the key decides once.
    """
    if sum(weights.values()) != 100:
        raise ValueError(f"arm weights must sum to 100, got {weights}")
    bucket = int(hashlib.sha256(key.encode()).hexdigest(), 16) % 100
    threshold = 0
    for arm in (*_ARM_ORDER, *sorted(set(weights) - set(_ARM_ORDER))):
        threshold += weights.get(arm, 0)
        if bucket < threshold:
            return arm
    raise AssertionError("unreachable: weights sum to 100")
