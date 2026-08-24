# Usage

From the project root:

```bash
source .venv/bin/activate
python forecast.py --market all
```

Or:

```bash
python forecast.py --market london
python forecast.py --market shanghai
```

Outputs are written to `results/latest_forecast/`.

The workflow combines:
- Logistic Regression for P(up)
- Ridge Regression for expected return
- purged walk-forward validation
- a 60-day historical analogue matcher
- probability, analogue-path, history and feature-contribution charts
