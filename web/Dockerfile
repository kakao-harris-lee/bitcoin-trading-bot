# Web Dashboard Dockerfile
FROM python:3.12-slim

WORKDIR /app

# 시스템 패키지
RUN apt-get update && apt-get install -y \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Python 패키지
COPY web/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 파일 복사
COPY web/ .

# 포트 노출
EXPOSE 8080

# 실행
CMD ["python", "app.py"]
