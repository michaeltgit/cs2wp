from cs2wp_core.mapwin import _swap_after
from cs2wp_core.mapwin import map_win_prob as m


def test_even_game_is_coin_flip():
    assert abs(m(0, 0, True, 0.5) - 0.5) < 1e-9
    assert abs(m(6, 6, False, 0.5) - 0.5) < 1e-9


def test_match_point():
    assert abs(m(12, 11, True, 0.9) - 0.95) < 1e-9   # win -> 13-11, lose -> 12-12 (50%)
    assert abs(m(11, 12, True, 0.5) - 0.25) < 1e-9


def test_overtime_blocks():
    assert abs(m(12, 12, True, 0.5) - 0.5) < 1e-9
    assert abs(m(15, 15, True, 0.5) - 0.5) < 1e-9
    assert abs(m(15, 14, True, 0.5) - 0.75) < 1e-9


def test_monotone_in_round_prob():
    assert m(5, 5, True, 0.8) > m(5, 5, True, 0.2)


def test_side_swaps_match_cs2_rules():
    # halftime after 12; OT keeps sides for 3 rounds, swaps after OT round 3 of each 6-round block
    assert [n for n in range(1, 40) if _swap_after(n)] == [12, 27, 33, 39]


def test_even_overtime_is_a_coin_flip():
    assert abs(m(15, 15, False, 0.5, 0.5) - 0.5) < 1e-9


def test_unsigned_columns_become_signed():
    import numpy as np
    import pandas as pd

    from cs2wp_core.features import signed
    df = signed(pd.DataFrame({"ct": np.array([1000], dtype=np.uint32), "t": np.array([1500], dtype=np.uint32)}))
    assert (df["ct"] - df["t"]).iloc[0] == -500  # uint32 would wrap to 4294966796
