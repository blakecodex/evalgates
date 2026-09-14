# the psi arithmetic, pinned on inputs small enough to check by hand.
import math

from evalgates.families.drift import psi


def test_identical_distributions_give_zero():
    scores = [0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14] * 50
    value, _ = psi(scores, list(scores))
    assert value < 1e-9


def test_two_bin_example_by_hand():
    # reference: half below 0.5, half above. current: 80/20.
    # one edge at 0.5 -> shares a=(0.5, 0.5), b=(0.8, 0.2)
    # psi = (0.5-0.8)ln(0.5/0.8) + (0.5-0.2)ln(0.5/0.2)
    ref = [0.1] * 500 + [0.9] * 500
    cur = [0.1] * 800 + [0.9] * 200
    value, table = psi(ref, cur, n_bins=2)
    by_hand = (0.5 - 0.8) * math.log(0.5 / 0.8) + (0.5 - 0.2) * math.log(0.5 / 0.2)
    assert abs(value - by_hand) < 1e-9
    assert len(table) == 2


def test_every_term_is_non_negative():
    # (a-b) and ln(a/b) always share a sign, so no term can be negative
    ref = [i / 1000 for i in range(1000)]
    cur = [((i * 37) % 1000) / 900 for i in range(1000)]
    _, table = psi(ref, cur)
    assert all(row["term"] >= 0 for row in table)


def test_shift_direction_does_not_matter_much():
    # swapping cohorts changes which side sets the bin edges, but a big
    # shift stays big measured either way
    ref = [0.05 + (i % 100) / 1000 for i in range(2000)]
    cur = [x + 0.05 for x in ref]
    up, _ = psi(ref, cur)
    down, _ = psi(cur, ref)
    assert up > 0.2 and down > 0.2


def test_empty_bin_is_floored_not_crashed():
    ref = [0.1] * 500 + [0.9] * 500
    cur = [0.1] * 1000                      # nothing lands in the top bin
    value, _ = psi(ref, cur, n_bins=2)
    assert math.isfinite(value) and value > 0
