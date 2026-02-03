"""
MLP Model Evaluation Module.

Evaluates trained MLP models on validation data (BTC/ETH):
- Classification metrics (accuracy, precision, recall, F1)
- Confusion matrix visualization
- SHAP feature importance analysis
- Per-class performance analysis

Reference: Parente & Rizzuti (2025) Section 7

Usage:
    python mlp_trainer/src/mlp_evaluate.py \
        --model models/mlp_direction/model_final.pt \
        --data data/mlp_datasets/validation_BTCUSDT_bwin5_fwin2.npz
"""

import argparse
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import torch
import matplotlib.pyplot as plt

from mlp_trainer.src.mlp_model import MLPDirectionClassifier
from trading.indicators.mlp_features import FEATURE_NAMES_PAPER, FEATURE_NAMES_SHAP

# Try to import SHAP
try:
    import shap

    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False
    logging.warning("SHAP not available. Install with: pip install shap")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports" / "mlp_evaluation"

# Label names
LABEL_NAMES = {0: "Hold", 1: "Buy", 2: "Sell"}


class MLPEvaluator:
    """
    Evaluates MLP direction classifier on validation data.

    Provides comprehensive analysis including:
    - Classification metrics
    - Confusion matrix
    - SHAP feature importance
    - Trading simulation metrics
    """

    def __init__(
        self,
        model_path: str,
        device: str = "cpu",
        feature_names: Optional[list[str]] = None,
    ):
        self.device = torch.device(device)
        self.model = MLPDirectionClassifier.load(model_path, device)
        self.model.eval()
        self.feature_names = feature_names or FEATURE_NAMES_PAPER

        logger.info(f"Loaded model from {model_path}")
        logger.info(self.model.summary())

    def predict(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        Get predictions and probabilities.

        Args:
            X: Feature array (n_samples, n_features)

        Returns:
            Tuple of (predictions, probabilities)
        """
        X_tensor = torch.FloatTensor(X).to(self.device)
        probs = self.model.predict_proba(X_tensor).cpu().numpy()
        preds = probs.argmax(axis=1)
        return preds, probs

    def evaluate_classification(
        self,
        X: np.ndarray,
        y: np.ndarray,
    ) -> dict:
        """
        Evaluate classification performance.

        Args:
            X: Feature array
            y: True labels

        Returns:
            Dict with classification metrics
        """
        preds, probs = self.predict(X)

        # Overall accuracy
        accuracy = (preds == y).mean()

        # Per-class metrics
        metrics = {
            "accuracy": accuracy,
            "n_samples": len(y),
        }

        for cls in range(3):
            cls_name = LABEL_NAMES[cls].lower()

            # True positives, false positives, false negatives
            tp = ((preds == cls) & (y == cls)).sum()
            fp = ((preds == cls) & (y != cls)).sum()
            fn = ((preds != cls) & (y == cls)).sum()
            tn = ((preds != cls) & (y != cls)).sum()

            # Precision
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0

            # Recall
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0

            # F1
            f1 = (
                2 * precision * recall / (precision + recall)
                if (precision + recall) > 0
                else 0
            )

            # Support (number of samples)
            support = (y == cls).sum()

            metrics[f"{cls_name}_precision"] = precision
            metrics[f"{cls_name}_recall"] = recall
            metrics[f"{cls_name}_f1"] = f1
            metrics[f"{cls_name}_support"] = int(support)

        return metrics

    def compute_confusion_matrix(
        self,
        X: np.ndarray,
        y: np.ndarray,
    ) -> np.ndarray:
        """
        Compute confusion matrix.

        Args:
            X: Feature array
            y: True labels

        Returns:
            Confusion matrix (3x3)
        """
        preds, _ = self.predict(X)

        cm = np.zeros((3, 3), dtype=int)
        for true_cls in range(3):
            for pred_cls in range(3):
                cm[true_cls, pred_cls] = ((y == true_cls) & (preds == pred_cls)).sum()

        return cm

    def plot_confusion_matrix(
        self,
        X: np.ndarray,
        y: np.ndarray,
        save_path: Optional[str] = None,
        normalize: bool = True,
    ) -> np.ndarray:
        """
        Plot confusion matrix.

        Args:
            X: Feature array
            y: True labels
            save_path: Path to save figure
            normalize: Whether to normalize by row

        Returns:
            Confusion matrix
        """
        cm = self.compute_confusion_matrix(X, y)

        if normalize:
            cm_display = cm.astype(float) / cm.sum(axis=1, keepdims=True)
        else:
            cm_display = cm

        fig, ax = plt.subplots(figsize=(8, 6))

        im = ax.imshow(cm_display, cmap="Blues")

        # Labels
        classes = [LABEL_NAMES[i] for i in range(3)]
        ax.set_xticks(range(3))
        ax.set_yticks(range(3))
        ax.set_xticklabels(classes)
        ax.set_yticklabels(classes)

        # Annotations
        for i in range(3):
            for j in range(3):
                if normalize:
                    text = f"{cm_display[i, j]:.2%}\n({cm[i, j]})"
                else:
                    text = str(cm[i, j])
                ax.text(j, i, text, ha="center", va="center")

        ax.set_xlabel("Predicted")
        ax.set_ylabel("True")
        ax.set_title("Confusion Matrix")

        plt.colorbar(im)
        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150)
            logger.info(f"Saved confusion matrix to {save_path}")

        plt.close()

        return cm

    def compute_shap_importance(
        self,
        X: np.ndarray,
        n_samples: int = 1000,
        save_path: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Compute SHAP feature importance.

        Based on the paper's methodology (Section 7).

        Args:
            X: Feature array
            n_samples: Number of samples for SHAP computation
            save_path: Path to save SHAP summary plot

        Returns:
            DataFrame with feature importance values
        """
        if not SHAP_AVAILABLE:
            logger.warning("SHAP not available")
            return None

        logger.info(f"Computing SHAP values for {n_samples} samples...")

        # Sample data if needed
        if len(X) > n_samples:
            indices = np.random.choice(len(X), n_samples, replace=False)
            X_sample = X[indices]
        else:
            X_sample = X

        # Create SHAP explainer
        # Using DeepExplainer for neural networks
        X_tensor = torch.FloatTensor(X_sample).to(self.device)

        # Use KernelExplainer as fallback (more compatible)
        def model_predict(x):
            x_tensor = torch.FloatTensor(x).to(self.device)
            with torch.no_grad():
                probs = self.model.predict_proba(x_tensor)
            return probs.cpu().numpy()

        # Background data
        background = X_sample[:100]

        explainer = shap.KernelExplainer(model_predict, background)
        shap_values = explainer.shap_values(X_sample[:500])  # Limit for speed

        # Average absolute SHAP values across all classes
        if isinstance(shap_values, list):
            # Multi-class: average across classes
            shap_importance = np.mean(
                [np.abs(sv).mean(axis=0) for sv in shap_values], axis=0
            )
        else:
            shap_importance = np.abs(shap_values).mean(axis=0)

        # Create DataFrame
        importance_df = pd.DataFrame(
            {
                "feature": self.feature_names,
                "importance": shap_importance,
            }
        )
        importance_df = importance_df.sort_values("importance", ascending=False)
        importance_df["rank"] = range(1, len(importance_df) + 1)

        # Plot
        if save_path:
            fig, ax = plt.subplots(figsize=(10, 8))

            # Bar plot
            y_pos = range(len(importance_df))
            ax.barh(y_pos, importance_df["importance"].values)
            ax.set_yticks(y_pos)
            ax.set_yticklabels(importance_df["feature"].values)
            ax.invert_yaxis()
            ax.set_xlabel("Mean |SHAP Value|")
            ax.set_title("Feature Importance (SHAP)")

            plt.tight_layout()
            plt.savefig(save_path, dpi=150)
            logger.info(f"Saved SHAP importance to {save_path}")
            plt.close()

        return importance_df

    def evaluate_trading_simulation(
        self,
        X: np.ndarray,
        y: np.ndarray,
        returns: np.ndarray,
        confidence_threshold: float = 0.6,
    ) -> dict:
        """
        Simulate trading based on model predictions.

        Args:
            X: Feature array
            y: True labels
            returns: Actual returns for each sample
            confidence_threshold: Minimum Buy probability to enter

        Returns:
            Dict with trading metrics
        """
        preds, probs = self.predict(X)

        # Only trade when model predicts Buy with high confidence
        buy_mask = (preds == 1) & (probs[:, 1] >= confidence_threshold)

        trades = buy_mask.sum()
        if trades == 0:
            return {
                "num_trades": 0,
                "total_return": 0,
                "win_rate": 0,
                "avg_return": 0,
            }

        # Calculate returns for trades taken
        trade_returns = returns[buy_mask]
        wins = (trade_returns > 0).sum()
        win_rate = wins / trades

        # Compound return
        total_return = np.prod(1 + trade_returns) - 1

        # Average return
        avg_return = trade_returns.mean()

        return {
            "num_trades": int(trades),
            "total_return": float(total_return),
            "win_rate": float(win_rate),
            "avg_return": float(avg_return),
            "max_return": float(trade_returns.max()) if trades > 0 else 0,
            "min_return": float(trade_returns.min()) if trades > 0 else 0,
        }

    def generate_report(
        self,
        X: np.ndarray,
        y: np.ndarray,
        symbol: str,
        output_dir: Path,
        returns: Optional[np.ndarray] = None,
    ) -> dict:
        """
        Generate comprehensive evaluation report.

        Args:
            X: Feature array
            y: True labels
            symbol: Symbol name (e.g., 'BTCUSDT')
            output_dir: Output directory
            returns: Optional returns for trading simulation

        Returns:
            Dict with all metrics
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"\n{'='*60}")
        logger.info(f"Evaluation Report: {symbol}")
        logger.info(f"{'='*60}")

        # Classification metrics
        metrics = self.evaluate_classification(X, y)

        logger.info(f"\nClassification Metrics:")
        logger.info(f"  Accuracy: {metrics['accuracy']:.4f}")
        logger.info(f"  Samples: {metrics['n_samples']:,}")

        for cls_name in ["hold", "buy", "sell"]:
            logger.info(f"\n  {cls_name.upper()}:")
            logger.info(f"    Precision: {metrics[f'{cls_name}_precision']:.4f}")
            logger.info(f"    Recall: {metrics[f'{cls_name}_recall']:.4f}")
            logger.info(f"    F1: {metrics[f'{cls_name}_f1']:.4f}")
            logger.info(f"    Support: {metrics[f'{cls_name}_support']}")

        # Confusion matrix
        cm_path = output_dir / f"confusion_matrix_{symbol}.png"
        self.plot_confusion_matrix(X, y, save_path=str(cm_path))
        metrics["confusion_matrix_path"] = str(cm_path)

        # SHAP importance
        if SHAP_AVAILABLE:
            shap_path = output_dir / f"shap_importance_{symbol}.png"
            importance_df = self.compute_shap_importance(
                X, save_path=str(shap_path)
            )

            if importance_df is not None:
                logger.info(f"\nTop 5 Important Features:")
                for _, row in importance_df.head().iterrows():
                    logger.info(f"  {row['rank']}. {row['feature']}: {row['importance']:.4f}")

                # Save to CSV
                csv_path = output_dir / f"feature_importance_{symbol}.csv"
                importance_df.to_csv(csv_path, index=False)
                metrics["feature_importance_path"] = str(csv_path)

        # Trading simulation (if returns provided)
        if returns is not None:
            logger.info(f"\nTrading Simulation:")
            for threshold in [0.5, 0.6, 0.7]:
                sim_metrics = self.evaluate_trading_simulation(
                    X, y, returns, confidence_threshold=threshold
                )
                logger.info(f"  Threshold {threshold}:")
                logger.info(f"    Trades: {sim_metrics['num_trades']}")
                logger.info(f"    Win Rate: {sim_metrics['win_rate']:.2%}")
                logger.info(f"    Total Return: {sim_metrics['total_return']:.2%}")

                metrics[f"sim_{threshold}"] = sim_metrics

        # Save metrics to JSON
        import json

        metrics_path = output_dir / f"metrics_{symbol}.json"
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2, default=str)

        logger.info(f"\nReport saved to {output_dir}")

        return metrics


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Evaluate MLP Direction Classifier")
    parser.add_argument(
        "--model",
        type=str,
        required=True,
        help="Path to model checkpoint",
    )
    parser.add_argument(
        "--data",
        type=str,
        required=True,
        help="Path to validation data npz file",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for report",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Symbol name (auto-detected from filename if not provided)",
    )

    args = parser.parse_args()

    # Auto-detect symbol from filename
    if args.symbol is None:
        filename = Path(args.data).stem
        if "BTCUSDT" in filename:
            symbol = "BTCUSDT"
        elif "ETHUSDT" in filename:
            symbol = "ETHUSDT"
        else:
            symbol = "UNKNOWN"
    else:
        symbol = args.symbol

    # Load data
    data = np.load(args.data)
    X = data["X"]
    y = data["y"]
    if "feature_names" in data:
        feature_names = list(data["feature_names"])
    else:
        feature_names = FEATURE_NAMES_PAPER

    # Create evaluator and generate report
    evaluator = MLPEvaluator(args.model, feature_names=feature_names)
    evaluator.generate_report(
        X,
        y,
        symbol=symbol,
        output_dir=Path(args.output),
    )


if __name__ == "__main__":
    main()
