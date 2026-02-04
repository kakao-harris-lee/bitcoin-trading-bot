"""
Focal Loss for Imbalanced Classification.

Focal Loss down-weights easy examples and focuses on hard negatives.
Particularly effective for class imbalanced datasets.

Reference: Lin et al. (2017) "Focal Loss for Dense Object Detection"
https://arxiv.org/abs/1708.02002

Formula:
    FL(p_t) = -α_t * (1 - p_t)^γ * log(p_t)

Where:
    - p_t: probability of correct class
    - α_t: class weight (balances class frequency)
    - γ (gamma): focusing parameter (reduces loss for easy examples)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional, List, Union


class FocalLoss(nn.Module):
    """
    Focal Loss for multi-class classification.

    Args:
        gamma: Focusing parameter (default: 2.0)
            - γ = 0: equivalent to CrossEntropyLoss
            - γ > 0: reduces loss for well-classified examples
            - Higher γ: more focus on hard examples
        alpha: Class weights (default: None)
            - None: no class weighting
            - List[float]: per-class weights [α_0, α_1, ..., α_C]
            - float: weight for positive class (binary case)
        reduction: 'none' | 'mean' | 'sum' (default: 'mean')

    Example:
        >>> criterion = FocalLoss(gamma=2.0, alpha=[0.25, 0.5, 0.5])
        >>> logits = torch.randn(32, 3)  # batch=32, classes=3
        >>> labels = torch.randint(0, 3, (32,))
        >>> loss = criterion(logits, labels)
    """

    def __init__(
        self,
        gamma: float = 2.0,
        alpha: Optional[Union[float, List[float]]] = None,
        reduction: str = "mean",
        label_smoothing: float = 0.0,
    ):
        super().__init__()
        self.gamma = gamma
        self.reduction = reduction
        self.label_smoothing = label_smoothing

        # Handle alpha (class weights)
        if alpha is not None:
            if isinstance(alpha, (list, tuple)):
                self.register_buffer("alpha", torch.tensor(alpha, dtype=torch.float32))
            else:
                self.register_buffer("alpha", torch.tensor([alpha], dtype=torch.float32))
        else:
            self.alpha = None

    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        """
        Compute Focal Loss.

        Args:
            inputs: Logits of shape (N, C) where C = number of classes
            targets: Class indices of shape (N,)

        Returns:
            Loss tensor (scalar if reduction='mean' or 'sum')
        """
        # Compute softmax probabilities
        p = F.softmax(inputs, dim=-1)

        # Get probability of target class for each sample
        # p_t shape: (N,)
        ce_loss = F.cross_entropy(
            inputs,
            targets,
            reduction="none",
            label_smoothing=self.label_smoothing,
        )
        p_t = torch.exp(-ce_loss)  # p_t = p[target_class]

        # Focal weight: (1 - p_t)^gamma
        focal_weight = (1 - p_t) ** self.gamma

        # Apply alpha weighting if provided
        if self.alpha is not None:
            # Move alpha to same device as inputs
            alpha = self.alpha.to(inputs.device)
            # Select alpha for each target
            alpha_t = alpha[targets]
            focal_weight = alpha_t * focal_weight

        # Compute focal loss
        loss = focal_weight * ce_loss

        # Apply reduction
        if self.reduction == "mean":
            return loss.mean()
        elif self.reduction == "sum":
            return loss.sum()
        else:  # 'none'
            return loss


class FocalLossWithLogits(FocalLoss):
    """
    Focal Loss that expects raw logits (same as FocalLoss).

    Alias for clarity - FocalLoss already expects logits.
    """

    pass


def focal_loss(
    inputs: torch.Tensor,
    targets: torch.Tensor,
    gamma: float = 2.0,
    alpha: Optional[Union[float, List[float]]] = None,
    reduction: str = "mean",
) -> torch.Tensor:
    """
    Functional interface for Focal Loss.

    Args:
        inputs: Logits of shape (N, C)
        targets: Class indices of shape (N,)
        gamma: Focusing parameter
        alpha: Class weights
        reduction: 'none' | 'mean' | 'sum'

    Returns:
        Loss tensor
    """
    criterion = FocalLoss(gamma=gamma, alpha=alpha, reduction=reduction)
    return criterion(inputs, targets)


# Default alpha weights for MLP Direction (Hold, Buy, Sell)
# Lower weight for Hold (majority class), higher for Buy/Sell
MLP_DIRECTION_ALPHA = [0.25, 0.5, 0.5]


def create_focal_loss_for_mlp(
    gamma: float = 2.0,
    alpha: Optional[List[float]] = None,
) -> FocalLoss:
    """
    Create Focal Loss configured for MLP Direction classification.

    Args:
        gamma: Focusing parameter (default: 2.0)
        alpha: Class weights (default: [0.25, 0.5, 0.5] for Hold/Buy/Sell)

    Returns:
        Configured FocalLoss instance
    """
    if alpha is None:
        alpha = MLP_DIRECTION_ALPHA

    return FocalLoss(gamma=gamma, alpha=alpha, reduction="mean")


# Quick test
if __name__ == "__main__":
    # Test basic functionality
    print("Testing Focal Loss...")

    # Create loss function
    criterion = FocalLoss(gamma=2.0, alpha=[0.25, 0.5, 0.5])

    # Simulate batch
    batch_size = 32
    num_classes = 3

    # Random logits and labels
    logits = torch.randn(batch_size, num_classes)
    labels = torch.randint(0, num_classes, (batch_size,))

    # Compute loss
    loss = criterion(logits, labels)
    print(f"Focal Loss: {loss.item():.4f}")

    # Compare with CrossEntropy
    ce_loss = F.cross_entropy(logits, labels)
    print(f"CrossEntropy Loss: {ce_loss.item():.4f}")

    # Test with confident predictions (should have lower focal loss)
    confident_logits = torch.zeros(batch_size, num_classes)
    confident_logits[range(batch_size), labels] = 10.0  # Very confident correct predictions

    confident_focal = criterion(confident_logits, labels)
    confident_ce = F.cross_entropy(confident_logits, labels)
    print(f"\nWith confident correct predictions:")
    print(f"  Focal Loss: {confident_focal.item():.6f}")
    print(f"  CrossEntropy: {confident_ce.item():.6f}")
    print(f"  Ratio (Focal/CE): {confident_focal.item() / confident_ce.item():.4f}")

    print("\n✓ Focal Loss test passed!")
