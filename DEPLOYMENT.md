# Deployment Guide (Native macOS)

This guide covers deploying the Jarvis OCR Service on macOS natively (for Apple Vision support).

## Quick Deployment

The simplest deployment workflow:

```bash
# 1. SSH into your macOS server
ssh user@your-macos-server

# 2. Navigate to project directory
cd /path/to/jarvis-ocr-server

# 3. Run deployment script (with automatic service startup)
./deploy.sh --start-services --enable-redis-queue

# Services will start automatically in the background
# Logs are in: logs/service.log and logs/worker.log
```

**Or deploy without starting services:**
```bash
./deploy.sh
# Then start manually or use launchd (see below)
```

## Deployment Script

The `deploy.sh` script automates:
- ✅ Git pull (latest code)
- ✅ Poetry dependency updates
- ✅ Graceful service shutdown
- ✅ Optional service startup in background

**Usage:**
```bash
./deploy.sh                              # Deploy only (don't start services)
./deploy.sh --start-services             # Deploy and start services in background
./deploy.sh --start-services --enable-redis-queue  # Include Redis queue
./deploy.sh --skip-deps                 # Skip Poetry install (faster)
```

**When using `--start-services`:**
- Services run in background (won't lock terminal)
- Logs written to `logs/service.log` and `logs/worker.log`
- PIDs saved to `logs/service.pid` and `logs/worker.pid`
- Services can be stopped with: `kill $(cat logs/service.pid)`

## Process Management Options

### Option 1: Manual (Screen/Tmux) - Simplest

Run services in screen/tmux sessions for easy access:

```bash
# Install screen (if needed)
brew install screen

# Start service in screen
screen -S ocr-service
./run.sh --enable-redis-queue
# Press Ctrl+A then D to detach

# Start worker in another screen
screen -S ocr-worker
./run-worker.sh
# Press Ctrl+A then D to detach

# Reattach later
screen -r ocr-service
screen -r ocr-worker
```

### Option 2: Launchd (macOS Native) - Recommended for Production

**Deploy (Recommended):**

```bash
./deploy-launchd.sh
```

This script will:
- Materialize plist templates with your project path and username
- Install services to `~/Library/LaunchAgents/`
- Reload and start both service and worker via modern launchctl commands
- Configure services to start on login (RunAtLoad) and auto-restart (KeepAlive)

Logs are written to `~/Library/Logs/jarvis-ocr/`.

**Useful launchd commands:**
```bash
# Check status
launchctl print gui/$(id -u)/com.jarvis.ocr.service
launchctl print gui/$(id -u)/com.jarvis.ocr.worker

# Force restart
launchctl kickstart -k gui/$(id -u)/com.jarvis.ocr.service
launchctl kickstart -k gui/$(id -u)/com.jarvis.ocr.worker

# Disable (stop and prevent auto-start)
launchctl bootout gui/$(id -u)/com.jarvis.ocr.service
launchctl bootout gui/$(id -u)/com.jarvis.ocr.worker
```

### Option 3: PM2 (Process Manager)

PM2 works great for Python services:

```bash
# Install PM2
npm install -g pm2

# Start services
pm2 start main.py --name ocr-service --interpreter poetry -- run python
pm2 start worker.py --name ocr-worker --interpreter poetry -- run python

# Save PM2 configuration
pm2 save
pm2 startup  # Follow instructions to enable auto-start
```

## Deployment Workflow

### Standard Deployment

1. **Push to GitHub:**
   ```bash
   git add .
   git commit -m "Deploy: description"
   git push origin main
   ```

2. **On Server - Deploy:**
   ```bash
   ./deploy.sh
   ```

3. **Restart Services:**
   - If using screen/tmux: Reattach and restart
   - If using launchd: `./deploy-launchd.sh` (or `launchctl kickstart -k gui/$(id -u)/com.jarvis.ocr.service`)
   - If using PM2: `pm2 restart ocr-service ocr-worker`

### Zero-Downtime Deployment (Advanced)

For zero-downtime, you can:

1. Run multiple worker instances
2. Deploy to a new directory
3. Switch traffic gradually
4. Or use a load balancer with health checks

## Environment Variables

Ensure your `.env` file is configured on the server:

```bash
# Copy .env.example to .env (if you have one)
cp .env.example .env

# Edit with your settings
nano .env
```

**Required variables:**
- `JARVIS_AUTH_BASE_URL` - Auth service URL
- `JARVIS_APP_ID` - App ID for authentication
- `JARVIS_APP_KEY` - App key for authentication
- `AWS_ACCESS_KEY_ID` - For S3/MinIO access
- `AWS_SECRET_ACCESS_KEY` - For S3/MinIO access
- `REDIS_HOST` - Redis host (default: localhost)
- `REDIS_PORT` - Redis port (default: 6379)

## Monitoring

### Health Checks

The service provides health endpoints:
- `GET /health` - Basic health check
- `GET /v1/queue/status` - Redis queue status

### Logs

**If using launchd:**
```bash
tail -f ~/Library/Logs/jarvis-ocr/service-out.log
tail -f ~/Library/Logs/jarvis-ocr/worker-out.log
```

**If using PM2:**
```bash
pm2 logs ocr-service
pm2 logs ocr-worker
```

**If using screen/tmux:**
- Logs appear in the terminal
- Or redirect to files: `./run.sh > logs/service.log 2>&1`

## Troubleshooting

### Service won't start
1. Check Poetry is installed: `poetry --version`
2. Check dependencies: `poetry install`
3. Check .env file exists and is configured
4. Check port is available: `lsof -i :7031`

### Worker not processing jobs
1. Check Redis is running: `redis-cli ping`
2. Check queue has jobs: `redis-cli LLEN jarvis.ocr.jobs`
3. Check worker logs for errors

### Apple Vision not working
1. Ensure running on macOS (not Linux)
2. Check `OCR_ENABLE_APPLE_VISION=true` in .env
3. Verify Vision framework is available

## Recommended Setup

For production, we recommend:

1. **Use launchd** for automatic startup and process management
2. **Set up log rotation** to prevent disk fill
3. **Monitor with health checks** (cron job or monitoring service)
4. **Use a reverse proxy** (nginx) if exposing to internet
5. **Set up backups** for Redis data (if using persistent storage)

## Quick Reference

```bash
# Deploy
./deploy.sh

# Start service
./run.sh --enable-redis-queue

# Start worker
./run-worker.sh

# Check if running
ps aux | grep "python.*main.py"
ps aux | grep "python.*worker.py"

# View logs (if redirected)
tail -f logs/service.log
tail -f logs/worker.log
```

