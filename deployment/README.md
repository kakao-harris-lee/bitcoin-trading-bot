# 📦 배포 가이드

Bitcoin Trading Bot을 새로운 서버(49.247.171.64)에 Docker Compose로 배포하는 가이드입니다.

---

## 🖥️ 서버 정보

- **서버 주소**: 49.247.171.64
- **SSH 접속**: `ssh deploy@49.247.171.64`
- **배포 경로**: `/home/deploy/bitcoin-trading-bot`
- **배포 방식**: Docker Compose

---

## 📁 파일 목록

| 파일 | 설명 |
|------|------|
| `SERVER_DEPLOYMENT.md` | 완전한 서버 배포 가이드 (상세) |
| `deploy_to_server.sh` | 서버 자동 배포 스크립트 |
| `monitor_server.sh` | 서버 모니터링 도구 |
| `deploy_docker.sh` | 로컬 Docker Compose 실행 |
| `_deprecated_aws/` | AWS EC2 관련 구 파일들 (사용 안 함) |

---

## 🚀 빠른 시작

### 1. 서버로 배포

```bash
cd deployment

# 실행 권한 확인
chmod +x deploy_to_server.sh monitor_server.sh

# 서버로 배포
./deploy_to_server.sh
```

### 2. 모니터링

```bash
./monitor_server.sh
```

인터랙티브 메뉴:

- 1: 실시간 로그
- 2: 컨테이너 상태
- 3: 시스템 리소스
- 4: 최근 에러 로그
- 5: 컨테이너 재시작
- 6: 컨테이너 중지
- 7: 컨테이너 시작
- 8: 서버 SSH 접속
- 9: 종료

---

## 📖 상세 가이드

완전한 배포 가이드는 [`SERVER_DEPLOYMENT.md`](./SERVER_DEPLOYMENT.md)를 참고하세요.

### 주요 내용

- ✅ SSH 키 설정
- ✅ Docker 설치
- ✅ 자동/수동 배포 방법
- ✅ 모니터링 및 관리
- ✅ 문제 해결
- ✅ 보안 설정

---

## 🛠️ 로컬 Docker 테스트

서버 배포 전에 로컬에서 테스트:

```bash
# 로컬 Docker Compose 실행
./deploy_docker.sh start

# 로그 확인
./deploy_docker.sh logs

# 중지
./deploy_docker.sh stop
cd bitcoin-trading-bot/deployment
chmod +x setup_ec2.sh
./setup_ec2.sh

# 3. .env 파일 생성
nano ~/bitcoin-trading-bot/.env
# 내용 입력 후 저장

# 4. systemd 서비스 설정
sudo cp bitcoin-trading-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bitcoin-trading-bot
sudo systemctl start bitcoin-trading-bot

# 5. 상태 확인
sudo systemctl status bitcoin-trading-bot
```

---

## 🔍 트러블슈팅

### 서비스가 시작되지 않을 때

```bash
# 로그 확인
sudo journalctl -u bitcoin-trading-bot -n 50

# 수동 실행으로 에러 확인
cd ~/bitcoin-trading-bot/live_trading
source ../venv/bin/activate
python main.py --once
```

### TA-Lib 오류

```bash
# TA-Lib 재설치
cd /tmp
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib/
./configure --prefix=/usr
make
sudo make install
sudo ldconfig
```

### 메모리 부족

```bash
# 스왑 추가
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 📊 유용한 명령어

### 로컬에서

```bash
# SSH 접속
ssh -i <KEY_FILE> ubuntu@<EC2_IP>

# 로그 실시간 보기
ssh -i <KEY_FILE> ubuntu@<EC2_IP> "tail -f ~/bitcoin-trading-bot/logs/trading.log"

# 서비스 재시작
ssh -i <KEY_FILE> ubuntu@<EC2_IP> "sudo systemctl restart bitcoin-trading-bot"
```

### EC2에서

```bash
# 서비스 관리
sudo systemctl status bitcoin-trading-bot
sudo systemctl restart bitcoin-trading-bot
sudo systemctl stop bitcoin-trading-bot
sudo systemctl start bitcoin-trading-bot

# 로그 확인
tail -f ~/bitcoin-trading-bot/logs/trading.log
tail -f ~/bitcoin-trading-bot/logs/error.log
sudo journalctl -u bitcoin-trading-bot -f

# 연결 테스트
cd ~/bitcoin-trading-bot/live_trading
source ../venv/bin/activate
python test_connection.py

# 수동 실행 (테스트)
python main.py --once
```

---

## 💡 팁

### 백그라운드 실행 (screen/tmux 대신 systemd 사용)

systemd를 사용하면:

- ✅ 자동 재시작
- ✅ 부팅 시 자동 시작
- ✅ 로그 관리
- ✅ 리소스 제한

따라서 screen이나 tmux 불필요!

### 로그 관리

```bash
# 로그 크기 확인
du -sh ~/bitcoin-trading-bot/logs/

# 오래된 로그 삭제
find ~/bitcoin-trading-bot/logs/ -name "*.log.*" -mtime +30 -delete
```

### 정기 점검

```bash
# cron으로 매일 오전 8시 점검 (선택)
crontab -e

# 추가:
0 8 * * * /home/ubuntu/bitcoin-trading-bot/deployment/health_check.sh
```

---

## 🔐 보안 체크리스트

- [ ] SSH 키 파일 권한 400
- [ ] .env 파일 권한 600
- [ ] 업비트 API 키 권한 최소화 (조회, 거래만)
- [ ] EC2 보안 그룹에서 SSH만 허용
- [ ] Fail2Ban 설치 및 활성화
- [ ] 정기적인 API 키 재발급 (분기별)
- [ ] 로그 정기 확인

---

## 📞 지원

문제가 발생하면:

1. [`AWS_EC2_DEPLOYMENT.md`](./AWS_EC2_DEPLOYMENT.md)의 문제 해결 섹션 확인
2. 로그 확인
3. 텔레그램 에러 메시지 확인
4. 서비스 재시작

---

**다음:** [상세 배포 가이드](./AWS_EC2_DEPLOYMENT.md)
