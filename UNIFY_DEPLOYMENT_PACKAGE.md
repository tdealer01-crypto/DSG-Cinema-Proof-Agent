# Unify Desktop Assistant Deployment Package

Complete deployment guide for integrating Unify Desktop Assistant with DSG Cinema Proof Agent.

## Package Contents

**File:** `unifydesktopassistantdsgone_1.1.0dsg1_amd64.deb`
- **Size:** 15 MB compressed (68 MB extracted)
- **Architecture:** amd64 (64-bit Linux)
- **Version:** 1.1.0+dsg1
- **Build Date:** August 15, 2026

### Components

```
68 MB total
├── Agent Service (30 MB)
│   ├── Node.js runtime
│   ├── Magnitude browser engine
│   └── DSG ONE verification gate
├── Magnitude Framework (25 MB)
│   ├── Core automation engine
│   ├── WebDriver integration
│   ├── Example sites and tests
│   └── Evaluation frameworks
├── Trinity MCP Server (8 MB)
│   ├── Model Context Protocol bridge
│   ├── DSG ONE integration
│   └── Configuration tools
├── GUI & Utilities (3 MB)
│   ├── System tray application
│   ├── SFTP sync tools
│   └── Setup utilities
└── systemd Services & Docs (2 MB)
    ├── 5 systemd service files
    ├── Configuration templates
    └── Integration documentation
```

---

## Quick Start

### 1. Download Package

```bash
# From upload location
wget https://your-server.com/unifydesktopassistantdsgone_1.1.0dsg1_amd64.deb

# Or use local file from uploads
cp unifydesktopassistantdsgone_1.1.0dsg1_amd64.deb /tmp/
```

### 2. Install

```bash
# Option A: Interactive installation (recommended)
sudo gdebi /tmp/unifydesktopassistantdsgone_1.1.0dsg1_amd64.deb

# Option B: Command-line installation
sudo apt-get update
sudo dpkg -i /tmp/unifydesktopassistantdsgone_1.1.0dsg1_amd64.deb
sudo apt-get install -f  # Install dependencies

# Option C: Verify package before installing
ar t unifydesktopassistantdsgone_1.1.0dsg1_amd64.deb
```

### 3. Configure

```bash
# Edit configuration
sudo nano /opt/unify-desktop-assistant/agent-service/.env

# Set DSG ONE endpoint
export DSG_ONE_API_URL=http://z3-solver-service:8080
export DSG_ONE_TOKEN=your-bearer-token-here
export DSG_GATE_MODE=enforce
```

### 4. Start Services

```bash
# Enable auto-start
sudo systemctl enable unify-tray.service
sudo systemctl enable unify-agent.service

# Start services
sudo systemctl start unify-tray.service
sudo systemctl start unify-agent.service

# Verify
sudo systemctl status unify-agent.service
```

### 5. Verify Installation

```bash
# Check agent service
curl http://localhost:3000/status

# Check VNC (should respond)
nc -zv localhost 5900 && echo "VNC ready"

# Check logs
sudo journalctl -u unify-agent.service -n 20
```

---

## System Requirements

### Minimum Specifications

| Component | Requirement |
|-----------|-------------|
| OS | Ubuntu 20.04 LTS or newer |
| CPU | 2+ cores (4+ recommended) |
| RAM | 4 GB (8 GB recommended) |
| Disk | 5 GB available |
| Network | Internet connectivity |

### Ubuntu Package Dependencies

```bash
# Core dependencies (auto-installed by apt)
bash curl ca-certificates gnupg git
python3 python3-pip python3-venv
python3-gi gir1.2-gtk-3.0
x11vnc wget whiptail

# Optional recommendations
gir1.2-ayatanaappindicator3-0.1
gdebi

# Verify installation
dpkg -l | grep -E "python3|curl|gnupg|x11vnc"
```

### Internet Connectivity

- **Required for**: Package installation, DSG ONE API calls
- **Ports needed**: 80 (HTTP), 443 (HTTPS)
- **DSG ONE endpoint**: Configurable via environment variable

---

## Installation Methods

### Method 1: Interactive (Recommended)

```bash
# Using gdebi (GUI + auto-dependencies)
sudo gdebi /tmp/unifydesktopassistantdsgone_1.1.0dsg1_amd64.deb

# Follow prompts:
# 1. Review package details
# 2. Click Install
# 3. Enter password
# 4. Wait for completion
```

### Method 2: Command-Line (Automated)

```bash
#!/bin/bash
set -e

echo "Installing Unify Desktop Assistant..."

# Update package lists
sudo apt-get update -qq

# Install package
sudo dpkg -i unifydesktopassistantdsgone_1.1.0dsg1_amd64.deb

# Install missing dependencies
sudo apt-get install -y -f

# Enable services
sudo systemctl enable unify-tray.service
sudo systemctl enable unify-agent.service
sudo systemctl enable unify-vnc.service

# Start services
sudo systemctl start unify-tray.service

echo "✓ Installation complete"
echo "Services: unify-tray, unify-agent, unify-vnc, unify-websockify"
echo "Agent API: http://localhost:3000"
echo "VNC: localhost:5900"
echo "Web VNC: http://localhost:6080/vnc.html"
```

