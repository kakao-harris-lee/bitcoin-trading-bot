"""
베이스 시그널 추출기
모든 전략의 시그널 추출기는 이 클래스를 상속받아 구현
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from pathlib import Path
import pandas as pd
import sqlite3
from datetime import datetime
import sys

# core 모듈 import를 위한 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

class BaseSignalExtractor(ABC):
    """시그널 추출기 베이스 클래스"""

    def __init__(self, strategy_name: str, version: str):
        """
        Args:
            strategy_name: 전략 이름 (예: "scalping_with_classifier")
            version: 버전 (예: "v31")
        """
        self.strategy_name = strategy_name
        self.version = version
        self.db_path = Path(__file__).parent.parent.parent / "upbit_bitcoin.db"

    def load_data(self, year: int, timeframe: str = 'day') -> pd.DataFrame:
        """데이터 로드

        Args:
            year: 연도 (2020-2025)
            timeframe: 타임프레임 (day, minute60, minute240, minute15, minute5)

        Returns:
            DataFrame with OHLCV + indicators
        """
        conn = sqlite3.connect(str(self.db_path))

        # 테이블 이름 결정
        table_mapping = {
            'day': 'bitcoin_day',
            'minute60': 'bitcoin_minute60',
            'minute240': 'bitcoin_minute240',
            'minute15': 'bitcoin_minute15',
            'minute5': 'bitcoin_minute5'
        }

        table_name = table_mapping.get(timeframe, 'bitcoin_day')

        # 연도 필터링
        query = f"""
        SELECT * FROM {table_name}
        WHERE timestamp >= '{year}-01-01'
          AND timestamp < '{year+1}-01-01'
        ORDER BY timestamp ASC
        """

        try:
            df = pd.read_sql_query(query, conn)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')
            return df
        except Exception as e:
            print(f"데이터 로드 실패 ({timeframe}, {year}): {e}")
            return pd.DataFrame()
        finally:
            conn.close()

    @abstractmethod
    def extract_buy_signals(self, df: pd.DataFrame) -> List[Dict]:
        """매수 시그널 추출 (반드시 구현)

        Args:
            df: OHLCV + indicators DataFrame

        Returns:
            List of buy signals:
            [
                {
                    'timestamp': '2020-03-22 09:00:00',  # str 형식
                    'price': 7367473.2,                  # 매수 가격
                    'reason': 'MFI>50 AND MACD>Signal',  # 진입 이유
                    'confidence': 0.8,                   # 신뢰도 (옵션)
                    'position_size': 0.5,                # 투자 비율 (옵션, 기본 1.0)
                    'metadata': {...}                    # 추가 정보 (옵션)
                },
                ...
            ]
        """
        pass

    @abstractmethod
    def extract_sell_signals(self, df: pd.DataFrame,
                            buy_signals: List[Dict]) -> List[Dict]:
        """매도 시그널 추출 (반드시 구현)

        Args:
            df: OHLCV + indicators DataFrame
            buy_signals: extract_buy_signals()의 반환값

        Returns:
            List of sell signals (매수와 1:1 대응):
            [
                {
                    'buy_index': 0,                      # buy_signals의 인덱스
                    'timestamp': '2020-12-30 09:00:00',  # str 형식
                    'price': 31884621.8,                 # 매도 가격
                    'reason': 'Take Profit +5%',         # 청산 이유
                    'hold_hours': 6552,                  # 보유 시간 (hours)
                    'metadata': {...}                    # 추가 정보 (옵션)
                },
                ...
            ]
        """
        pass

    def extract_all(self, year: int, timeframe: str = 'day') -> Dict:
        """전체 시그널 추출 (표준 인터페이스)

        Args:
            year: 연도 (2020-2025)
            timeframe: 타임프레임

        Returns:
            {
                'version': 'v31',
                'strategy_name': 'scalping_with_classifier',
                'year': 2020,
                'timeframe': 'day',
                'buy_signals': [...],
                'sell_signals': [...],
                'signal_count': 10,
                'extraction_date': '2025-10-21T07:00:00'
            }
        """
        print(f"[{self.version}] {year} {timeframe} 시그널 추출 시작...")

        # 데이터 로드
        df = self.load_data(year, timeframe)

        if df.empty:
            print(f"[{self.version}] {year} {timeframe} 데이터 없음")
            return {
                'version': self.version,
                'strategy_name': self.strategy_name,
                'year': year,
                'timeframe': timeframe,
                'buy_signals': [],
                'sell_signals': [],
                'signal_count': 0,
                'extraction_date': datetime.now().isoformat(),
                'error': 'No data available'
            }

        # 시그널 추출
        try:
            buy_signals = self.extract_buy_signals(df)
            sell_signals = self.extract_sell_signals(df, buy_signals)

            # 검증: 매수/매도 개수 일치
            if len(buy_signals) != len(sell_signals):
                print(f"[{self.version}] WARNING: 매수({len(buy_signals)}) != 매도({len(sell_signals)})")

            result = {
                'version': self.version,
                'strategy_name': self.strategy_name,
                'year': year,
                'timeframe': timeframe,
                'buy_signals': buy_signals,
                'sell_signals': sell_signals,
                'signal_count': len(buy_signals),
                'extraction_date': datetime.now().isoformat()
            }

            print(f"[{self.version}] {year} {timeframe} 시그널 {len(buy_signals)}개 추출 완료")
            return result

        except Exception as e:
            print(f"[{self.version}] {year} {timeframe} 시그널 추출 실패: {e}")
            import traceback
            traceback.print_exc()

            return {
                'version': self.version,
                'strategy_name': self.strategy_name,
                'year': year,
                'timeframe': timeframe,
                'buy_signals': [],
                'sell_signals': [],
                'signal_count': 0,
                'extraction_date': datetime.now().isoformat(),
                'error': str(e)
            }

    def save_signals(self, signals: Dict, output_dir: Optional[Path] = None):
        """시그널 JSON 저장

        Args:
            signals: extract_all()의 반환값
            output_dir: 저장 디렉토리 (기본: validation/signals/)
        """
        import json

        if output_dir is None:
            output_dir = Path(__file__).parent.parent / "signals"

        output_dir.mkdir(parents=True, exist_ok=True)

        # 파일명: v31_signals_2020_day.json
        filename = f"{signals['version']}_signals_{signals['year']}_{signals['timeframe']}.json"
        filepath = output_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(signals, f, indent=2, ensure_ascii=False)

        print(f"[{self.version}] 시그널 저장: {filepath}")

    def calculate_hold_hours(self, buy_timestamp: str, sell_timestamp: str) -> int:
        """보유 시간 계산 (헬퍼 함수)

        Args:
            buy_timestamp: 매수 시간 (str 또는 pandas.Timestamp)
            sell_timestamp: 매도 시간 (str 또는 pandas.Timestamp)

        Returns:
            보유 시간 (hours)
        """
        if isinstance(buy_timestamp, str):
            buy_ts = pd.to_datetime(buy_timestamp)
        else:
            buy_ts = buy_timestamp

        if isinstance(sell_timestamp, str):
            sell_ts = pd.to_datetime(sell_timestamp)
        else:
            sell_ts = sell_timestamp

        delta = sell_ts - buy_ts
        return int(delta.total_seconds() / 3600)

    def find_exit_point(self,
                       df: pd.DataFrame,
                       entry_idx: int,
                       entry_price: float,
                       take_profit_pct: float = 0.05,
                       stop_loss_pct: float = -0.02,
                       max_hold_hours: Optional[int] = None) -> Dict:
        """청산 지점 찾기 (헬퍼 함수)

        Args:
            df: DataFrame
            entry_idx: 매수 인덱스
            entry_price: 매수 가격
            take_profit_pct: 익절 비율 (0.05 = 5%)
            stop_loss_pct: 손절 비율 (-0.02 = -2%)
            max_hold_hours: 최대 보유 시간 (None = 무제한)

        Returns:
            {
                'exit_idx': int,
                'exit_price': float,
                'exit_reason': str,
                'hold_hours': int
            }
        """
        tp_price = entry_price * (1 + take_profit_pct)
        sl_price = entry_price * (1 + stop_loss_pct)

        # entry_idx 이후 데이터
        future_df = df.iloc[entry_idx + 1:]

        if future_df.empty:
            # 데이터 끝: 마지막 가격으로 청산
            last_idx = len(df) - 1
            return {
                'exit_idx': last_idx,
                'exit_price': df.iloc[last_idx]['close'],
                'exit_reason': 'End of data',
                'hold_hours': self.calculate_hold_hours(
                    df.index[entry_idx],
                    df.index[last_idx]
                )
            }

        for i, (timestamp, row) in enumerate(future_df.iterrows(), start=1):
            # 익절 체크
            if row['high'] >= tp_price:
                return {
                    'exit_idx': entry_idx + i,
                    'exit_price': tp_price,
                    'exit_reason': f'Take Profit {take_profit_pct*100:.1f}%',
                    'hold_hours': self.calculate_hold_hours(
                        df.index[entry_idx],
                        timestamp
                    )
                }

            # 손절 체크
            if row['low'] <= sl_price:
                return {
                    'exit_idx': entry_idx + i,
                    'exit_price': sl_price,
                    'exit_reason': f'Stop Loss {stop_loss_pct*100:.1f}%',
                    'hold_hours': self.calculate_hold_hours(
                        df.index[entry_idx],
                        timestamp
                    )
                }

            # 최대 보유 시간 체크
            if max_hold_hours is not None:
                hold_hours = self.calculate_hold_hours(df.index[entry_idx], timestamp)
                if hold_hours >= max_hold_hours:
                    return {
                        'exit_idx': entry_idx + i,
                        'exit_price': row['close'],
                        'exit_reason': f'Timeout {max_hold_hours}h',
                        'hold_hours': hold_hours
                    }

        # 데이터 끝까지 도달: 마지막 가격으로 청산
        last_idx = len(df) - 1
        return {
            'exit_idx': last_idx,
            'exit_price': df.iloc[last_idx]['close'],
            'exit_reason': 'End of data',
            'hold_hours': self.calculate_hold_hours(
                df.index[entry_idx],
                df.index[last_idx]
            )
        }
