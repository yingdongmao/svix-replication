"""
SVIX Replication: Main Execution Script

This script uses the `svix` module to download data from WRDS,
compute the SVIX index (full, up, and down variants), and save
the results to a CSV file.
"""

import argparse
import os
from src.svix import download_data, clean_data, compute_rf_and_forward, compute_svix

def main():
    parser = argparse.ArgumentParser(description="Replicate Martin (2017) SVIX measure")
    parser.add_argument("--username", type=str, required=True, help="WRDS username")
    parser.add_argument("--start-year", type=int, default=1996, help="Start year (default: 1996)")
    parser.add_argument("--end-year", type=int, default=2012, help="End year (default: 2012)")
    parser.add_argument("--output", type=str, default="data/svix.pkl", help="Output PKL path")
    
    args = parser.parse_args()
    
    print("="*60)
    print(f"SVIX Replication: {args.start_year} to {args.end_year}")
    print("="*60)
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    
    # 1. Download
    options, zeros, index_px = download_data(args.start_year, args.end_year, args.username)
    
    # 2. Clean
    options, zeros, index_px = clean_data(options, zeros, index_px)
    
    # 3. Risk-Free & Forward
    options = compute_rf_and_forward(options, zeros, index_px)
    
    # 4. Compute SVIX (full, up, down)
    result = compute_svix(options)
    
    # 5. Save
    result.to_pickle(args.output, index=False)
    print(f"\nSuccess! Results saved to {args.output}")
    
    # Print summary
    print("\nSummary Statistics (Lower Bound on Equity Premium, %):")
    for t in [30, 60, 90, 180, 360]:
        col = f'lower_bound_{t}d'
        if col in result.columns:
            s = result[col].dropna()
            print(f"  {t} days: Mean={s.mean():.2f}%, Std={s.std():.2f}%, Max={s.max():.2f}%")

    print("\nSummary Statistics (SVIX Index, annualised %):")
    for t in [30, 60, 90, 180, 360]:
        col = f'svix_index_{t}d'
        if col in result.columns:
            s = result[col].dropna()
            print(f"  {t} days: Mean={s.mean():.2f}%, Std={s.std():.2f}%")

    print("\nSummary Statistics (Up-SVIX — calls only, annualised %):")
    for t in [30, 60, 90, 180, 360]:
        col = f'up_svix_{t}d'
        if col in result.columns:
            s = result[col].dropna()
            print(f"  {t} days: Mean={s.mean():.2f}%, Std={s.std():.2f}%")

    print("\nSummary Statistics (Down-SVIX — puts only, annualised %):")
    for t in [30, 60, 90, 180, 360]:
        col = f'down_svix_{t}d'
        if col in result.columns:
            s = result[col].dropna()
            print(f"  {t} days: Mean={s.mean():.2f}%, Std={s.std():.2f}%")

if __name__ == "__main__":
    main()