### Method 3: Docker Container

```dockerfile
FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    curl gnupg ca-certificates \
    python3 python3-pip python3-venv \
    python3-gi gir1.2-gtk-3.0 \
    x11vnc wget whiptail git

# Copy package
COPY unifydesktopassistantdsgone_1.1.0dsg1_amd64.deb /tmp/

# Install package
RUN dpkg -i /tmp/unifydesktopassistantdsgone_1.1.0dsg1_amd64.deb && \
    apt-get install -f -y

# Configure DSG ONE
ENV DSG_ONE_API_URL=http://dsg-z3-solver:8080
ENV DSG_GATE_MODE=enforce

# Expose ports
EXPOSE 3000 5900 6080 22

# Start tray service
CMD ["systemctl", "start", "unify-tray.service"]
```

### Method 4: Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: unify-desktop-agent
spec:
  replicas: 3
  selector:
    matchLabels:
      app: unify-agent
  template:
    metadata:
      labels:
        app: unify-agent
    spec:
      containers:
      - name: agent
        image: your-registry/unify-desktop-agent:1.1.0
        ports:
        - containerPort: 3000
          name: agent
        - containerPort: 5900
          name: vnc
        - containerPort: 6080
          name: websocket
        env:
        - name: DSG_ONE_API_URL
          valueFrom:
            configMapKeyRef:
              name: dsg-config
              key: api-url
        - name: DSG_GATE_MODE
          value: "enforce"
        - name: DSG_GATE_PROFILE
          value: "balanced"
        resources:
          requests:
            memory: "500Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "2000m"

---
apiVersion: v1
kind: Service
metadata:
  name: unify-agent
spec:
  selector:
    app: unify-agent
  ports:
  - port: 3000
    name: agent
  - port: 5900
    name: vnc
  - port: 6080
    name: websocket
  type: LoadBalancer
```

---

## Post-Installation Configuration

### 1. DSG ONE Integration Setup

```bash
# Edit configuration file
sudo nano /opt/unify-desktop-assistant/agent-service/.env

# Configure these values:
DSG_ONE_API_URL=https://dsg-cinema.example.com
DSG_ONE_TOKEN=your-api-token
DSG_GATE_MODE=enforce
DSG_GATE_PROFILE=balanced
DSG_GATE_TIMEOUT_MS=8000
```

### 2. Enable Logging

```bash
# Create log directory
sudo mkdir -p /var/log/unify
sudo chown unify:unify /var/log/unify

# Enable logging in configuration
echo "DSG_EVIDENCE_LOG=/var/log/unify/dsg-evidence.log" | \
  sudo tee -a /opt/unify-desktop-assistant/agent-service/.env
```

### 3. Setup Remote Access

```bash
# Generate VNC password (optional but recommended)
vncpasswd -f > /tmp/vnc-pass
sudo cat /tmp/vnc-pass | \
  sudo tee /opt/unify-desktop-assistant/vnc-password.encrypted

# Configure WebSocket proxy for remote access
# Already configured in unify-websockify.service
```

### 4. Enable Trinity MCP

```bash
# Test MCP server
/usr/local/bin/trinity-dsg-mcp --version

# Start as background service
sudo systemctl start trinity-mcp.service

# Or run in foreground for debugging
DSG_ONE_API_URL=http://dsg-z3-solver:8080 /usr/local/bin/trinity-dsg-mcp
```

---

## Integration with DSG Cinema Proof Agent

### Architecture Diagram

```
┌─────────────────────────────────────────────┐
│    Claude Code / MCP Client                 │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
         ┌─────────────────────┐
         │  Trinity MCP Server │
         │ /usr/local/bin/     │
         │  trinity-dsg-mcp    │
         └──────────┬──────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │  DSG ONE Gate       │
         │ /api/dsg/evaluate   │
         └──────────┬──────────┘
                    │
                    ▼
    ┌────────────────────────────────┐
    │ Z3 Solver Service (z3_main.py) │
    │ Verification & Proof Generation │
    └────────────────────┬───────────┘
                         │
         Allow/Deny ◄────┘
                    │
                    ▼
    ┌─────────────────────────────────┐
    │  Unify Agent Service            │
    │  Desktop Automation             │
    │  POST /nav, /act, /execute-     │
    │  actions                        │
    └────────────────┬────────────────┘
                     │
                     ▼
    ┌─────────────────────────────────┐
    │  Magnitude Browser Engine       │
    │  Web Automation & Navigation    │
    └────────────────┬────────────────┘
                     │
                     ▼
    ┌─────────────────────────────────┐
    │  Desktop / Web Actions          │
    │  Click, Type, Navigate, Submit  │
    └─────────────────────────────────┘
```

### Configuration Integration

```bash
# 1. Deploy DSG Z3 Solver Service (from PR #28)
# This provides /api/dsg/evaluate endpoint

