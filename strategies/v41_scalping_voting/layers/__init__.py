"""
v41 Scalping Voting Layers
3-Layer 투표 시스템

Layer 1: 단기 모멘텀 (3개 전략)
Layer 2: 중기 트렌드 (3개 전략)
Layer 3: Day 캔들 시장 필터 (1개 전략)

Total: 7개 독립 전략 투표
"""

from .layer1_momentum import (
    RsiExtremeStrategy,
    VolumeSpikeStrategy,
    MacdCrossStrategy,
    Layer1MomentumVoter
)

from .layer2_trend import (
    EmaCrossoverStrategy,
    BbReversionStrategy,
    AdxStrengthStrategy,
    Layer2TrendVoter
)

from .layer3_classifier import (
    DayMarketStateClassifier,
    Layer3ClassifierVoter
)

__all__ = [
    # Layer 1
    'RsiExtremeStrategy',
    'VolumeSpikeStrategy',
    'MacdCrossStrategy',
    'Layer1MomentumVoter',

    # Layer 2
    'EmaCrossoverStrategy',
    'BbReversionStrategy',
    'AdxStrengthStrategy',
    'Layer2TrendVoter',

    # Layer 3
    'DayMarketStateClassifier',
    'Layer3ClassifierVoter',
]
