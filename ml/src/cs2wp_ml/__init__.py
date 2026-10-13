"""cs2wp-ml: training, evaluation and the model registry."""

import argparse
import json

__version__ = "0.1.0"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cs2wp-ml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_t = sub.add_parser("train", help="train a new version (+ leave-one-match-out models)")
    p_t.add_argument("--activate", action="store_true")
    p_t.add_argument("--no-cv", action="store_true", help="skip the per-match out-of-sample models")
    p_t.add_argument("--every", type=int, default=None, help="training subsample in ticks (default 8)")
    sub.add_parser("worker", help="claim and run queued train jobs")
    sub.add_parser("models", help="list registered versions")
    p_a = sub.add_parser("activate", help="make a version the active model")
    p_a.add_argument("version")
    sub.add_parser("ablation", help="held-out log loss with each feature group removed")
    sub.add_parser("by-match", help="held-out log loss per match")
    a = ap.parse_args(argv)

    from cs2wp_core import modeling
    if a.cmd == "train":
        from cs2wp_core.config import TRAIN_EVERY

        from .train import train
        v = train(activate=a.activate, every=a.every or TRAIN_EVERY, cv_models=not a.no_cv)
        print(f"trained {v} (active: {modeling.registry()['active']})")
        print("rescore with: cs2wp-pipeline rescore  (or enqueue a rescore job)")
    elif a.cmd == "worker":
        from .worker import run_forever
        run_forever()
    elif a.cmd == "models":
        reg = modeling.registry()
        for v, info in sorted(reg["versions"].items()):
            ll = info.get("overall", {}).get("lightgbm_calibrated", {}).get("log_loss")
            print(f"{'*' if v == reg['active'] else ' '} {v}  maps={info.get('n_demos')}  log_loss={ll}")
    elif a.cmd == "activate":
        modeling.set_active(a.version)
        print(f"active: {a.version}")
    elif a.cmd == "ablation":
        from .evaluate import ablation
        print(ablation().to_string(index=False))
    elif a.cmd == "by-match":
        from .evaluate import by_match
        print(json.dumps(by_match().to_dict("records"), indent=1))
