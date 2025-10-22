"""
Signal Extractor Base
=====================
모든 전략의 시그널 추출기 베이스 클래스

각 전략은 이 클래스를 상속하여 extract_signals() 메서드만 구현하면 됨

작성일: 2025-10-20
"""

import json
import importlib.util
import sys
import sqlite3
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional
from abc import ABC, abstractmethod


class SignalExtractorBase(ABC):
    """
    전략 독립적인 시그널 추출기 베이스 클래스

    모든 전략은 이 클래스를 상속하여:
    1. extract_signals(year) 메서드 구현
    2. 표준 포맷 시그널 배열 반환
    """

    def __init__(self, strategy_version: str):
        """
        Args:
            strategy_version: 전략 버전 (예: 'v43', 'v35', etc.)
        """
        self.version = strategy_version
        self.project_root = Path(__file__).parent.parent
        self.strategy_path = self.project_root / 'strategies' / strategy_version

        # 메타데이터 로드
        self.config = self.load_config()
        self.metadata = self.load_metadata()

        # DB 경로
        self.db_path = self.project_root / 'upbit_bitcoin.db'

    @abstractmethod
    def extract_signals(self, year: int) -> List[Dict]:
        """
        전략별 시그널 추출 (구현 필요)

        Args:
            year: 연도 (2020-2025)

        Returns:
            표준 포맷 시그널 배열:
            [{
                'timestamp': '2024-01-01 09:00',
                'action': 'BUY',
                'price': 58839000,
                'score': 42 (optional),
                'indicators': {...} (optional)
            }]
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement extract_signals()"
        )

    def load_config(self) -> Optional[Dict]:
        """config.json 로드"""
        config_path = self.strategy_path / 'config.json'

        if not config_path.exists():
            return None

        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️  config.json 로드 실패: {e}")
            return None

    def load_metadata(self) -> Dict:
        """전략 메타데이터 로드"""
        # 나중에 strategy_metadata.json에서 로드할 예정
        # 현재는 기본값 반환
        return {
            'timeframe': self.config.get('timeframe', 'day') if self.config else 'day',
            'name': self.version.replace('_', ' ').title()
        }

    def load_strategy_module(self):
        """strategy.py 동적 임포트"""
        strategy_file = self.strategy_path / 'strategy.py'

        if not strategy_file.exists():
            raise FileNotFoundError(
                f"strategy.py not found: {strategy_file}"
            )

        # 동적 임포트
        spec = importlib.util.spec_from_file_location(
            f"{self.version}_strategy",
            strategy_file
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{self.version}_strategy"] = module
        spec.loader.exec_module(module)

        return module

    def load_price_data(
        self,
        year: int,
        timeframe: Optional[str] = None
    ) -> pd.DataFrame:
        """
        가격 데이터 로드

        Args:
            year: 연도
            timeframe: 타임프레임 (None이면 metadata에서 자동 로드)

        Returns:
            DataFrame with columns: [timestamp, open, high, low, close, volume]
        """
        if timeframe is None:
            timeframe = self.metadata['timeframe']

        # 타임프레임별 테이블명
        table_map = {
            'minute5': 'bitcoin_minute5',
            'minute15': 'bitcoin_minute15',
            'minute60': 'bitcoin_minute60',
            'minute240': 'bitcoin_minute240',
            'day': 'bitcoin_day'
        }

        table = table_map.get(timeframe, 'bitcoin_day')

        # 연도 필터링
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31 23:59:59"

        query = f"""
            SELECT timestamp, open, high, low, close, volume
            FROM {table}
            WHERE timestamp >= '{start_date}' AND timestamp <= '{end_date}'
            ORDER BY timestamp
        """

        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query(query, conn)
        conn.close()

        return df

    def get_exit_config(self) -> Dict:
        """
        전략의 청산 설정 로드

        Returns:
            exit_config: {
                'type': 'fixed',
                'take_profit': 0.05,
                'stop_loss': 0.02,
                'timeout_hours': 72
            }
        """
        if not self.config:
            # 기본값 (대부분의 전략)
            return {
                'type': 'fixed',
                'take_profit': 0.05,
                'stop_loss': 0.02,
                'timeout_hours': 72
            }

        # config에서 exit 설정 추출
        return {
            'type': self.config.get('exit_type', 'fixed'),
            'take_profit': self.config.get('take_profit', 0.05),
            'stop_loss': self.config.get('stop_loss', 0.02),
            'timeout_hours': self.config.get('max_holding_hours', 72),
            'trailing_stop': self.config.get('trailing_stop')  # optional
        }

    @staticmethod
    def standardize_signal(signal: Dict) -> Dict:
        """
        시그널을 표준 포맷으로 변환

        Args:
            signal: 원본 시그널 (다양한 형식)

        Returns:
            표준 포맷 시그널
        """
        return {
            'timestamp': signal.get('timestamp') or signal.get('time') or signal.get('date'),
            'action': signal.get('action', 'BUY').upper(),
            'price': signal.get('price') or signal.get('close') or signal.get('entry_price'),
            'score': signal.get('score'),
            'indicators': signal.get('indicators', {})
        }

    def validate_signals(self, signals: List[Dict]) -> List[Dict]:
        """
        시그널 유효성 검사

        - timestamp, price 필수 체크
        - 중복 제거
        - 시간순 정렬
        """
        valid_signals = []

        for signal in signals:
            # 필수 필드 체크
            if not signal.get('timestamp') or not signal.get('price'):
                continue

            # 표준화
            std_signal = self.standardize_signal(signal)
            valid_signals.append(std_signal)

        # 중복 제거 (timestamp 기준)
        seen = set()
        unique_signals = []
        for signal in valid_signals:
            ts = signal['timestamp']
            if ts not in seen:
                seen.add(ts)
                unique_signals.append(signal)

        # 시간순 정렬
        unique_signals.sort(key=lambda x: x['timestamp'])

        return unique_signals

    def get_timeframe(self) -> str:
        """전략의 타임프레임 반환"""
        return self.metadata['timeframe']

    def get_strategy_name(self) -> str:
        """전략 이름 반환"""
        return self.metadata['name']

    def __repr__(self):
        return f"<SignalExtractor: {self.version} ({self.metadata['timeframe']})>"


class SimpleSignalExtractor(SignalExtractorBase):
    """
    간단한 시그널 추출기 (테스트용)

    기존 results.json이 있는 전략에 사용
    """

    def extract_signals(self, year: int) -> List[Dict]:
        """
        results.json에서 시그널 추출

        Note: 이 방법은 기존 백테스팅 결과가 있을 때만 사용 가능
        """
        results_path = self.strategy_path / 'results.json'

        if not results_path.exists():
            print(f"⚠️  {self.version}: results.json not found")
            return []

        try:
            with open(results_path) as f:
                results = json.load(f)

            # trades에서 entry 시그널 추출
            if 'trades' in results:
                signals = []
                for trade in results['trades']:
                    # 연도 필터링
                    entry_time = trade.get('entry_time') or trade.get('entry_timestamp')
                    if entry_time and entry_time.startswith(str(year)):
                        signals.append({
                            'timestamp': entry_time,
                            'action': 'BUY',
                            'price': trade.get('entry_price'),
                            'score': trade.get('score')
                        })

                return self.validate_signals(signals)

            return []

        except Exception as e:
            print(f"❌ {self.version}: Error loading results.json: {e}")
            return []


if __name__ == '__main__':
    # 테스트
    print("=" * 60)
    print("Signal Extractor Base - Test")
    print("=" * 60)

    # SimpleSignalExtractor 테스트 (v43)
    print("\n[Test: SimpleSignalExtractor with v43]")
    extractor = SimpleSignalExtractor('v43_supreme_scalping')

    print(f"Version: {extractor.version}")
    print(f"Timeframe: {extractor.get_timeframe()}")
    print(f"Name: {extractor.get_strategy_name()}")
    print(f"Exit Config: {extractor.get_exit_config()}")

    # 2024년 시그널 추출 시도
    signals_2024 = extractor.extract_signals(2024)
    print(f"\n2024 Signals: {len(signals_2024)} found")

    if signals_2024:
        print("\nFirst 3 signals:")
        for i, signal in enumerate(signals_2024[:3], 1):
            print(f"  {i}. {signal['timestamp']}: {signal['price']:,}원")

    print("\n" + "=" * 60)
