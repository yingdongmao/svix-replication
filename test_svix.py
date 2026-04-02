"""
Unit tests for the up-svix and down-svix implementation.

These tests validate the core integral logic without requiring a WRDS connection
by constructing synthetic option data and checking the mathematical properties.
"""

import sys
import os
import numpy as np
import pandas as pd

# Allow importing from src/
sys.path.insert(0, os.path.dirname(__file__))

from src.svix import (
    _compute_svix2_integral,
    _compute_up_svix2_integral,
    _compute_down_svix2_integral,
    compute_svix,
)

# ---------------------------------------------------------------------------
# Helper: build a minimal synthetic options group
# ---------------------------------------------------------------------------

def make_group(put_strikes, put_prices, call_strikes, call_prices,
               S=100.0, F=100.0, R_f=1.02, days=30):
    """Return a DataFrame mimicking a single (date, exdate) group."""
    rows = []
    for k, p in zip(put_strikes, put_prices):
        rows.append({'cp_flag': 'P', 'strike': k, 'mid': p,
                     'S': S, 'F': F, 'R_f': R_f, 'days_to_expiry': days})
    for k, p in zip(call_strikes, call_prices):
        rows.append({'cp_flag': 'C', 'strike': k, 'mid': p,
                     'S': S, 'F': F, 'R_f': R_f, 'days_to_expiry': days})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Test 1: _trapz_integral removed (now internal to _compute_all_integrals)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 2: up + down = full (additive decomposition of SVIX²)
# ---------------------------------------------------------------------------

def test_additivity():
    """up-SVIX² + down-SVIX² must equal full SVIX² for every group."""
    put_strikes  = [80.0, 85.0, 90.0, 95.0]
    put_prices   = [2.0,  3.0,  5.0,  8.0]
    call_strikes = [100.0, 105.0, 110.0, 115.0, 120.0]
    call_prices  = [6.0,   4.0,   2.5,   1.5,   0.8]

    grp = make_group(put_strikes, put_prices, call_strikes, call_prices,
                     S=100.0, F=100.0, R_f=1.02, days=30)

    full = _compute_svix2_integral(grp)
    up   = _compute_up_svix2_integral(grp)
    down = _compute_down_svix2_integral(grp)

    assert full is not np.nan and not np.isnan(full), "full SVIX² is NaN"
    assert up   is not np.nan and not np.isnan(up),   "up-SVIX² is NaN"
    assert down is not np.nan and not np.isnan(down), "down-SVIX² is NaN"

    assert abs((up + down) - full) < 1e-10, (
        f"Additivity violated: up={up:.6f} + down={down:.6f} = {up+down:.6f} != full={full:.6f}"
    )
    print(f"PASS  test_additivity  (full={full:.6f}, up={up:.6f}, down={down:.6f})")


# ---------------------------------------------------------------------------
# Test 3: calls-only group → down-SVIX² is NaN, up-SVIX² is valid
# ---------------------------------------------------------------------------

def test_calls_only():
    """When only calls are present, down-SVIX² should be NaN and up-SVIX² valid."""
    call_strikes = [100.0, 105.0, 110.0]
    call_prices  = [5.0,   3.0,   1.5]

    grp = make_group([], [], call_strikes, call_prices,
                     S=100.0, F=100.0, R_f=1.02, days=30)

    up   = _compute_up_svix2_integral(grp)
    down = _compute_down_svix2_integral(grp)

    assert not np.isnan(up),   "up-SVIX² should be valid when only calls are present"
    assert np.isnan(down),     "down-SVIX² should be NaN when no puts are present"
    print(f"PASS  test_calls_only  (up={up:.6f}, down=NaN)")


# ---------------------------------------------------------------------------
# Test 4: puts-only group → up-SVIX² is NaN, down-SVIX² is valid
# ---------------------------------------------------------------------------

def test_puts_only():
    """When only puts are present, up-SVIX² should be NaN and down-SVIX² valid."""
    put_strikes = [80.0, 85.0, 90.0, 95.0]
    put_prices  = [2.0,  3.5,  5.0,  8.0]

    grp = make_group(put_strikes, put_prices, [], [],
                     S=100.0, F=100.0, R_f=1.02, days=30)

    up   = _compute_up_svix2_integral(grp)
    down = _compute_down_svix2_integral(grp)

    assert np.isnan(up),       "up-SVIX² should be NaN when no calls are present"
    assert not np.isnan(down), "down-SVIX² should be valid when only puts are present"
    print(f"PASS  test_puts_only  (up=NaN, down={down:.6f})")


# ---------------------------------------------------------------------------
# Test 5: compute_svix end-to-end with synthetic data
# ---------------------------------------------------------------------------

def test_compute_svix_end_to_end():
    """
    Build a minimal synthetic options DataFrame and verify that compute_svix
    produces the expected output columns for each target horizon.
    """
    from datetime import date, timedelta

    base_date = pd.Timestamp("2020-01-02")
    # Create two expiries: 30 days and 60 days out
    expiries = [base_date + pd.Timedelta(days=d) for d in [30, 60]]

    S, R_f = 100.0, 1.02
    rows = []
    for exdate in expiries:
        days = (exdate - base_date).days
        F = S * R_f
        # OTM puts: K < F
        for k, p in [(80, 1.0), (85, 2.0), (90, 4.0), (95, 7.0)]:
            rows.append({'date': base_date, 'exdate': exdate, 'cp_flag': 'P',
                         'strike': float(k), 'mid': p, 'S': S, 'F': F,
                         'R_f': R_f, 'days_to_expiry': days})
        # OTM calls: K >= F
        for k, p in [(102, 6.0), (105, 4.0), (110, 2.0), (115, 1.0)]:
            rows.append({'date': base_date, 'exdate': exdate, 'cp_flag': 'C',
                         'strike': float(k), 'mid': p, 'S': S, 'F': F,
                         'R_f': R_f, 'days_to_expiry': days})

    options = pd.DataFrame(rows)
    result = compute_svix(options)

    assert len(result) == 1, f"Expected 1 row, got {len(result)}"

    expected_cols = []
    for t in [30, 60, 90, 180, 360]:
        expected_cols += [
            f'svix2_{t}d', f'rf_{t}d', f'svix_index_{t}d', f'lower_bound_{t}d',
            f'up_svix2_{t}d', f'up_svix_{t}d',
            f'down_svix2_{t}d', f'down_svix_{t}d',
        ]

    for col in expected_cols:
        assert col in result.columns, f"Missing column: {col}"

    # Verify additivity in the output for the 30-day horizon
    row = result.iloc[0]
    up30   = row['up_svix2_30d']
    down30 = row['down_svix2_30d']
    full30 = row['svix2_30d']
    if not any(np.isnan([up30, down30, full30])):
        assert abs((up30 + down30) - full30) < 1e-10, (
            f"Additivity violated in output: {up30} + {down30} != {full30}"
        )

    print("PASS  test_compute_svix_end_to_end")
    print(f"      Columns present: {list(result.columns)}")
    print(f"      30d: svix={row['svix_index_30d']:.4f}%, "
          f"up={row['up_svix_30d']:.4f}%, down={row['down_svix_30d']:.4f}%")


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Running SVIX unit tests...\n")
    test_additivity()
    test_calls_only()
    test_puts_only()
    test_compute_svix_end_to_end()
    print("\nAll tests passed.")
