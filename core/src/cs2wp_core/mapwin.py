"""Turn round win probability + score into map win probability (what Kalshi map markets price).

CS2 rules (checked against demos): MR12, first to 13, sides swap after round 12. At 12-12,
overtime blocks of 6 rounds, first to 4 within a block. Overtime KEEPS the second-half sides for
its first 3 rounds, swaps after 3, and the next block keeps whatever sides the previous one
ended on. A 3-3 block starts another block, so overtime can repeat; that is solved in closed form.

Future rounds are side-aware: P(team A wins a round) depends on whether A is CT (the map's CT
round win rate, learned in training). Everything here comes from the model; nothing is hand-set.
"""

from functools import lru_cache

HALF, WIN = 12, 13
OT_HALF, OT_WIN = 3, 4


def round_probs(q_ct: float) -> tuple[float, float]:
    """(P(A wins a round as CT), P(A wins a round as T))."""
    return q_ct, 1 - q_ct


def map_win_prob(a: int, b: int, a_is_ct: bool, p_round_a: float, q_ct: float = 0.5) -> float:
    """P(team A wins the map), evaluated during a round played at score a-b.

    p_round_a: P(A wins the current round), from the round model.
    q_ct: P(the CT side wins a round) on this map (from training).
    """
    pc, pt = round_probs(q_ct)
    key = (round(pc, 3), round(pt, 3))
    return p_round_a * _after(a + 1, b, a_is_ct, key) + (1 - p_round_a) * _after(a, b + 1, a_is_ct, key)


def _swap_after(n: int) -> bool:
    """Do sides swap after the n-th round of the map has been played?"""
    if n == HALF:
        return True
    if n > 2 * HALF:
        return (n - 2 * HALF) % (2 * OT_HALF) == OT_HALF  # after OT rounds 3, 9, 15, ...
    return False


def _after(a, b, a_was_ct, key):
    a_ct_next = (not a_was_ct) if _swap_after(a + b) else a_was_ct
    return _v(a, b, a_ct_next, key)


@lru_cache(maxsize=200_000)
def _v(a, b, a_ct, key):
    """P(A wins the map) at score a-b before the next round, A on CT if a_ct."""
    pc, pt = key
    if a == WIN and b < HALF:
        return 1.0
    if b == WIN and a < HALF:
        return 0.0
    if a + b >= 2 * HALF and (a < HALF or b < HALF):  # impossible / decided score
        return 1.0 if a > b else 0.0 if b > a else 0.5
    if a + b < 2 * HALF:
        p = pc if a_ct else pt
        nxt = (not a_ct) if _swap_after(a + b + 1) else a_ct
        return p * _v(a + 1, b, nxt, key) + (1 - p) * _v(a, b + 1, nxt, key)
    # overtime: reduce to the current block (each finished 3-3 block resets it)
    k = min((a - HALF) // OT_HALF, (b - HALF) // OT_HALF)
    return _block(a - HALF - OT_HALF * k, b - HALF - OT_HALF * k, a_ct, key)


@lru_cache(maxsize=4096)
def _block(u, v, a_ct, key):
    """Inside an overtime block at u-v (A on CT if a_ct)."""
    if u == OT_WIN:
        return 1.0
    if v == OT_WIN:
        return 0.0
    if u == OT_HALF and v == OT_HALF:
        return _ot_start(a_ct, key)  # the next block keeps the current sides
    pc, pt = key
    p = pc if a_ct else pt
    nxt = (not a_ct) if (u + v + 1) == OT_HALF else a_ct
    return p * _block(u + 1, v, nxt, key) + (1 - p) * _block(u, v + 1, nxt, key)


@lru_cache(maxsize=256)
def _ot_start(a_ct, key):
    """P(A wins overtime) from the start of a block. Consecutive blocks start on opposite sides,
    so V(c) = W(c) + D(c) * V(not c); solve the 2x2 system exactly."""
    w1, d1 = _block_outcome(a_ct, key)
    w2, d2 = _block_outcome(not a_ct, key)
    return (w1 + d1 * w2) / (1 - d1 * d2) if d1 * d2 < 1 else 0.5


@lru_cache(maxsize=256)
def _block_outcome(a_ct, key):
    """(P(A wins the block), P(block ends 3-3)) from 0-0 with A on CT if a_ct."""
    pc, pt = key
    probs = {(0, 0, a_ct): 1.0}
    win = draw = 0.0
    for _ in range(2 * OT_HALF):
        nxt = {}
        for (u, v, c), pr in probs.items():
            p = pc if c else pt
            c2 = (not c) if (u + v + 1) == OT_HALF else c
            for uu, vv, q in ((u + 1, v, p), (u, v + 1, 1 - p)):
                m = pr * q
                if uu == OT_WIN:
                    win += m
                elif vv == OT_WIN:
                    continue
                elif uu == OT_HALF and vv == OT_HALF:
                    draw += m
                else:
                    nxt[(uu, vv, c2)] = nxt.get((uu, vv, c2), 0.0) + m
        probs = nxt
    return win, draw
