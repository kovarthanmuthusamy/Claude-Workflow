from pathlib import Path

import numpy as np

from src.prepare import load_listings, make_features, split_listings


def report(model_path: Path, X: np.ndarray, y: np.ndarray) -> dict:
    m = np.load(model_path)
    err = X @ m["w"] + m["b"] - y
    return {"rmse_k": round(float(np.sqrt(np.mean(err ** 2))), 1),
            "mae_k": round(float(np.mean(np.abs(err))), 1)}


if __name__ == "__main__":
    m = np.load("models/model.npz")
    _, test_df = split_listings(load_listings(Path("data/listings.csv")))
    X, y, _ = make_features(test_df, (m["mean"], m["std"]))
    print(f"test listings: {len(y)}", report(Path("models/model.npz"), X, y))