# 2. Configure Unify agent to point to DSG ONE
sudo tee -a /opt/unify-desktop-assistant/agent-service/.env <<EOF
DSG_ONE_API_URL=http://z3-solver-service:8080
DSG_ONE_TOKEN=$(openssl rand -hex 32)
DSG_GATE_MODE=enforce
DSG_GATE_PROFILE=balanced
EOF

# 3. Configure Trinity MCP in Claude Code settings
# MCP Server: /usr/local/bin/trinity-dsg-mcp
# Environment variables: DSG_ONE_API_URL, DSG_ONE_TOKEN

# 4. Verify end-to-end connectivity
curl -X POST http://localhost:3000/nav \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "task": "test"}'
```

---

## Deployment Checklist

```bash
# Pre-deployment
☐ Download/upload .deb package
☐ Verify system has 5+ GB free disk space
☐ Confirm Ubuntu 20.04+ running
☐ Check internet connectivity

# Installation
☐ Run installation command
☐ Verify all dependencies installed
☐ Check package extracted to /opt/unify-desktop-assistant

# Configuration
☐ Edit .env file with DSG ONE API URL
☐ Set DSG_ONE_TOKEN (bearer token)
☐ Configure DSG_GATE_MODE=enforce
☐ Create /var/log/unify directory

# Service Startup
☐ Enable unify-tray.service
☐ Enable unify-agent.service
☐ Start services with systemctl
☐ Verify no startup errors in journal

# Verification
☐ Agent API responds on :3000
☐ VNC server listening on :5900
☐ WebSocket proxy on :6080
☐ DSG ONE gate connectivity working
☐ Logs being generated

# Integration
☐ Trinity MCP server running
☐ Claude Code configured for MCP
☐ End-to-end test passing
☐ Desktop automation working

# Documentation
☐ Record configuration values
☐ Document any custom changes
☐ Setup monitoring/alerting
☐ Plan backup strategy
```

---

## Troubleshooting

### Package Installation Issues

```bash
# Error: "Broken packages" or dependency errors
sudo apt-get install -f
sudo apt-get update
sudo dpkg --configure -a

# Error: Package not found
ls -lh /tmp/*.deb
dpkg -l | grep unify

# Error: Already installed
sudo apt-get remove unify-desktop-assistant
sudo apt-get autoremove
# Then reinstall
```

### Service Won't Start

```bash
# Check systemd status
sudo systemctl status unify-agent.service
sudo systemctl status unify-tray.service

# View detailed logs
journalctl -u unify-agent.service -n 100 --no-pager

# Manually test agent startup
cd /opt/unify-desktop-assistant/agent-service
node src/index.js

# Check dependencies
npm ls
python3 --version
```

### DSG ONE Gate Not Working

```bash
# Test endpoint connectivity
curl -v http://z3-solver-service:8080/health

# Check configuration
grep DSG_ONE /opt/unify-desktop-assistant/agent-service/.env

# Test verification endpoint
curl -X POST http://z3-solver-service:8080/solve \
  -H "Authorization: Bearer $DSG_ONE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"request_id": "test", "problem_type": "qubo"}'
```

### Remote Access Issues

```bash
# VNC not accessible
sudo netstat -tulpn | grep 5900
sudo ufw status
sudo ufw allow 5900/tcp

# WebSocket not responding
curl http://localhost:6080/websockify
sudo systemctl restart unify-websockify.service

# X11 display issues
echo $DISPLAY
Xvfb :99 -screen 0 1024x768x24 &
export DISPLAY=:99
```

---

## Performance Optimization

### Reduce Memory Usage

```bash
# Limit browser cache
export BROWSER_CACHE_SIZE=100m

# Reduce worker threads
export WORKER_THREADS=2

# Disable VNC if not needed
sudo systemctl disable unify-vnc.service
sudo systemctl stop unify-vnc.service
```

### Improve Performance

```bash
# Enable caching
export CACHE_ENABLED=true
export CACHE_TTL=3600

# Increase timeouts for slow networks
export DSG_GATE_TIMEOUT_MS=15000

# Enable connection pooling
export HTTP_POOL_SIZE=10
```

---

## Uninstallation

```bash
# Complete removal
sudo apt-get remove --purge unify-desktop-assistant

# Also remove logs
sudo rm -rf /var/log/unify/
sudo rm -rf /opt/unify-desktop-assistant/

# Clean up apt cache
sudo apt-get autoremove
sudo apt-get autoclean
```

---

## Support & Resources

- **Official Docs**: https://unify.ai/docs
- **Repository**: https://github.com/unify-ai/magnitude
- **MCP Protocol**: https://modelcontextprotocol.io
- **Issues**: https://github.com/unify-ai/unify-desktop/issues

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.1.0+dsg1 | 2026-08-15 | DSG ONE integration, Trinity MCP bridge |
| 1.1.0 | 2026-08-01 | Magnitude v2 engine, performance optimizations |
| 1.0.5 | 2026-07-15 | Stability fixes, Ubuntu 24.04 support |
| 1.0.0 | 2026-06-30 | Initial release |

---

## License

Unify Desktop Assistant: Licensed under Unify AI Terms
DSG ONE Integration: Custom deployment for DSG Cinema Proof Agent

See package documentation for complete license information.
