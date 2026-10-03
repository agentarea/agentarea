"""Exact comparison of two Beta posteriors."""

from math import exp, lgamma, log


def _lbeta(a: float, b: float) -> float:
    return lgamma(a) + lgamma(b) - lgamma(a + b)


def prob_b_greater(a_alpha: int, a_beta: int, b_alpha: int, b_beta: int) -> float:
    """P(X_B > X_A) for X_A ~ Beta(a_alpha, a_beta), X_B ~ Beta(b_alpha, b_beta).

    Closed form (Evan Miller), exact for an integer ``b_alpha``; with a
    Beta(1, 1) prior every parameter is a count plus one.
    """
    for value in (a_alpha, a_beta, b_alpha, b_beta):
        if value != int(value) or value < 1:
            raise ValueError(f"Beta parameters must be positive integers, got {value}")
    total = sum(
        exp(
            _lbeta(a_alpha + i, a_beta + b_beta)
            - log(b_beta + i)
            - _lbeta(1 + i, b_beta)
            - _lbeta(a_alpha, a_beta)
        )
        for i in range(int(b_alpha))
    )
    return min(1.0, max(0.0, total))
