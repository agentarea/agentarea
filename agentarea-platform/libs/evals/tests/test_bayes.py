import random

import pytest
from agentarea_evals.decisions.bayes import prob_b_greater


def _monte_carlo(a_alpha, a_beta, b_alpha, b_beta, n=200_000):
    rng = random.Random(7)
    wins = sum(
        rng.betavariate(b_alpha, b_beta) > rng.betavariate(a_alpha, a_beta) for _ in range(n)
    )
    return wins / n


def test_identical_posteriors_are_a_coin_flip():
    assert prob_b_greater(5, 5, 5, 5) == pytest.approx(0.5, abs=1e-9)


def test_symmetry():
    p = prob_b_greater(3, 10, 8, 4)
    assert prob_b_greater(8, 4, 3, 10) == pytest.approx(1 - p, abs=1e-9)


@pytest.mark.parametrize(
    "params", [(2, 30, 9, 22), (11, 20, 6, 25), (1, 1, 4, 1), (31, 71, 41, 61)]
)
def test_matches_monte_carlo(params):
    assert prob_b_greater(*params) == pytest.approx(_monte_carlo(*params), abs=0.005)


def test_non_integer_alpha_is_refused():
    with pytest.raises(ValueError):
        prob_b_greater(1.5, 1, 1, 1)
