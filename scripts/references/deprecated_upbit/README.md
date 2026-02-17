# Deprecated Upbit Reference Scripts

This directory contains legacy Upbit/KRW tooling kept only for historical reference.

Status:
- Deprecated (not part of active spot/Binance pipeline)
- Not used by current paper/live execution or backtest workflows

Moved from:
- `scripts/collect_altcoin_data.py`
- `scripts/interpolate_gaps.py`
- `scripts/verify_data.py`
- `scripts/collectors/cli.py`
- `scripts/collectors/verify_data.py`
- `scripts/collectors/bin/*` (Go upbit collector + binary)

Active alternatives:
- Spot data collection: `scripts/auto_collect_data.py`
- Spot full recollection: `scripts/collectors/recollect_spot_all_assets.py`
- Spot parity validation: `scripts/validate_binance_indicator_parity.py`
