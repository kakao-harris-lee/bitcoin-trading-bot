# 🚀 서버 배포 가이드

새로운 서버(49.247.171.64)에 Bitcoin Trading Bot을 Docker Compose로 배포하는 가이드입니다.

---

## 📋 목차

1. [서버 정보](#서버-정보)
2. [사전 준비](#사전-준비)
3. [빠른 시작](#빠른-시작)
4. [서버 설정](#서버-설정)
5. [배포 방법](#배포-방법)
6. [모니터링](#모니터링)
7. [문제 해결](#문제-해결)

---

## 🖥️ 서버 정보

- **서버 주소**: 49.247.171.64
- **SSH 접속**: `ssh deploy@49.247.171.64`
- **배포 경로**: `/home/deploy/bitcoin-trading-bot`
- **배포 방식**: Docker Compose

---

## ⚙️ 사전 준비

### 1. 로컬 환경

```bash
# .env 파일 생성 (루트 디렉토리)
cat > .env << 'EOF'
UPBIT_ACCESS_KEY=your_access_key
UPBIT_SECRET_KEY=your_secret_key
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
AUTO_TRADE=False
EOF

# upbit_bitcoin.db 준비 (없으면 서버에서 수집)
# 있다면 489MB 데이터베이스 파일을 준비
```

### 2. SSH 키 등록

```bash
# SSH 키 생성 (없는 경우)
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"

# 서버에 SSH 키 등록
ssh-copy-id deploy@49.247.171.64

# 접속 테스트
ssh deploy@49.247.171.64
```

---

## 🚀 빠른 시작

### 자동 배포 (권장)

```bash
# 1. 배포 스크립트 실행 권한 부여
chmod +x deployment/deploy_to_server.sh
chmod +x deployment/monitor_server.sh

# 2. 서버로 배포
./deployment/deploy_to_server.sh

# 3. 모니터링
./deployment/monitor_server.sh
```

배포 스크립트가 자동으로:

- ✅ SSH 연결 확인
- ✅ 필수 파일 전송
- ✅ Docker 설치 (필요시)
- ✅ Docker Compose 빌드 및 실행
- ✅ 컨테이너 상태 확인

---

## 🛠️ 서버 설정

### Docker 수동 설치 (자동 배포로 안 되는 경우)

```bash
# 서버 접속
ssh deploy@49.247.171.64

# Docker 설치
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Docker Compose 설치 (Docker Desktop이 아닌 경우)
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 재로그인
exit
ssh deploy@49.247.171.64

# 확인
docker --version
docker compose version
```

---

## 📦 배포 방법

### 방법 1: 자동 배포 스크립트 (권장)

```bash
cd /path/to/bitcoin-trading-bot
./deployment/deploy_to_server.sh
```

### 방법 2: 수동 배포

```bash
# 1. 파일 전송
rsync -avz --progress \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='venv' \
    --exclude='logs/*.log' \
    ./ deploy@49.247.171.64:/home/deploy/bitcoin-trading-bot/

# 2. 서버 접속
ssh deploy@49.247.171.64

# 3. 작업 디렉토리 이동
cd /home/deploy/bitcoin-trading-bot

# 4. Docker Compose 실행
docker compose build
docker compose up -d

# 5. 상태 확인
docker compose ps
docker compose logs -f
```

---

## 📊 모니터링

### 대화형 모니터링 도구

```bash
# 로컬에서 실행
./deployment/monitor_server.sh
```

메뉴:

1. **실시간 로그** - 트레이딩 봇 로그 스트리밍
2. **컨테이너 상태** - 실행 중인 컨테이너 확인
3. **시스템 리소스** - CPU, 메모리, 디스크 사용량
4. **최근 에러 로그** - 에러 메시지 필터링
5. **컨테이너 재시작** - 빠른 재시작
6. **컨테이너 중지** - 안전한 종료
7. **컨테이너 시작** - 중지된 컨테이너 시작
8. **서버 SSH 접속** - 직접 터미널 접속
9. **종료** - 모니터링 종료

### 수동 명령어

```bash
# 서버 접속
ssh deploy@49.247.171.64
cd /home/deploy/bitcoin-trading-bot

# 로그 확인
docker compose logs -f              # 실시간 로그
docker compose logs --tail=100      # 최근 100줄

# 현재 적용 candidate 확인 (컨테이너에서 사용하는 설정)
cat analysis/selected_candidate.json

# 컨테이너 관리
docker compose ps                   # 상태 확인
docker compose restart              # 재시작
docker compose down                 # 중지
docker compose up -d                # 시작

# 리소스 확인
docker compose stats                # 리소스 사용량
docker compose top                  # 프로세스 확인
```

---

## 🔧 유용한 명령어

### 로그 관리

```bash
# 서버에서
cd /home/deploy/bitcoin-trading-bot

# 로그 파일 확인
ls -lh logs/

# 특정 날짜 로그
cat logs/trading_$(date +%Y%m%d).log

# 에러만 필터링
docker compose logs | grep -i error

# 로그 파일 정리 (3일 이상 된 로그 삭제)
find logs/ -name "*.log" -mtime +3 -delete
```

### 데이터베이스 관리

```bash
# DB 크기 확인
ls -lh upbit_bitcoin.db

# DB 백업
cp upbit_bitcoin.db upbit_bitcoin.db.backup_$(date +%Y%m%d)

# DB 다운로드 (로컬로)
scp deploy@49.247.171.64:/home/deploy/bitcoin-trading-bot/upbit_bitcoin.db ./
```

### Docker 이미지 관리

```bash
# 이미지 목록
docker images

# 사용하지 않는 이미지 삭제
docker image prune -a

# 전체 정리 (주의: 모든 중지된 컨테이너/이미지 삭제)
docker system prune -a
```

---

## ❗ 문제 해결

### 1. SSH 연결 실패

```bash
# 방화벽 확인
ping 49.247.171.64

# SSH 포트 확인
telnet 49.247.171.64 22

# SSH 키 재등록
ssh-copy-id deploy@49.247.171.64
```

### 2. Docker 권한 오류

```bash
# 서버에서
sudo usermod -aG docker $USER
# 재로그인 필요
exit
ssh deploy@49.247.171.64
```

### 3. 컨테이너가 시작되지 않음

```bash
# 로그 확인
docker compose logs

# .env 파일 확인
cat .env

# 이미지 재빌드
docker compose build --no-cache
docker compose up -d
```

### 4. 메모리 부족

```bash
# 리소스 제한 조정 (docker-compose.yml)
# limits.memory 값을 줄이기

# 또는 불필요한 컨테이너 중지
docker ps -a
docker stop <container_id>
```

### 5. 데이터베이스 오류

```bash
# DB 파일 권한 확인
ls -la upbit_bitcoin.db

# 권한 수정
chmod 644 upbit_bitcoin.db

# DB 재전송
scp upbit_bitcoin.db deploy@49.247.171.64:/home/deploy/bitcoin-trading-bot/
```

---

## 🔐 보안 설정

### 방화벽 설정 (선택)

```bash
# 서버에서 (root 권한 필요)
sudo ufw enable
sudo ufw allow 22/tcp    # SSH
sudo ufw status
```

### .env 파일 보안

```bash
# 권한 제한
chmod 600 .env

# 서버 .env 확인
ssh deploy@49.247.171.64 "cat /home/deploy/bitcoin-trading-bot/.env"
```

---

## 📝 일일 체크리스트

- [ ] 컨테이너 상태 확인: `docker compose ps`
- [ ] 로그 확인: `docker compose logs --tail=50`
- [ ] 에러 확인: `docker compose logs | grep -i error`
- [ ] 리소스 확인: `docker compose stats`
- [ ] 텔레그램 알림 확인

---

## 🆘 긴급 상황 대응

### 봇 즉시 중지

```bash
# 로컬에서
ssh deploy@49.247.171.64 "cd /home/deploy/bitcoin-trading-bot && docker compose down"

# 또는
./deployment/monitor_server.sh
# 메뉴에서 6번 선택
```

### 빠른 재시작

```bash
ssh deploy@49.247.171.64 "cd /home/deploy/bitcoin-trading-bot && docker compose restart"
```

---

## 📞 지원

- **모니터링**: `./deployment/monitor_server.sh`
- **로그**: `ssh deploy@49.247.171.64 'cd /home/deploy/bitcoin-trading-bot && docker compose logs -f'`
- **재배포**: `./deployment/deploy_to_server.sh`
