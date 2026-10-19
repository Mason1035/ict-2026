"""Train lightweight real-public-data branches; never fabricate project labels."""

import argparse
import json
from pathlib import Path
import sys

from ai_training.multimodal.pipeline import run_training


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True, help="directory containing lisa/ and smartstone/")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="new directory; existing runs never overwritten")
    parser.add_argument("--evaluate-test", action="store_true", help="release grouped soil holdout once for this completed run")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        summary = run_training(args.data_root, args.output_dir, config, evaluate_test=args.evaluate_test)
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": summary["status"], "output_dir": str(args.output_dir),
                      "soil_evaluation": summary["models"]["soil"]["evaluation_scope"],
                      "motion_evaluation": summary["models"]["motion"]["evaluation_scope"],
                      "fusion": summary["fusion"]["status"], "deployment_ready": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
