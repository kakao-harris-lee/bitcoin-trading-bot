"""
Shared constants for MLP Direction training and evaluation.
"""

# Direction classification threshold (for 4H data)
# Returns above this threshold are labeled as Buy, below negative threshold as Sell
DIRECTION_THRESHOLD = 0.005  # 0.5%

# Feature calculation periods (from Parente & Rizzuti 2025 paper)
BOLLINGER_PERIOD = 14
ZSCORE_PERIOD = 30
EMA_PERIODS = (20, 50, 100)

# Model architecture defaults
DEFAULT_HIDDEN_DIMS = (128, 64, 32)
DEFAULT_INPUT_DIM = 36
DEFAULT_NUM_CLASSES = 3

# Inference batch size for memory efficiency
INFERENCE_BATCH_SIZE = 4096

# Allowed model directories for security
ALLOWED_MODEL_DIRS = ["models", "mlp_trainer/models"]
