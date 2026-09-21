"""Run one literal collection36 group, only inside Kaggle."""

import argparse
from pathlib import Path

from biohub.association_collection import run_group


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    run_group(args.plan, args.root)


if __name__ == "__main__":
    main()
