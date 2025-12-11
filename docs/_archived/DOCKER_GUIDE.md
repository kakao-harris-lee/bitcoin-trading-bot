# Docker Compose 실행 가이드

**최종 업데이트**: 2025-12-09

---

## 🐳 개요

Docker Compose를 사용하여 다음 서비스를 한번에 실행:
1. **듀얼 트레이딩 봇**: 업비트 + 바이넨스 헤지 전략
2. **웹 대시보드**: 실시간 거래 내역 모니터링

---

## 📋 사전 준비

### 1. Docker 설치

**macOS/Windows**:
- Docker Desktop 설치: https://www.docker.com/products/docker-desktop

**Linux (Ubuntu/Debian)**:
```bash
# Docker 설치
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# 현재 사용자를 docker 그룹에 추가
sudo usermod -aG docker $USER
newgrp docker

# Docker Compose 설치
sudo apt-get update
sudo apt-get install docker-compose-plugin
```

### 2. .env 파일 확인

프로젝트 루트에 `.env` 파일이 있는지 확인:

```bash
# .env 파일 내용
UPBIT_ACCESS_KEY=your_upbit_access_key
UPBIT_SECRET_KEY=your_upbit_secret_key
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
TELEGRAM_BOT_TOKEN=your_telegram_token
TELEGRAM_CHAT_ID=your_chat_id
```

---

## 🚀 실행 방법

### 방법 1: 자동 스크립트 (권장)

```bash
# 로컬에서 실행
./docker-start.sh
```

### 방법 2: 수동 실행

```bash
# 1. DB 생성 (처음 실행 시)
python3 setup_dashboard_db.py

# 2. Docker Compose 실행
docker-compose up -d --build

# 3. 상태 확인
docker-compose ps
```

---

## 📊 접속

### 웹 대시보드
```
http://localhost:8000
```

**또는 서버 IP**:
```
http://49.247.171.64:8000
```

---

## 🔍 모니터링

### 실시간 로그 확인

```bash
# 전체 로그
docker-compose logs -f

# 트레이딩 봇만
docker-compose logs -f trading-bot

# 대시보드만
docker-compose logs -f dashboard
```

### 컨테이너 상태 확인

```bash
docker-compose ps
```

**예상 출력**:
```
NAME                         STATUS              PORTS
bitcoin-dual-trading-bot     Up 5 minutes
trading-dashboard            Up 5 minutes        0.0.0.0:8000->8000/tcp
```

### 컨테이너 내부 접속

```bash
# 트레이딩 봇
docker exec -it bitcoin-dual-trading-bot bash

# 대시보드
docker exec -it trading-dashboard bash
```

---

## 🛠️ 관리 명령어

### 서비스 제어

```bash
# 중지
docker-compose down

# 재시작
docker-compose restart

# 특정 서비스만 재시작
docker-compose restart trading-bot
docker-compose restart dashboard

# 로그 삭제 후 재시작
docker-compose down
docker-compose up -d --build
```

### 리소스 관리

```bash
# 사용 중인 리소스 확인
docker stats

# 미사용 이미지/컨테이너 정리
docker system prune -a

# 볼륨 정리 (주의: DB 삭제됨)
docker-compose down -v
```

---

## 📁 파일 구조

### 호스트 <-> 컨테이너 매핑

```
호스트                              컨테이너
./logs/                    <->    /app/logs/
./trading_results.db       <->    /app/trading_results.db
./.env                     <->    컨테이너 환경변수
./strategies/              <->    /app/strategies/
```

### 로그 파일 위치

```bash
# 호스트에서 직접 확인
tail -f logs/trading.log
tail -f logs/error.log
```

---

## 🔧 설정 변경

### 체크 주기 변경

`docker-compose.yml` 수정:

```yaml
services:
  trading-bot:
    command: ["python", "main_dual.py", "--mode", "hedge", "--interval", "60"]
    #                                                                     ^^^
    #                                                                60초 (1분)
```

변경 후:
```bash
docker-compose up -d --build
```

### 헤지 모드 변경

**헤지 모드** (바이넨스 숏):
```yaml
command: ["python", "main_dual.py", "--mode", "hedge", "--interval", "300"]
```

