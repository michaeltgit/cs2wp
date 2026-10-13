# ml (`cs2wp-ml`)

Trains the round model and keeps the model registry. Reads features from storage and writes models to
storage `models/` (local folder or S3), so it runs the same on a laptop or on AWS.

- LightGBM + isotonic calibration on valid regulation-time rounds, 8 snapshots per second, each round
  weighted 1; evaluated grouped by match.
- One held-out model per match, calibrated on the other matches, so every shown map is out-of-sample.
- Inputs: game state only (68 features, see `core/features.py`); never score, round number or team.
- Left out of training (still scored): the parser's sample demo, one tier-3 match, overtime rounds
  (`dataset.py`).

```bash
uv run cs2wp-ml train --activate    # train, activate, re-score every map (~5 min)
uv run cs2wp-ml models              # versions (* = active)
uv run cs2wp-ml activate <version>
uv run cs2wp-ml ablation            # held-out log loss with each feature group removed
uv run cs2wp-ml by-match            # held-out log loss per match
```

Current model: v012, 33 matches / 90 maps / 1,916 rounds, held-out log loss 0.468 (baseline 0.532),
Brier 0.157. Feature importances are in `models/<version>/metrics.json`.
