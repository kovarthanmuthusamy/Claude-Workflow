import pandas as pd

from src.preprocess import build_features, load_raw


class Trainer:
    def __init__(self, lr: float, epochs: int):
        self.lr, self.epochs = lr, epochs

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        for _ in range(self.epochs):
            self._step(X, y)

    def _step(self, X, y):
        pass

    def save(self, path):
        pass


if __name__ == "__main__":
    X, y = build_features(load_raw("data"))
    Trainer(lr=1e-3, epochs=10).fit(X, y)
