"""Run one frozen public-four E23 observation arm, only inside Kaggle."""

import argparse
from pathlib import Path

from biohub.association_parity import run_arm


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--arm", choices=("off", "on"), required=True)
    args = parser.parse_args()
    run_arm(args.plan, args.source, args.root, args.arm)


if __name__ == "__main__":
    main()
