# SVIX Replication: Martin (2017)

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

This repository provides a complete, robust Python implementation to replicate the **SVIX index** and the **lower bound on the equity premium** introduced in Ian Martin's seminal paper:

> Martin, I. (2017). "What is the Expected Return on the Market?" *The Quarterly Journal of Economics*, 132(1), 367-433. [Link to paper](https://academic.oup.com/qje/article/132/1/367/2724543)

## 📌 Overview

The code connects directly to the **WRDS OptionMetrics** database, downloads S&P 500 index options data, cleans it according to the procedures described in the paper's Appendix A, and computes the SVIX index and the lower bound on the equity premium.

### Key Formulas Implemented

1. **SVIX² Definition (Equation 12):**
   $$SVIX^2_{t \to T} = \frac{2}{(T-t) R_{f,t} S_t^2} \left[ \int_0^{F_{t,T}} put_{t,T}(K) dK + \int_{F_{t,T}}^\infty call_{t,T}(K) dK \right]$$

2. **SVIX Index (Table IV):**
   $$SVIX = \sqrt{SVIX^2_{t \to T}} \times 100$$
   *(Annualized percentage value, comparable to the VIX index, averaging ~20.96% in the paper's sample).*

3. **Lower Bound on Equity Premium (Table I):**
   $$Lower Bound = R_{f,t} \times SVIX^2_{t \to T} \times 100$$
   *(Annualized percentage value, averaging ~5.00% in the paper's sample).*

## 🚀 Features

- **Robust WRDS Connection:** Downloads options data in monthly chunks to prevent the common `SSL SYSCALL error: EOF detected` timeout issue when querying large OptionMetrics tables.
- **Exact Methodology:** Implements all data cleaning steps from Appendix A (removing duplicates, zero-bids, quarterly options, and filtering by 7-550 days to expiry).
- **CBOE Discretization:** Uses the exact CBOE integral discretization method specified in the paper.
- **Interpolation:** Computes SVIX² for all available expiries and linearly interpolates to the target horizons (30, 60, 90, 180, and 360 days).

## 🛠️ Installation & Requirements

You must have an active **WRDS account** with access to the OptionMetrics database.

1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/svix-replication.git
   cd svix-replication
   ```

2. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```

## 💻 Usage

Run the main script from the command line, providing your WRDS username and the desired sample period:

```bash
python main.py --username your_wrds_username --start-year 1996 --end-year 2023 --output data/svix_results.csv
```

### Arguments:
- `--username`: Your WRDS username (Required)
- `--start-year`: Start year for the sample (Default: 1996)
- `--end-year`: End year for the sample (Default: 2012)
- `--output`: Path to save the resulting CSV file (Default: `data/svix_results.csv`)

## 📊 Output Format

The script generates a CSV file containing daily values for the following columns:
- `date`: Trading date
- `svix2_{T}d`: The raw SVIX² value for horizon T
- `rf_{T}d`: The gross risk-free rate factor for horizon T
- `svix_index_{T}d`: The SVIX index in annualized % (matches Table IV)
- `lower_bound_{T}d`: The lower bound on the equity premium in annualized % (matches Table I)

Where `{T}` is 30, 60, 90, 180, and 360 days.

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the issues page.
