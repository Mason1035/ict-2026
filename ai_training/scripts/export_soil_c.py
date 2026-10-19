"""Export a fitted VWC soil baseline to a new C99 header (no target SDK needed)."""

import argparse
from pathlib import Path
import sys

from ai_training.multimodal.embedded import render_soil_header
from ai_training.multimodal.forecast import RidgeForecaster


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new .h file; does not overwrite")
    args = parser.parse_args(argv)
    try:
        header = render_soil_header(RidgeForecaster.load(args.model))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(header)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"C export failed: {exc}", file=sys.stderr)
        return 2
    print(f"Exported C inference header: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
