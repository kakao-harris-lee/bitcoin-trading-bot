"""
MLP Direction Classifier Training Script.

Complete training pipeline with:
- Data loading from npz files
- Training loop with validation
- Early stopping
- Learning rate scheduling
- MLflow experiment tracking
- Model checkpointing

Reference: Parente & Rizzuti (2025)

Usage:
    python mlp_trainer/src/mlp_train.py --dataset data/mlp_datasets/mlp_dataset_bwin5_fwin2.npz
"""

import argparse
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from mlp_trainer.src.mlp_model import MLPDirectionClassifier, MLPConfig

# Try to import MLflow
try:
    import mlflow
    import mlflow.pytorch

    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models" / "mlp_direction"


@dataclass
class TrainingConfig:
    """Training configuration."""

    # Model architecture
    input_dim: int = 36
    hidden_dims: tuple = (128, 64, 32)
    num_classes: int = 3
    dropout: float = 0.0
    use_batch_norm: bool = False
    leaky_relu_slope: float = 0.01

    # Training parameters
    epochs: int = 100
    batch_size: int = 256
    learning_rate: float = 1e-3
    weight_decay: float = 1e-5

    # Early stopping
    patience: int = 10
    min_delta: float = 1e-4

    # Learning rate scheduling
    lr_scheduler: str = "plateau"  # 'plateau' or 'cosine'
    lr_patience: int = 5
    lr_factor: float = 0.5

    # Device
    device: str = field(
        default_factory=lambda: "cuda" if torch.cuda.is_available() else "cpu"
    )

    # Paths
    output_dir: Path = DEFAULT_MODEL_DIR
    experiment_name: str = "mlp_direction"


