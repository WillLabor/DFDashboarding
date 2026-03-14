"""A lightweight ML experiment runner.

This module is meant as a starting point for iterating on models and evaluation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split


def run_classification(
    input_csv: str,
    target_column: str,
    features: list[str] | None = None,
    test_size: float = 0.2,
    random_state: int = 42,
) -> None:
    """Load data, train a simple model, and print metrics."""

    df = pd.read_csv(input_csv)

    if features is None:
        features = [c for c in df.columns if c != target_column]

    X = df[features]
    y = df[target_column]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y if len(set(y)) > 1 else None
    )

    model = RandomForestClassifier(random_state=random_state, n_jobs=-1)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    print("=== classification report ===")
    print(classification_report(y_test, y_pred))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run a quick ML experiment")
    parser.add_argument("--input-csv", required=True, help="Path to input CSV")
    parser.add_argument("--target", required=True, help="Target column name")
    parser.add_argument(
        "--features",
        nargs="*",
        default=None,
        help="Optional list of feature columns to use (default: all except target)",
    )
    parser.add_argument("--test-size", type=float, default=0.2, help="Test split size")
    parser.add_argument("--random-state", type=int, default=42, help="Random seed")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    run_classification(
        input_csv=args.input_csv,
        target_column=args.target,
        features=args.features,
        test_size=args.test_size,
        random_state=args.random_state,
    )


if __name__ == "__main__":
    main()
