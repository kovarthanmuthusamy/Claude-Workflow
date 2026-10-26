from pathlib import Path

import pandas as pd


def _parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    return df


def load_raw(path: Path) -> pd.DataFrame:
    return _parse_dates(pd.concat(pd.read_csv(p) for p in path.glob("*.csv")))


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    return df.drop(columns="churn"), df["churn"]
