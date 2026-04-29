"""``params_hash`` correctness — the cache-key spec is locked, so the test
suite is the lock."""

from __future__ import annotations

from signal_trck.indicators.params import params_hash


def test_basic_dict_hashes_stably() -> None:
    h1 = params_hash({"period": 50})
    h2 = params_hash({"period": 50})
    assert h1 == h2
    assert len(h1) == 16


def test_different_params_different_hash() -> None:
    assert params_hash({"period": 14}) != params_hash({"period": 21})
    assert params_hash({"fast": 12, "slow": 26}) != params_hash({"fast": 8, "slow": 21})


def test_key_order_does_not_matter() -> None:
    h1 = params_hash({"fast": 12, "slow": 26, "signal": 9})
    h2 = params_hash({"signal": 9, "fast": 12, "slow": 26})
    assert h1 == h2


def test_int_and_int_float_collide_by_design() -> None:
    """``period: 50`` and ``period: 50.0`` must hash equally so JSON round-trip
    doesn't bust the cache."""
    assert params_hash({"period": 50}) == params_hash({"period": 50.0})


def test_genuinely_fractional_floats_do_not_collapse() -> None:
    """``period: 50.5`` is a different parameter and must not collapse to 50."""
    assert params_hash({"period": 50.5}) != params_hash({"period": 50})


def test_nested_dicts_normalize_recursively() -> None:
    a = {"outer": {"inner": 1.0}}
    b = {"outer": {"inner": 1}}
    assert params_hash(a) == params_hash(b)


def test_lists_normalize_too() -> None:
    assert params_hash({"weights": [1.0, 2.0]}) == params_hash({"weights": [1, 2]})


def test_bool_does_not_canonicalize_to_int() -> None:
    """``True`` is not the same parameter as ``1``."""
    assert params_hash({"flag": True}) != params_hash({"flag": 1})
    assert params_hash({"flag": False}) != params_hash({"flag": 0})


def test_empty_dict_has_stable_hash() -> None:
    h = params_hash({})
    assert isinstance(h, str)
    assert len(h) == 16
    assert h == params_hash({})
