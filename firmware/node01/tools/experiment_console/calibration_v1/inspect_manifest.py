"""Validate an explicitly selected, reviewed manifest using local files only."""
import argparse
import json

from .manifest_schema_adapter import verify_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_manifest(args.manifest)
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
