# Deployment Guide

## Server Info

- **Server**: chsvr.duckdns.org
- **SSH**: `ssh deploy@chsvr.duckdns.org`
- **Path**: `/home/deploy/bitcoin-trading-bot`

## Quick Start

```bash
# Deploy to server
./deployment/deploy_to_server.sh
```

## Commands

```bash
# SSH to server
ssh deploy@chsvr.duckdns.org

# Start bot
./bot.sh start live h4_conservative h4_short bear_only

# Check status
./bot.sh status

# View logs
./bot.sh logs

# Stop
./bot.sh stop
```

## Troubleshooting

```bash
# Check logs
tail -f logs/trading.log

# Restart service
./bot.sh stop && ./bot.sh start live
```
