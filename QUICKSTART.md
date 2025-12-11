# 🚀 서버 배포 빠른 시작 가이드

## 1단계: SSH 키 설정

```bash
# SSH 키가 없다면 생성
ssh-keygen -t rsa -b 4096

# 서버에 키 등록
ssh-copy-id deploy@49.247.171.64

# 연결 테스트
ssh deploy@49.247.171.64
```

## 2단계: 환경 변수 설정

```bash
# .env 파일 생성
cp .env.example .env

# .env 파일 수정 (필수 값 입력)
nano .env
```

필수 입력 항목:

- `UPBIT_ACCESS_KEY`: Upbit API 키
- `UPBIT_SECRET_KEY`: Upbit Secret 키
- `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰
- `TELEGRAM_CHAT_ID`: 텔레그램 채팅 ID
- `AUTO_TRADE`: False (알림만) 또는 True (자동 거래)

## 3단계: 서버로 배포

```bash
cd deployment
./deploy_to_server.sh
```

자동으로:

- ✅ 파일 전송
- ✅ Docker 설치 (필요시)
- ✅ 컨테이너 빌드 및 실행

## 4단계: 모니터링

```bash
./monitor_server.sh
```

메뉴:

1. 실시간 로그
2. 컨테이너 상태
3. 시스템 리소스
4. 에러 로그 확인

## 주요 명령어

```bash
# 서버 접속
ssh deploy@49.247.171.64
cd /home/deploy/bitcoin-trading-bot

# 로그 확인
docker compose logs -f

# 재시작
docker compose restart

# 중지
docker compose down

# 시작
docker compose up -d
```

## 문제 해결

### SSH 연결 실패

```bash
ssh-copy-id deploy@49.247.171.64
```

### 컨테이너 시작 실패

```bash
# 서버에서
docker compose logs
docker compose build --no-cache
docker compose up -d
```

### .env 파일 확인

```bash
ssh deploy@49.247.171.64 "cat /home/deploy/bitcoin-trading-bot/.env"
```

## 상세 문서

- **전체 가이드**: `deployment/SERVER_DEPLOYMENT.md`
- **Docker 로컬 테스트**: `deployment/deploy_docker.sh`
- **문제 해결**: `deployment/SERVER_DEPLOYMENT.md` 참고