class MLPTrainer:
    """
    MLP Direction Classifier Trainer.

    Handles the complete training pipeline including:
    - Model initialization
    - Training loop with validation
    - Early stopping
    - MLflow logging
    - Model checkpointing
    """

    def __init__(self, config: TrainingConfig):
        self.config = config
        self.device = torch.device(config.device)

        # Create model
        self.model = MLPDirectionClassifier(
            input_dim=config.input_dim,
            hidden_dims=config.hidden_dims,
            num_classes=config.num_classes,
            dropout=config.dropout,
            use_batch_norm=config.use_batch_norm,
            leaky_relu_slope=config.leaky_relu_slope,
        ).to(self.device)

        # Loss function with class weights (optional)
        self.criterion = nn.CrossEntropyLoss()

        # Optimizer
        self.optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=config.learning_rate,
            weight_decay=config.weight_decay,
        )

        # Learning rate scheduler
        if config.lr_scheduler == "plateau":
            self.scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
                self.optimizer,
                mode="min",
                patience=config.lr_patience,
                factor=config.lr_factor,
            )
        else:
            self.scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
                self.optimizer,
                T_max=config.epochs,
            )

        # Early stopping state
        self.best_val_loss = float("inf")
        self.best_val_acc = 0.0
        self.patience_counter = 0
        self.best_state_dict = None

        # Output directory
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Model initialized on {self.device}")
        logger.info(f"Parameters: {self.model.count_parameters():,}")

    def train_epoch(self, dataloader: DataLoader) -> tuple[float, float]:
        """Train for one epoch."""
        self.model.train()
        total_loss = 0.0
        correct = 0
        total = 0

        for X_batch, y_batch in dataloader:
            X_batch = X_batch.to(self.device)
            y_batch = y_batch.to(self.device)

            self.optimizer.zero_grad()

            outputs = self.model(X_batch)
            loss = self.criterion(outputs, y_batch)

            loss.backward()
            self.optimizer.step()

            total_loss += loss.item() * len(y_batch)
            _, predicted = outputs.max(1)
            correct += predicted.eq(y_batch).sum().item()
            total += len(y_batch)

        avg_loss = total_loss / total
        accuracy = correct / total

        return avg_loss, accuracy

    def validate(self, dataloader: DataLoader) -> tuple[float, float, dict]:
        """Validate model."""
        self.model.eval()
        total_loss = 0.0
        correct = 0
        total = 0

        # Per-class metrics
        class_correct = {0: 0, 1: 0, 2: 0}
        class_total = {0: 0, 1: 0, 2: 0}

        with torch.no_grad():
            for X_batch, y_batch in dataloader:
                X_batch = X_batch.to(self.device)
                y_batch = y_batch.to(self.device)

                outputs = self.model(X_batch)
                loss = self.criterion(outputs, y_batch)

                total_loss += loss.item() * len(y_batch)
                _, predicted = outputs.max(1)
                correct += predicted.eq(y_batch).sum().item()
                total += len(y_batch)

                # Per-class accuracy
                for cls in range(3):
                    mask = y_batch == cls
                    class_total[cls] += mask.sum().item()
                    class_correct[cls] += (predicted[mask] == cls).sum().item()

        avg_loss = total_loss / total
        accuracy = correct / total

        # Calculate per-class accuracies
        class_acc = {}
        for cls in range(3):
            if class_total[cls] > 0:
                class_acc[cls] = class_correct[cls] / class_total[cls]
            else:
                class_acc[cls] = 0.0

        metrics = {
            "hold_acc": class_acc[0],
            "buy_acc": class_acc[1],
            "sell_acc": class_acc[2],
        }

        return avg_loss, accuracy, metrics

    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        run_name: Optional[str] = None,
    ) -> dict:
        """
        Train the model.

        Args:
            X_train: Training features
            y_train: Training labels
            X_val: Validation features
            y_val: Validation labels
            run_name: Optional name for MLflow run

        Returns:
            Dict with training history and best metrics
        """
        # Create data loaders
        train_dataset = TensorDataset(
            torch.FloatTensor(X_train),
            torch.LongTensor(y_train),
        )
        val_dataset = TensorDataset(
            torch.FloatTensor(X_val),
            torch.LongTensor(y_val),
        )

        train_loader = DataLoader(
            train_dataset,
            batch_size=self.config.batch_size,
            shuffle=True,
            num_workers=0,
            pin_memory=True if self.device.type == "cuda" else False,
        )
        val_loader = DataLoader(
            val_dataset,
            batch_size=self.config.batch_size,
            shuffle=False,
            num_workers=0,
        )

        logger.info(f"Training samples: {len(train_dataset):,}")
        logger.info(f"Validation samples: {len(val_dataset):,}")

        # Setup MLflow
        if MLFLOW_AVAILABLE:
            mlflow.set_experiment(self.config.experiment_name)
            mlflow.start_run(run_name=run_name)

            # Log parameters
            mlflow.log_params(
                {
                    "hidden_dims": str(self.config.hidden_dims),
                    "dropout": self.config.dropout,
                    "batch_size": self.config.batch_size,
                    "learning_rate": self.config.learning_rate,
                    "weight_decay": self.config.weight_decay,
                    "epochs": self.config.epochs,
                    "patience": self.config.patience,
                }
            )

        # Training history
        history = {
            "train_loss": [],
            "train_acc": [],
            "val_loss": [],
            "val_acc": [],
        }

        start_time = time.time()

        for epoch in range(self.config.epochs):
            # Train
            train_loss, train_acc = self.train_epoch(train_loader)

            # Validate
            val_loss, val_acc, class_metrics = self.validate(val_loader)

            # Update learning rate
            if self.config.lr_scheduler == "plateau":
                self.scheduler.step(val_loss)
            else:
                self.scheduler.step()

            # Record history
            history["train_loss"].append(train_loss)
            history["train_acc"].append(train_acc)
            history["val_loss"].append(val_loss)
            history["val_acc"].append(val_acc)

            # Log to MLflow
            if MLFLOW_AVAILABLE:
                mlflow.log_metrics(
                    {
                        "train_loss": train_loss,
                        "train_acc": train_acc,
                        "val_loss": val_loss,
                        "val_acc": val_acc,
                        **class_metrics,
                    },
                    step=epoch,
                )

            # Logging
            current_lr = self.optimizer.param_groups[0]["lr"]
            logger.info(
                f"Epoch {epoch+1:3d}/{self.config.epochs} | "
                f"Train Loss: {train_loss:.4f} Acc: {train_acc:.4f} | "
                f"Val Loss: {val_loss:.4f} Acc: {val_acc:.4f} | "
                f"LR: {current_lr:.2e}"
            )

            # Early stopping check
            if val_loss < self.best_val_loss - self.config.min_delta:
                self.best_val_loss = val_loss
                self.best_val_acc = val_acc
                self.best_state_dict = self.model.state_dict().copy()
                self.patience_counter = 0

                # Save best model
                self._save_checkpoint(epoch, val_loss, val_acc, is_best=True)
            else:
                self.patience_counter += 1
                if self.patience_counter >= self.config.patience:
                    logger.info(f"Early stopping at epoch {epoch+1}")
                    break

        elapsed = time.time() - start_time

        # Restore best model
        if self.best_state_dict is not None:
            self.model.load_state_dict(self.best_state_dict)

        # Final save
        final_path = self._save_checkpoint(
            epoch, self.best_val_loss, self.best_val_acc, is_best=False, final=True
        )

        # Log final metrics to MLflow
        if MLFLOW_AVAILABLE:
            mlflow.log_metrics(
                {
                    "best_val_loss": self.best_val_loss,
                    "best_val_acc": self.best_val_acc,
                    "training_time": elapsed,
                }
            )
            mlflow.log_artifact(str(final_path))
            mlflow.end_run()

        logger.info(f"\nTraining complete in {elapsed:.1f}s")
        logger.info(f"Best validation loss: {self.best_val_loss:.4f}")
        logger.info(f"Best validation accuracy: {self.best_val_acc:.4f}")
        logger.info(f"Model saved to: {final_path}")

        return {
            "history": history,
            "best_val_loss": self.best_val_loss,
            "best_val_acc": self.best_val_acc,
            "model_path": str(final_path),
            "training_time": elapsed,
        }

    def _save_checkpoint(
        self,
        epoch: int,
        val_loss: float,
        val_acc: float,
        is_best: bool = False,
        final: bool = False,
    ) -> Path:
        """Save model checkpoint."""
        if final:
            filename = "model_final.pt"
        elif is_best:
            filename = "model_best.pt"
        else:
            filename = f"model_epoch{epoch+1}.pt"

        path = self.output_dir / filename
        self.model.save(str(path))

        return path

    def evaluate(
        self,
        X_test: np.ndarray,
        y_test: np.ndarray,
    ) -> dict:
        """
        Evaluate model on test set.

        Args:
            X_test: Test features
            y_test: Test labels

        Returns:
            Dict with evaluation metrics
        """
        test_dataset = TensorDataset(
            torch.FloatTensor(X_test),
            torch.LongTensor(y_test),
        )
        test_loader = DataLoader(
            test_dataset,
            batch_size=self.config.batch_size,
            shuffle=False,
        )

        test_loss, test_acc, class_metrics = self.validate(test_loader)

        # Compute confusion matrix
        self.model.eval()
        all_preds = []
        all_labels = []

        with torch.no_grad():
            for X_batch, y_batch in test_loader:
                X_batch = X_batch.to(self.device)
                outputs = self.model(X_batch)
                _, preds = outputs.max(1)
                all_preds.extend(preds.cpu().numpy())
                all_labels.extend(y_batch.numpy())

        all_preds = np.array(all_preds)
        all_labels = np.array(all_labels)

        # Per-class precision and recall
        metrics = {
            "test_loss": test_loss,
            "test_acc": test_acc,
            **class_metrics,
        }

        for cls in range(3):
            # Precision
            pred_mask = all_preds == cls
            if pred_mask.sum() > 0:
                metrics[f"precision_{cls}"] = (
                    (all_labels[pred_mask] == cls).sum() / pred_mask.sum()
                )
            else:
                metrics[f"precision_{cls}"] = 0.0

            # Recall
            label_mask = all_labels == cls
            if label_mask.sum() > 0:
                metrics[f"recall_{cls}"] = (
                    (all_preds[label_mask] == cls).sum() / label_mask.sum()
                )
            else:
                metrics[f"recall_{cls}"] = 0.0

        logger.info(f"\nTest Results:")
        logger.info(f"  Loss: {test_loss:.4f}")
        logger.info(f"  Accuracy: {test_acc:.4f}")
        logger.info(f"  Hold Acc: {class_metrics['hold_acc']:.4f}")
        logger.info(f"  Buy Acc: {class_metrics['buy_acc']:.4f}")
        logger.info(f"  Sell Acc: {class_metrics['sell_acc']:.4f}")

        return metrics


