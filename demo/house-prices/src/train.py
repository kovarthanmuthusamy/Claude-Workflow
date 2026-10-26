from pathlib import Path

import numpy as np
import pandas as pd

from src.prepare import load_listings, make_features, split_listings

PENALTIES = np.concatenate([[0.0], np.logspace(-2, 3, 12)])


def fit_linear(X: np.ndarray, y: np.ndarray, penalty: float = 0.0) -> tuple[np.ndarray, float]:
    # Centre first so the base price is left out of the penalty.
    x_mean, y_mean = X.mean(axis=0), y.mean()
    Xc = X - x_mean
    w = np.linalg.solve(Xc.T @ Xc + penalty * np.eye(X.shape[1]), Xc.T @ (y - y_mean))
    return w, float(y_mean - x_mean @ w)


def choose_penalty(train_df: pd.DataFrame, n_folds: int = 5, seed: int = 0) -> tuple[float, np.ndarray]:
    folds = np.array_split(np.random.default_rng(seed).permutation(len(train_df)), n_folds)
    cv_rmse = np.zeros(len(PENALTIES))
    for k in range(n_folds):
        fit_rows = np.concatenate([f for j, f in enumerate(folds) if j != k])
        X_fit, y_fit, scaling = make_features(train_df.iloc[fit_rows])
        X_val, y_val, _ = make_features(train_df.iloc[folds[k]], scaling)
        for i, lam in enumerate(PENALTIES):
            w, b = fit_linear(X_fit, y_fit, lam)
            cv_rmse[i] += np.sqrt(np.mean((X_val @ w + b - y_val) ** 2)) / n_folds
    return float(PENALTIES[np.argmin(cv_rmse)]), cv_rmse


if __name__ == "__main__":
    train_df, _ = split_listings(load_listings(Path("data/listings.csv")))
    penalty, cv_rmse = choose_penalty(train_df)
    for lam, err in zip(PENALTIES, cv_rmse):
        print(f"penalty {lam:9.3f}  held-out RMSE {err:6.2f}")
    X, y, scaling = make_features(train_df)
    w, b = fit_linear(X, y, penalty)
    Path("models").mkdir(exist_ok=True)
    np.savez("models/model.npz", w=w, b=b, mean=scaling[0], std=scaling[1], penalty=penalty)
    print("chosen penalty:", round(penalty, 3))
    print("weights per feature:", np.round(w, 2), "intercept:", round(b, 1))
