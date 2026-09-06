# src/rhosocial/activerecord/backend/impl/bigquery/__main__.py
"""BigQuery backend command-line interface."""

import argparse


def main():
    """Main CLI entry point for the BigQuery backend."""
    parser = argparse.ArgumentParser(
        description="BigQuery backend for rhosocial-activerecord.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.parse_args()
    print("BigQuery backend for rhosocial-activerecord")


if __name__ == "__main__":
    main()
