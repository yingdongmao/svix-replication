"""
SVIX Computation Module

This module provides functions to download OptionMetrics data from WRDS,
clean it according to Martin (2017), and compute the SVIX index, the
lower bound on the equity premium, and the one-sided SVIX variants:

  - up-svix: SVIX computed using call options only (upside variance)
  - down-svix: SVIX computed using put options only (downside variance)

The one-sided integrals are computed by splitting the **combined** OTM
option array at the forward price F, so that the CBOE discretisation
weights (dK) are shared and the additivity property holds exactly:

    SVIX² = up-SVIX² + down-SVIX²

Reference:
Martin, I. (2017). "What is the Expected Return on the Market?"
The Quarterly Journal of Economics, 132(1), 367-433.
"""

import wrds
import pandas as pd
import numpy as np
from scipy.interpolate import interp1d
import time
import warnings

warnings.filterwarnings('ignore')

# Constants from the paper
SPX_SECID = 108105
MIN_DAYS_TO_EXPIRY = 7
MAX_DAYS_TO_EXPIRY = 550
TARGET_DAYS = [30, 60, 90, 180, 360]

def download_data(start_year, end_year, username):
    """
    Download OptionMetrics data year by year from WRDS.
    Downloads in monthly chunks to avoid WRDS SSL timeouts.
    
    Args:
        start_year (int): Start year (e.g., 1996)
        end_year (int): End year (e.g., 2023)
        username (str): WRDS username
        
    Returns:
        tuple: (options_df, zeros_df, index_px_df)
    """
    print(f"Connecting to WRDS as {username}...")
    db = wrds.Connection(wrds_username=username, autoconnect=False)
    db.connect()
    print("Connected successfully.")

    all_opts, all_zeros, all_idx = [], [], []

    for year in range(start_year, end_year + 1):
        print(f"\n--- Downloading data for {year} ---")
        
        # 1. Index Prices
        print("  Fetching index prices...")
        idx = db.raw_sql(f"SELECT date, close FROM optionm_all.secprd{year} WHERE secid = {SPX_SECID}")
        all_idx.append(idx)
        
        # 2. Zero Curve
        print("  Fetching zero curve...")
        zer = db.raw_sql(f"SELECT date, days, rate FROM optionm_all.zerocd WHERE EXTRACT(YEAR FROM date) = {year}")
        all_zeros.append(zer)
        
        # 3. Options Data (Chunked by month)
        print("  Fetching options data (monthly chunks)...")
        for month in range(1, 13):
            start_date = f"{year}-{month:02d}-01"
            if month == 12:
                end_date = f"{year}-12-31"
            else:
                next_month = pd.Timestamp(f"{year}-{month+1:02d}-01")
                end_date = (next_month - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                
            query = f"""
                SELECT secid, date, exdate, cp_flag, strike_price,
                       best_bid, best_offer, expiry_indicator
                FROM optionm_all.opprcd{year}
                WHERE secid = {SPX_SECID}
                  AND date >= '{start_date}' AND date <= '{end_date}'
                  AND best_bid IS NOT NULL AND best_offer IS NOT NULL
                  AND best_bid >= 0 AND best_offer >= 0
            """
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    opt = db.raw_sql(query)
                    all_opts.append(opt)
                    print(f"    Month {month:02d}: {len(opt)} rows")
                    break
                except Exception as e:
                    print(f"    Error on month {month:02d} (Attempt {attempt+1}/{max_retries}): {e}")
                    time.sleep(5)
                    try: db.close()
                    except: pass
                    db = wrds.Connection(wrds_username=username, autoconnect=False)
                    db.connect()
            else:
                print(f"    FAILED to fetch month {month:02d} after {max_retries} attempts.")

    db.close()
    print("\nData download complete.")

    return (pd.concat(all_opts, ignore_index=True),
            pd.concat(all_zeros, ignore_index=True),
            pd.concat(all_idx, ignore_index=True))

def clean_data(options, zeros, index_px):
    """
    Clean data according to Martin (2017) Appendix A.
    """
    print("\nCleaning data...")
    
    options['date'] = pd.to_datetime(options['date'])
    options['exdate'] = pd.to_datetime(options['exdate'])
    zeros['date'] = pd.to_datetime(zeros['date'])
    index_px['date'] = pd.to_datetime(index_px['date'])

    # Convert strike to dollars
    options['strike'] = options['strike_price'] / 1000.0
    options['mid'] = (options['best_bid'] + options['best_offer']) / 2.0

    # Step 1: Delete replicated entries
    options = options.drop_duplicates(subset=['secid', 'date', 'exdate', 'cp_flag', 'strike_price'])
    
    # Step 2: Delete options with zero bid
    options = options[options['best_bid'] > 0]
    
    # Step 3: Delete Quarterly options
    options = options[options['expiry_indicator'].isna() | (options['expiry_indicator'] == '')]
    
    # Step 4: Filter by days to expiry [7, 550)
    options['days_to_expiry'] = (options['exdate'] - options['date']).dt.days
    options = options[(options['days_to_expiry'] >= MIN_DAYS_TO_EXPIRY) &
                      (options['days_to_expiry'] < MAX_DAYS_TO_EXPIRY)]

    print(f"Cleaned options: {len(options)} rows")
    return options, zeros, index_px

def compute_rf_and_forward(options, zeros, index_px):
    """Compute continuously compounded risk-free rate and forward price."""
    print("Computing risk-free rates and forward prices...")
    
    zeros_grp = zeros.groupby('date')

    def get_rf(date, days):
        if date not in zeros_grp.groups: return np.nan
        zd = zeros_grp.get_group(date).sort_values('days')
        d_arr = zd['days'].values.astype(float)
        r_arr = zd['rate'].values / 100.0
        
        if len(d_arr) == 0: return np.nan
        if days <= d_arr[0]: r = r_arr[0]
        elif days >= d_arr[-1]: r = r_arr[-1]
        else: r = float(interp1d(d_arr, r_arr, kind='linear')(days))
        return np.exp(r * days / 365.0)

    idx_map = index_px.set_index('date')['close'].to_dict()
    options['S'] = options['date'].map(idx_map)

    pairs = options[['date', 'exdate', 'days_to_expiry']].drop_duplicates()
    rf_rows = [{'date': r['date'], 'exdate': r['exdate'],
                'R_f': get_rf(r['date'], r['days_to_expiry'])} for _, r in pairs.iterrows()]
    
    options = options.merge(pd.DataFrame(rf_rows), on=['date', 'exdate'], how='left')
    options['F'] = options['S'] * options['R_f']

    # Step 5: For each strike, select the option whose mid price is lower
    options = options.sort_values('mid').drop_duplicates(subset=['date', 'exdate', 'strike'], keep='first')
    return options

# ---------------------------------------------------------------------------
# Core integral computation
# ---------------------------------------------------------------------------

def _compute_all_integrals(grp):
    """
    Compute the full, upside, and downside SVIX² integrals for a single
    (date, exdate) group in a single pass.

    The combined OTM option array (puts with K < F, calls with K >= F) is
    assembled once and the CBOE discretisation weights (dK) are computed
    once.  The upside and downside integrals are then obtained by masking
    the shared weight array, which guarantees exact additivity:

        full SVIX² == up-SVIX² + down-SVIX²

    Returns
    -------
    dict with keys 'svix2', 'up_svix2', 'down_svix2'
    """
    nan_result = {'svix2': np.nan, 'up_svix2': np.nan, 'down_svix2': np.nan}

    if len(grp) < 2:
        return nan_result

    days = grp['days_to_expiry'].iloc[0]
    T    = days / 365.0
    R_f  = grp['R_f'].iloc[0]
    S    = grp['S'].iloc[0]
    F    = grp['F'].iloc[0]

    if any(pd.isna([R_f, S, F])) or S <= 0 or R_f <= 0:
        return nan_result

    grp   = grp.sort_values('strike')
    puts  = grp[(grp['cp_flag'] == 'P') & (grp['strike'] <  F)][['strike', 'mid']]
    calls = grp[(grp['cp_flag'] == 'C') & (grp['strike'] >= F)][['strike', 'mid']]

    otm = pd.concat([
        puts.rename(columns={'mid': 'price'}).assign(side='down'),
        calls.rename(columns={'mid': 'price'}).assign(side='up'),
    ]).sort_values('strike')

    if len(otm) < 2:
        return nan_result

    K    = otm['strike'].values
    P    = otm['price'].values
    side = otm['side'].values
    N    = len(K)

    # CBOE discretisation weights — computed once on the combined array
    dK       = np.empty(N)
    dK[0]    = K[1]  - K[0]
    dK[-1]   = K[-1] - K[-2]
    if N > 2:
        dK[1:-1] = (K[2:] - K[:-2]) / 2.0

    scale = 2.0 / (T * R_f * S**2)

    # Full integral
    svix2 = scale * np.sum(P * dK)

    # Upside: calls only (side == 'up')
    mask_up   = (side == 'up')
    up_svix2  = scale * np.sum(P[mask_up] * dK[mask_up]) if mask_up.any() else np.nan

    # Downside: puts only (side == 'down')
    mask_down   = (side == 'down')
    down_svix2  = scale * np.sum(P[mask_down] * dK[mask_down]) if mask_down.any() else np.nan

    return {'svix2': svix2, 'up_svix2': up_svix2, 'down_svix2': down_svix2}


# ---------------------------------------------------------------------------
# Legacy single-value wrappers (kept for backward compatibility / testing)
# ---------------------------------------------------------------------------

def _compute_svix2_integral(grp):
    """Return full SVIX² for a single (date, exdate) group."""
    return _compute_all_integrals(grp)['svix2']


def _compute_up_svix2_integral(grp):
    """Return upside SVIX² (calls only) for a single (date, exdate) group."""
    return _compute_all_integrals(grp)['up_svix2']


def _compute_down_svix2_integral(grp):
    """Return downside SVIX² (puts only) for a single (date, exdate) group."""
    return _compute_all_integrals(grp)['down_svix2']


# ---------------------------------------------------------------------------
# Main compute function
# ---------------------------------------------------------------------------

def compute_svix(options):
    """
    Compute SVIX², up-SVIX², and down-SVIX² for all expiries and interpolate
    to target horizons (30, 60, 90, 180, 360 days).

    Output columns per horizon T:
      svix2_{T}d        – full SVIX² (puts + calls)
      rf_{T}d           – gross risk-free rate factor
      svix_index_{T}d   – SVIX index (annualised %, sqrt of svix2 × 100)
      lower_bound_{T}d  – lower bound on equity premium (R_f × svix2 × 100)
      up_svix2_{T}d     – upside SVIX² (calls only)
      up_svix_{T}d      – upside SVIX index (annualised %, sqrt of up_svix2 × 100)
      down_svix2_{T}d   – downside SVIX² (puts only)
      down_svix_{T}d    – downside SVIX index (annualised %, sqrt of down_svix2 × 100)

    By construction:  svix2_{T}d == up_svix2_{T}d + down_svix2_{T}d
    """
    print("Computing SVIX² integrals per expiry (full, up, down)...")

    # Compute all three integrals in a single grouped pass
    integral_rows = []
    for (date, exdate), grp in options.groupby(['date', 'exdate']):
        res = _compute_all_integrals(grp)
        res['date']   = date
        res['exdate'] = exdate
        integral_rows.append(res)

    svix_exp = pd.DataFrame(integral_rows)
    svix_exp['days_to_expiry'] = (svix_exp['exdate'] - svix_exp['date']).dt.days

    # Drop rows where full SVIX² is invalid
    svix_exp = svix_exp.dropna(subset=['svix2'])
    svix_exp = svix_exp[svix_exp['svix2'] > 0]

    # Attach risk-free rates
    rf_map   = options[['date', 'exdate', 'R_f']].drop_duplicates()
    svix_exp = svix_exp.merge(rf_map, on=['date', 'exdate'], how='left')

    print("Interpolating to target horizons...")

    def interp_series(grp, col, targets):
        """Linearly interpolate a column in grp to each target day count."""
        sub = (grp[grp['days_to_expiry'] >= MIN_DAYS_TO_EXPIRY]
               .dropna(subset=[col])
               .sort_values('days_to_expiry'))
        if len(sub) < 1:
            return {t: np.nan for t in targets}

        d = sub['days_to_expiry'].values.astype(float)
        v = sub[col].values
        out = {}
        for t in targets:
            if len(d) == 1:
                out[t] = v[0]
            elif t <= d[0]:
                slope  = (v[1] - v[0]) / (d[1] - d[0]) if len(d) > 1 else 0
                out[t] = max(v[0] + slope * (t - d[0]), 1e-8)
            elif t >= d[-1]:
                slope  = (v[-1] - v[-2]) / (d[-1] - d[-2]) if len(d) > 1 else 0
                out[t] = max(v[-1] + slope * (t - d[-1]), 1e-8)
            else:
                out[t] = float(interp1d(d, v, kind='linear')(t))
        return out

    rows = []
    for date, grp in svix_exp.groupby('date'):
        res_svix2      = interp_series(grp, 'svix2',      TARGET_DAYS)
        res_up_svix2   = interp_series(grp, 'up_svix2',   TARGET_DAYS)
        res_down_svix2 = interp_series(grp, 'down_svix2', TARGET_DAYS)

        # Interpolate risk-free rate
        d   = grp['days_to_expiry'].values.astype(float)
        r   = grp['R_f'].values
        res_rf = {}
        if len(d) > 0:
            for t in TARGET_DAYS:
                if len(d) == 1:   res_rf[t] = r[0]
                elif t <= d[0]:   res_rf[t] = r[0]
                elif t >= d[-1]:  res_rf[t] = r[-1]
                else:             res_rf[t] = float(interp1d(d, r, kind='linear')(t))
        else:
            res_rf = {t: np.nan for t in TARGET_DAYS}

        row = {'date': date}
        for t in TARGET_DAYS:
            svix2      = res_svix2[t]
            up_svix2   = res_up_svix2[t]
            down_svix2 = res_down_svix2[t]
            rf         = res_rf[t]

            # Full SVIX
            row[f'svix2_{t}d']       = svix2
            row[f'rf_{t}d']          = rf
            row[f'svix_index_{t}d']  = np.sqrt(svix2) * 100 if (svix2 and svix2 > 0) else np.nan
            row[f'lower_bound_{t}d'] = rf * svix2 * 100 if (svix2 and rf and svix2 > 0) else np.nan

            # Up-SVIX (calls only)
            row[f'up_svix2_{t}d']    = up_svix2
            row[f'up_svix_{t}d']     = (np.sqrt(up_svix2) * 100
                                         if (up_svix2 and not np.isnan(up_svix2) and up_svix2 > 0)
                                         else np.nan)

            # Down-SVIX (puts only)
            row[f'down_svix2_{t}d']  = down_svix2
            row[f'down_svix_{t}d']   = (np.sqrt(down_svix2) * 100
                                         if (down_svix2 and not np.isnan(down_svix2) and down_svix2 > 0)
                                         else np.nan)

        rows.append(row)

    return pd.DataFrame(rows).sort_values('date').reset_index(drop=True)