**현금 전환 모드** (바이넨스 사용 안함):
```yaml
command: ["python", "main_dual.py", "--mode", "cash", "--interval", "300"]
```

---

## 🐛 문제 해결

### 1. 포트 8000이 이미 사용 중

```bash
# 포트 사용 확인
lsof -i :8000

# 프로세스 종료
kill -9 <PID>

# 또는 다른 포트 사용
# docker-compose.yml에서 수정:
ports:
  - "8080:8000"  # 호스트 포트를 8080으로 변경
```

### 2. 컨테이너가 계속 재시작됨

```bash
# 로그 확인
docker-compose logs trading-bot

# 일반적인 원인:
# - .env 파일 누락 또는 잘못된 API 키
# - trading_results.db 권한 문제
# - 메모리 부족
```

### 3. DB 파일 권한 오류

```bash
# 호스트에서 권한 수정
chmod 666 trading_results.db

# 또는 소유자 변경
chown 1000:1000 trading_results.db
```

### 4. 이미지 빌드 실패

```bash
# 캐시 삭제 후 재빌드
docker-compose build --no-cache

# 또는 모든 이미지 삭제 후 재빌드
docker-compose down --rmi all
docker-compose up -d --build
```

---

## 📈 성능 최적화

### 리소스 제한 조정

`docker-compose.yml`에서:

```yaml
deploy:
  resources:
    limits:
      cpus: '1.0'      # CPU 제한 (기본 0.8)
      memory: 2G       # 메모리 제한 (기본 1G)
    reservations:
      memory: 512M     # 최소 메모리 (기본 256M)
```

---

## 🔐 보안

### 1. .env 파일 보호

```bash
# 권한 설정 (소유자만 읽기)
chmod 600 .env

# Git에서 제외 (.gitignore에 추가)
echo ".env" >> .gitignore
```

### 2. 컨테이너 격리

- 컨테이너는 `trading-network`라는 격리된 네트워크에서 실행
- 외부에서는 대시보드 포트(8000)만 접근 가능
- 트레이딩 봇은 외부에 노출되지 않음

---

## 🚀 서버 배포 (Linux)

### 1. 프로젝트 복사

```bash
# 로컬에서
rsync -avz --progress \
  --exclude 'venv/' \
  --exclude '.git/' \
  --exclude '*.db' \
  ./ deploy@49.247.171.64:~/bitcoin-trading-bot/
```

### 2. 서버에서 실행

```bash
ssh deploy@49.247.171.64

cd ~/bitcoin-trading-bot

# .env 파일 확인 및 수정
nano .env

# DB 생성
python3 setup_dashboard_db.py

# Docker Compose 실행
docker-compose up -d --build

# 로그 확인
docker-compose logs -f
```

### 3. 방화벽 설정

```bash
# 포트 8000 열기 (대시보드)
sudo ufw allow 8000/tcp

# 또는 iptables
sudo iptables -A INPUT -p tcp --dport 8000 -j ACCEPT
```

---

## 📊 모니터링 대시보드

### Portainer 설치 (선택)

Docker 컨테이너를 GUI로 관리:

```bash
docker volume create portainer_data

docker run -d \
  -p 9000:9000 \
  --name=portainer \
  --restart=always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  portainer/portainer-ce
```

접속: `http://localhost:9000`

---

## 📞 지원

### 로그 수집

문제 발생 시:

```bash
# 전체 로그 저장
docker-compose logs > docker-logs.txt

# 시스템 정보
docker-compose ps > docker-status.txt
docker stats --no-stream >> docker-status.txt
```

---

## ✅ 체크리스트

### 배포 전
- [ ] Docker 설치 완료
- [ ] .env 파일 생성 및 확인
- [ ] trading_results.db 생성
- [ ] API 키 IP 제한 확인 (업비트)

### 배포 후
- [ ] 컨테이너 정상 실행 확인 (`docker-compose ps`)
- [ ] 웹 대시보드 접속 확인 (`http://localhost:8000`)
- [ ] 로그 정상 출력 확인 (`docker-compose logs -f`)
- [ ] 첫 거래 시그널 확인 (텔레그램)

---

**작성일**: 2025-12-09
**버전**: 1.0
