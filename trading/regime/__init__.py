"""Regime intelligence package.

Phase 1 provides multimodal feature schema and fusion utilities for
offline dataset construction. Runtime integration remains
feature-flagged and disabled by default.
"""

from .types import RegimeFeatureRow
from .feature_table import build_regime_feature_table
from .training import (
    CLASS_TO_REGIME,
    DEFAULT_FEATURE_COLUMNS,
    REGIME_TO_CLASS,
    add_regime_target,
    build_supervised_dataset,
    chronological_split,
    compute_class_weight_map,
)
from .ensemble import (
    build_hmm_feature_frame,
    build_hmm_feature_frame_from_table,
    build_state_class_distribution,
    states_to_class_proba,
    combine_probabilities,
    predict_proba_all_classes,
)
from .hybrid import apply_sideways_guard
from .calibration import apply_class_multipliers, tune_class_multipliers
from .runtime import RuntimeRegimeOverlay, RuntimeRegimePrediction

__all__ = [
    "RegimeFeatureRow",
    "build_regime_feature_table",
    "REGIME_TO_CLASS",
    "CLASS_TO_REGIME",
    "DEFAULT_FEATURE_COLUMNS",
    "add_regime_target",
    "build_supervised_dataset",
    "chronological_split",
    "compute_class_weight_map",
    "build_hmm_feature_frame",
    "build_hmm_feature_frame_from_table",
    "build_state_class_distribution",
    "states_to_class_proba",
    "combine_probabilities",
    "predict_proba_all_classes",
    "apply_sideways_guard",
    "apply_class_multipliers",
    "tune_class_multipliers",
    "RuntimeRegimeOverlay",
    "RuntimeRegimePrediction",
]
