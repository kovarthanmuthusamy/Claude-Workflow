from pathlib import Path

import numpy as np
import pandas as pd

FEATURES = ["size_m2", "rooms", "distance_km", "age_years"]


def load_listings(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def split_listings(df: pd.DataFrame, test_share: float = 0.25, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    order = np.random.default_rng(seed).permutation(len(df))
    n_test = round(len(df) * test_share)
    return df.iloc[order[n_test:]], df.iloc[order[:n_test]]


def make_features(df: pd.DataFrame, scaling=None) -> tuple[np.ndarray, np.ndarray, tuple]:
    raw = df[FEATURES].to_numpy(dtype=float)
    if scaling is None:
        scaling = (raw.mean(axis=0), raw.std(axis=0))
    X = (raw - scaling[0]) / scaling[1]
    return X, df["price_k"].to_numpy(dtype=float), scaling