def load_dataset(path: str) -> dict:
    """Load dataset from npz file."""
    data = np.load(path)
    return {
        "X_train": data["X_train"],
        "X_val": data["X_val"],
        "X_test": data["X_test"],
        "y_train": data["y_train"],
        "y_val": data["y_val"],
        "y_test": data["y_test"],
        "feature_names": list(data["feature_names"]) if "feature_names" in data else None,
        "feature_set": str(data["feature_set"]) if "feature_set" in data else None,
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Train MLP Direction Classifier")
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        help="Path to dataset npz file",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_MODEL_DIR),
        help="Output directory for model",
    )
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--dropout", type=float, default=0.0)
    parser.add_argument("--use-batch-norm", action="store_true")
    parser.add_argument("--leaky-relu-slope", type=float, default=0.01)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument(
        "--hidden-dims",
        type=str,
        default="128,64,32",
        help="Hidden layer dimensions (comma-separated)",
    )
    parser.add_argument(
        "--run-name",
        type=str,
        default=None,
        help="MLflow run name",
    )
    parser.add_argument(
        "--no-mlflow",
        action="store_true",
        help="Disable MLflow logging",
    )

    args = parser.parse_args()

    # Parse hidden dims
    hidden_dims = tuple(int(x) for x in args.hidden_dims.split(","))

    # Create config
    # Load dataset
    logger.info(f"Loading dataset from {args.dataset}")
    data = load_dataset(args.dataset)

    input_dim = int(data["X_train"].shape[1])

    config = TrainingConfig(
        input_dim=input_dim,
        hidden_dims=hidden_dims,
        dropout=args.dropout,
        use_batch_norm=args.use_batch_norm,
        leaky_relu_slope=args.leaky_relu_slope,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        patience=args.patience,
        output_dir=Path(args.output),
    )

    # Disable MLflow if requested
    global MLFLOW_AVAILABLE
    if args.no_mlflow:
        MLFLOW_AVAILABLE = False

    logger.info(f"Train: {len(data['X_train']):,} samples")
    logger.info(f"Val: {len(data['X_val']):,} samples")
    logger.info(f"Test: {len(data['X_test']):,} samples")

    # Create trainer and train
    trainer = MLPTrainer(config)

    X_val = data["X_val"]
    y_val = data["y_val"]
    if len(X_val) == 0:
        logger.warning("Validation set is empty; using test set for validation.")
        X_val = data["X_test"]
        y_val = data["y_test"]

    results = trainer.train(
        data["X_train"],
        data["y_train"],
        X_val,
        y_val,
        run_name=args.run_name,
    )

    # Evaluate on test set
    test_metrics = trainer.evaluate(data["X_test"], data["y_test"])

    print(f"\nModel saved to: {results['model_path']}")
    print(f"Best validation accuracy: {results['best_val_acc']:.4f}")
    print(f"Test accuracy: {test_metrics['test_acc']:.4f}")


if __name__ == "__main__":
    main()
