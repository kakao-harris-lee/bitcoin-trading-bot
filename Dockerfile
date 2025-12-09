# Bitcoin Trading Bot - Docker Image
# Python 3.12 기반 경량 이미지

FROM python:3.12-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 패키지 업데이트 및 필수 도구 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    gcc \
    g++ \
    make \
    curl \
    && rm -rf /var/lib/apt/lists/*

# TA-Lib 설치
RUN cd /tmp && \
    wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    ldconfig && \
    cd / && \
    rm -rf /tmp/ta-lib*

# Python 패키지 설치를 위한 requirements 복사
COPY requirements.txt .

# 핵심 패키지만 설치 (Python 3.12 호환)
RUN pip install --no-cache-dir \
    numpy>=2.3.0 \
    pandas>=2.3.0 \
    scipy>=1.16.0 \
    TA-Lib>=0.6.0 \
    pyupbit>=0.2.34 \
    requests>=2.32.0 \
    python-dotenv>=1.2.0 \
    python-binance>=1.0.0 \
    websocket-client>=1.9.0

# 프로젝트 파일 복사
COPY . .

# 로그 디렉토리 생성
RUN mkdir -p /app/logs

# 헬스체크
HEALTHCHECK --interval=60s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# 실행 사용자 생성 (보안)
RUN useradd -m -u 1000 trader && \
    chown -R trader:trader /app
USER trader

# 작업 디렉토리를 live_trading으로 변경
WORKDIR /app/live_trading

# 기본 명령어
CMD ["python", "main.py", "--auto"]
