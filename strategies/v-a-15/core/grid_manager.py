"""
Grid Trading Manager
SIDEWAYS 시장에서 Support/Resistance 기반 Grid Trading
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class GridLevel:
    """Grid 레벨 정보"""
    price: float          # 레벨 가격
    position: int         # 레벨 위치 (0=support, n=resistance)
    allocated: bool       # 자본 배치 여부
    entry_price: float    # 실제 진입 가격 (allocated=True일 때)
    volume: float         # 매수 수량


class GridManager:
    """
    Grid Trading Manager

    SIDEWAYS 시장에서 Support/Resistance 자동 감지하고
    Grid 레벨 기반 진입/청산 관리
    """

    def __init__(self, config: Dict):
        """
        Args:
            config: 설정
                - grid_levels: Grid 레벨 수 (5-7 권장)
                - lookback_period: Support/Resistance 계산 기간 (20일 권장)
                - grid_position_size: 레벨당 포지션 크기 (0.15 = 15%)
                - grid_threshold: 레벨 진입 임계값 (0.02 = 2%)
                - grid_exit_threshold: 레벨 청산 임계값 (0.02 = 2%)
        """
        self.grid_levels_count = config.get('grid_levels', 7)
        self.lookback_period = config.get('lookback_period', 20)
        self.position_size = config.get('grid_position_size', 0.15)
        self.entry_threshold = config.get('grid_threshold', 0.02)
        self.exit_threshold = config.get('grid_exit_threshold', 0.02)

        # Grid 상태
        self.grid_levels: List[GridLevel] = []
        self.support: float = 0.0
        self.resistance: float = 0.0
        self.active: bool = False

    def update_grid(self, df: pd.DataFrame, current_idx: int) -> bool:
        """
        Grid 레벨 업데이트

        Args:
            df: 가격 데이터
            current_idx: 현재 인덱스

        Returns:
            성공 여부
        """
        try:
            # lookback 기간 확인
            if current_idx < self.lookback_period:
                return False

            # Support/Resistance 계산
            lookback_data = df.iloc[current_idx - self.lookback_period:current_idx]
            self.support = lookback_data['low'].min()
            self.resistance = lookback_data['high'].max()

            # Range 높이
            range_height = self.resistance - self.support

            # Range가 너무 좁으면 Grid Trading 비활성화
            if range_height / self.support < 0.03:  # 3% 미만 (완화됨)
                self.active = False
                return False

            # Grid 레벨 생성
            self.grid_levels = []
            for i in range(self.grid_levels_count):
                price = self.support + (range_height * i / (self.grid_levels_count - 1))
                level = GridLevel(
                    price=price,
                    position=i,
                    allocated=False,
                    entry_price=0.0,
                    volume=0.0
                )
                self.grid_levels.append(level)

            self.active = True
            return True

        except Exception as e:
            print(f"❌ Grid 업데이트 실패: {e}")
            self.active = False
            return False

    def check_entry(self, current_price: float, capital: float) -> Optional[Dict]:
        """
        Grid 진입 시그널 확인

        Args:
            current_price: 현재 가격
            capital: 사용 가능 자본

        Returns:
            진입 시그널 또는 None
        """
        if not self.active:
            return None

        # 각 레벨 확인
        for level in self.grid_levels:
            # 이미 배치된 레벨은 스킵
            if level.allocated:
                continue

            # 현재 가격이 레벨 근처인지 확인
            price_diff_pct = abs(current_price - level.price) / level.price

            # 레벨 하회 (매수 기회)
            if current_price <= level.price * (1 - self.entry_threshold):
                # 진입 시그널 생성
                position_size = min(self.position_size, capital / current_price if current_price > 0 else 0)

                if position_size > 0:
                    return {
                        'action': 'buy',
                        'fraction': self.position_size,
                        'reason': f'GRID_LEVEL_{level.position}',
                        'strategy': 'grid',
                        'level': level.position,
                        'grid_price': level.price,
                        'support': self.support,
                        'resistance': self.resistance
                    }

        return None

    def register_entry(self, level_position: int, entry_price: float, volume: float) -> bool:
        """
        진입 등록

        Args:
            level_position: 레벨 위치
            entry_price: 진입 가격
            volume: 매수 수량

        Returns:
            성공 여부
        """
        try:
            if 0 <= level_position < len(self.grid_levels):
                level = self.grid_levels[level_position]
                level.allocated = True
                level.entry_price = entry_price
                level.volume = volume
                return True
            return False
        except Exception as e:
            print(f"❌ 진입 등록 실패: {e}")
            return False

    def check_exit(self, current_price: float) -> Optional[Dict]:
        """
        Grid 청산 시그널 확인

        Args:
            current_price: 현재 가격

        Returns:
            청산 시그널 또는 None
        """
        if not self.active:
            return None

        # 배치된 레벨 확인
        for level in self.grid_levels:
            if not level.allocated:
                continue

            # 다음 레벨 가격 (상위 레벨)
            next_level_price = self.grid_levels[level.position + 1].price if level.position + 1 < len(self.grid_levels) else self.resistance

            # 다음 레벨 상회 시 청산
            if current_price >= next_level_price * (1 + self.exit_threshold):
                profit_pct = (current_price - level.entry_price) / level.entry_price * 100

                return {
                    'action': 'sell',
                    'reason': f'GRID_EXIT_{level.position}',
                    'strategy': 'grid',
                    'level': level.position,
                    'entry_price': level.entry_price,
                    'profit_pct': profit_pct,
                    'volume': level.volume
                }

        return None

    def register_exit(self, level_position: int) -> bool:
        """
        청산 등록 (레벨 초기화)

        Args:
            level_position: 레벨 위치

        Returns:
            성공 여부
        """
        try:
            if 0 <= level_position < len(self.grid_levels):
                level = self.grid_levels[level_position]
                level.allocated = False
                level.entry_price = 0.0
                level.volume = 0.0
                return True
            return False
        except Exception as e:
            print(f"❌ 청산 등록 실패: {e}")
            return False

    def get_status(self) -> Dict:
        """
        Grid 상태 조회

        Returns:
            상태 정보
        """
        allocated_count = sum(1 for level in self.grid_levels if level.allocated)
        total_volume = sum(level.volume for level in self.grid_levels if level.allocated)

        return {
            'active': self.active,
            'support': self.support,
            'resistance': self.resistance,
            'range_pct': (self.resistance - self.support) / self.support * 100 if self.support > 0 else 0,
            'total_levels': len(self.grid_levels),
            'allocated_levels': allocated_count,
            'utilization': allocated_count / len(self.grid_levels) * 100 if self.grid_levels else 0,
            'total_volume': total_volume,
            'levels': [
                {
                    'position': level.position,
                    'price': level.price,
                    'allocated': level.allocated,
                    'entry_price': level.entry_price if level.allocated else None,
                    'volume': level.volume if level.allocated else None
                }
                for level in self.grid_levels
            ]
        }

    def reset(self):
        """Grid 초기화"""
        self.grid_levels = []
        self.support = 0.0
        self.resistance = 0.0
        self.active = False

    def visualize_grid(self, current_price: float) -> str:
        """
        Grid 시각화 (텍스트)

        Args:
            current_price: 현재 가격

        Returns:
            시각화 텍스트
        """
        if not self.active:
            return "Grid 비활성"

        lines = []
        lines.append(f"━━━ Grid Trading Status ━━━")
        lines.append(f"Support: {self.support:,.0f}")
        lines.append(f"Resistance: {self.resistance:,.0f}")
        lines.append(f"Range: {(self.resistance - self.support) / self.support * 100:.2f}%")
        lines.append("")

        for level in reversed(self.grid_levels):
            # 레벨 표시
            level_marker = "├─"
            if level.position == len(self.grid_levels) - 1:
                level_marker = "┬─"
            elif level.position == 0:
                level_marker = "└─"

            # 배치 상태
            status = "✅" if level.allocated else "⬜"

            # 현재 가격 표시
            price_marker = " ← 현재" if abs(current_price - level.price) / level.price < 0.01 else ""

            lines.append(f"{level_marker} L{level.position}: {level.price:,.0f} {status}{price_marker}")

            if level.allocated:
                profit = (current_price - level.entry_price) / level.entry_price * 100
                lines.append(f"   진입: {level.entry_price:,.0f} (수익: {profit:+.2f}%)")

        return "\n".join(lines)


if __name__ == "__main__":
    """Grid Manager 테스트"""
    print("=" * 60)
    print("  Grid Trading Manager 테스트")
    print("=" * 60)

    # 설정
    config = {
        'grid_levels': 7,
        'lookback_period': 20,
        'grid_position_size': 0.15,
        'grid_threshold': 0.02,
        'grid_exit_threshold': 0.02
    }

    # Grid Manager 생성
    manager = GridManager(config)

    # 테스트 데이터 생성 (SIDEWAYS 시장)
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=100, freq='D')

    # SIDEWAYS 패턴 생성 (100M ~ 110M 범위)
    base_price = 105_000_000
    noise = np.random.randn(100) * 2_000_000
    prices = base_price + noise

    df = pd.DataFrame({
        'close': prices,
        'high': prices * 1.01,
        'low': prices * 0.99
    }, index=dates)

    # Grid 업데이트
    current_idx = 50
    success = manager.update_grid(df, current_idx)

    print(f"\n✅ Grid 업데이트: {'성공' if success else '실패'}")

    if success:
        print(f"\n{manager.visualize_grid(df.iloc[current_idx]['close'])}")

        # 상태 조회
        status = manager.get_status()
        print(f"\n📊 Grid 상태:")
        print(f"  Support: {status['support']:,.0f}")
        print(f"  Resistance: {status['resistance']:,.0f}")
        print(f"  Range: {status['range_pct']:.2f}%")
        print(f"  레벨: {status['total_levels']}개")
        print(f"  활용률: {status['utilization']:.1f}%")

        # 진입 테스트
        current_price = df.iloc[current_idx]['close']
        entry_signal = manager.check_entry(current_price * 0.98, capital=10_000_000)

        if entry_signal:
            print(f"\n🔔 진입 시그널:")
            print(f"  레벨: {entry_signal['level']}")
            print(f"  Grid 가격: {entry_signal['grid_price']:,.0f}")
            print(f"  포지션: {entry_signal['fraction'] * 100:.0f}%")

    print(f"\n✅ Grid Manager 테스트 완료!")
