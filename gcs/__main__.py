"""Entry point: python -m gcs"""
import argparse

from gcs.app import Application


def main():
    parser = argparse.ArgumentParser(
        prog="gcs", description="Ground Control Station (headless, phase 1)"
    )
    parser.add_argument("--config", default="configs/settings.json")
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="stop after this many seconds (default: run until Ctrl+C)",
    )
    args = parser.parse_args()
    Application(args.config).run(args.duration)


if __name__ == "__main__":
    main()
