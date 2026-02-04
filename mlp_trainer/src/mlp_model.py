"""
MLP Direction Classifier Model.

Architecture based on Parente & Rizzuti (2025):
- Default input: 13 features (shap_13 feature set)
- Paper input: 36 features (paper_36 feature set)
- Hidden layers: 128 → 64 → 32
- Activation: LeakyReLU
- Output: 3 classes (Hold, Buy, Sell) with softmax

Reference: https://doi.org/10.1007/s00500-025-10980-7
"""

import torch
import torch.nn as nn
import numpy as np
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from mlp_trainer.src.constants import (
    DEFAULT_INPUT_DIM,
    DEFAULT_HIDDEN_DIMS,
    DEFAULT_NUM_CLASSES,
)


@dataclass
class MLPConfig:
    """Configuration for MLP model."""

    input_dim: int = DEFAULT_INPUT_DIM
    hidden_dims: tuple = DEFAULT_HIDDEN_DIMS
    num_classes: int = DEFAULT_NUM_CLASSES
    dropout: float = 0.0
    leaky_relu_slope: float = 0.01
    use_batch_norm: bool = False


class MLPDirectionClassifier(nn.Module):
    """
    Multi-Layer Perceptron for price direction classification.

    Predicts Buy/Hold/Sell based on technical indicators.

    Architecture:
        Input(13) → Linear(128) → LeakyReLU
                  → Linear(64)  → LeakyReLU
                  → Linear(32)  → LeakyReLU
                  → Linear(3)   → Softmax (during inference)
    """

    def __init__(
        self,
        input_dim: int = DEFAULT_INPUT_DIM,
        hidden_dims: tuple = DEFAULT_HIDDEN_DIMS,
        num_classes: int = DEFAULT_NUM_CLASSES,
        dropout: float = 0.0,
        leaky_relu_slope: float = 0.01,
        use_batch_norm: bool = False,
    ):
        super().__init__()

        self.input_dim = input_dim
        self.hidden_dims = hidden_dims
        self.num_classes = num_classes
        self.dropout_rate = dropout

        layers = []
        prev_dim = input_dim

        for hidden_dim in hidden_dims:
            # Linear layer
            layers.append(nn.Linear(prev_dim, hidden_dim))

            # Activation
            layers.append(nn.LeakyReLU(negative_slope=leaky_relu_slope))

            # Batch normalization (optional but recommended)
            if use_batch_norm:
                layers.append(nn.BatchNorm1d(hidden_dim))

            # Dropout for regularization
            layers.append(nn.Dropout(dropout))

            prev_dim = hidden_dim

        # Output layer (no activation - CrossEntropyLoss handles softmax internally)
        layers.append(nn.Linear(prev_dim, num_classes))

        self.network = nn.Sequential(*layers)

        # Initialize weights
        self._init_weights()

    def _init_weights(self):
        """Initialize weights using Kaiming initialization."""
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.kaiming_normal_(
                    module.weight, mode="fan_in", nonlinearity="leaky_relu"
                )
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass.

        Args:
            x: Input tensor of shape (batch_size, input_dim)

        Returns:
            Logits tensor of shape (batch_size, num_classes)
        """
        # Handle single sample case for BatchNorm
        # BatchNorm1d requires batch_size > 1 during training
        if x.size(0) == 1 and self.training:
            # Temporarily switch to eval mode for single sample
            was_training = True
            self.eval()
        else:
            was_training = False

        result = self.network(x)

        if was_training:
            self.train()

        return result

    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        """
        Get probability predictions.

        Args:
            x: Input tensor of shape (batch_size, input_dim)

        Returns:
            Probability tensor of shape (batch_size, num_classes)
            Order: [Hold, Buy, Sell]
        """
        self.eval()
        with torch.no_grad():
            logits = self.forward(x)
            return torch.softmax(logits, dim=-1)

    def predict(self, x: torch.Tensor) -> torch.Tensor:
        """
        Get class predictions.

        Args:
            x: Input tensor of shape (batch_size, input_dim)

        Returns:
            Class indices tensor of shape (batch_size,)
            0=Hold, 1=Buy, 2=Sell
        """
        probs = self.predict_proba(x)
        return probs.argmax(dim=-1)

    def predict_numpy(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        Predict from numpy array.

        Args:
            x: Input array of shape (batch_size, input_dim) or (input_dim,)

        Returns:
            Tuple of (predictions, probabilities)
        """
        # Handle single sample
        if x.ndim == 1:
            x = x.reshape(1, -1)

        x_tensor = torch.FloatTensor(x)

        probs = self.predict_proba(x_tensor).numpy()
        preds = probs.argmax(axis=-1)

        return preds, probs

    def save(self, path: str):
        """
        Save model checkpoint.

        Args:
            path: File path to save to
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        checkpoint = {
            "state_dict": self.state_dict(),
            "config": {
                "input_dim": self.input_dim,
                "hidden_dims": self.hidden_dims,
                "num_classes": self.num_classes,
                "dropout": self.dropout_rate,
                "use_batch_norm": any(
                    isinstance(layer, nn.BatchNorm1d) for layer in self.network
                ),
                "leaky_relu_slope": self.network[1].negative_slope
                if len(self.network) > 1 and isinstance(self.network[1], nn.LeakyReLU)
                else 0.01,
            },
        }
        torch.save(checkpoint, path)

    @classmethod
    def load(
        cls,
        path: str,
        device: str = "cpu",
        validate_path: bool = True,
    ) -> "MLPDirectionClassifier":
        """
        Load model from checkpoint.

        Args:
            path: File path to load from
            device: Device to load to ('cpu' or 'cuda')
            validate_path: If True, validate path is within allowed directories

        Returns:
            Loaded model instance

        Security Note:
            torch.load with weights_only=False can execute arbitrary code.
            Only load models from trusted sources. The validate_path option
            helps prevent path traversal attacks.
        """
        from pathlib import Path

        model_path = Path(path).resolve()

        if validate_path:
            # Get project root (3 levels up from this file)
            project_root = Path(__file__).parent.parent.parent.resolve()
            allowed_dirs = [
                project_root / "models",
                project_root / "mlp_trainer" / "models",
            ]

            is_allowed = any(
                str(model_path).startswith(str(allowed_dir))
                for allowed_dir in allowed_dirs
            )

            if not is_allowed:
                raise ValueError(
                    f"Model path must be within allowed directories: {allowed_dirs}. "
                    f"Got: {model_path}"
                )

        checkpoint = torch.load(str(model_path), map_location=device, weights_only=False)

        config = checkpoint["config"]
        model = cls(
            input_dim=config["input_dim"],
            hidden_dims=tuple(config["hidden_dims"]),
            num_classes=config["num_classes"],
            dropout=config.get("dropout", 0.0),
            leaky_relu_slope=config.get("leaky_relu_slope", 0.01),
            use_batch_norm=config.get("use_batch_norm", True),
        )

        model.load_state_dict(checkpoint["state_dict"])
        model.to(device)
        model.eval()

        return model

    def count_parameters(self) -> int:
        """Count total trainable parameters."""
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

    def summary(self) -> str:
        """Get model summary string."""
        lines = [
            "MLPDirectionClassifier",
            "=" * 50,
            f"Input dimension: {self.input_dim}",
            f"Hidden dimensions: {self.hidden_dims}",
            f"Output classes: {self.num_classes}",
            f"Dropout rate: {self.dropout_rate}",
            f"Total parameters: {self.count_parameters():,}",
            "=" * 50,
        ]
        return "\n".join(lines)


class EnsembleMLPClassifier(nn.Module):
    """
    Ensemble of MLP classifiers for improved robustness.

    Averages predictions from multiple models trained on different
    data splits or with different random seeds.
    """

    def __init__(self, models: list[MLPDirectionClassifier]):
        super().__init__()
        self.models = nn.ModuleList(models)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Average logits from all models."""
        all_logits = torch.stack([model(x) for model in self.models])
        return all_logits.mean(dim=0)

    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        """Average probabilities from all models."""
        self.eval()
        with torch.no_grad():
            all_probs = torch.stack(
                [model.predict_proba(x) for model in self.models]
            )
            return all_probs.mean(dim=0)

    @classmethod
    def load_ensemble(
        cls, paths: list[str], device: str = "cpu", validate_path: bool = True
    ) -> "EnsembleMLPClassifier":
        """Load ensemble from multiple checkpoint files."""
        models = [
            MLPDirectionClassifier.load(path, device, validate_path=validate_path)
            for path in paths
        ]
        return cls(models)


def create_model(
    config: Optional[MLPConfig] = None,
    device: str = "cpu",
) -> MLPDirectionClassifier:
    """
    Factory function to create model.

    Args:
        config: Model configuration (uses defaults if None)
        device: Device to create model on

    Returns:
        Initialized model
    """
    if config is None:
        config = MLPConfig()

    model = MLPDirectionClassifier(
        input_dim=config.input_dim,
        hidden_dims=config.hidden_dims,
        num_classes=config.num_classes,
        dropout=config.dropout,
        leaky_relu_slope=config.leaky_relu_slope,
        use_batch_norm=config.use_batch_norm,
    )

    return model.to(device)


# Quick test when run directly
if __name__ == "__main__":
    # Create model
    model = create_model()
    print(model.summary())

    # Test forward pass
    batch_size = 32
    x = torch.randn(batch_size, 13)
    logits = model(x)
    print(f"\nInput shape: {x.shape}")
    print(f"Output shape: {logits.shape}")

    # Test prediction
    probs = model.predict_proba(x)
    preds = model.predict(x)
    print(f"Probabilities shape: {probs.shape}")
    print(f"Predictions shape: {preds.shape}")
    print(f"Sample prediction: class={preds[0].item()}, probs={probs[0].tolist()}")
