"""
pytest 설정 파일
"""

import pytest
import asyncio
import sys
import os

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session")
def event_loop():
    """asyncio 이벤트 루프"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


def pytest_configure(config):
    """pytest 설정"""
    config.addinivalue_line(
        "markers", "integration: 통합 테스트 (실제 연결 필요)"
    )
    config.addinivalue_line(
        "markers", "slow: 느린 테스트"
    )
