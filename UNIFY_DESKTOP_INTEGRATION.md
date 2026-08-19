# Unify Desktop Assistant + DSG ONE Integration

Complete desktop automation platform with AI-powered agent service and deterministic execution verification.

## Overview

The Unify Desktop Assistant (v1.1.0+dsg1) is a comprehensive Linux desktop automation suite that includes:

- **AI Agent Service**: Magnitude-based autonomous agent for desktop automation
- **DSG ONE Pre-Execution Gate**: Deterministic verification for all desktop actions
- **Trinity MCP Bridge**: Model Context Protocol server for DSG ONE integration
- **Remote Access Stack**: VNC server, noVNC web viewer, websockify proxy
- **System Tray GUI**: User control interface with service management
- **SFTP Sync**: File synchronization with remote systems

**Package Info:**
- Name: `unify-desktop-assistant`
- Version: `1.1.0+dsg1`
- Architecture: `amd64`
- Size: 68 MB (15 MB compressed)
- Maintainer: Unify AI <hello@unify.ai>

---

## Architecture

### Execution Pipeline

```
User Task
   ↓
Magnitude Planning System
   ↓
DSG ONE Pre-Execution Gate (/api/dsg/evaluate)
   ↓
Verification: Allow/Block Decision
   ↓
Desktop Action Execution (if approved)
   ↓
Local JSONL Audit Trail
```

### System Components

#### 1. Agent Service (`agent-service/`)
- **Framework**: Magnitude (browser automation)
- **Language**: TypeScript/Node.js
- **Port**: 3000
- **Endpoints**:
  - `/nav` - Navigation planning
  - `/act` - Action execution
  - `/execute-actions` - Batch execution
- **Integration**: DSG ONE verification gate
- **Audit**: Local JSONL evidence logging

#### 2. Magnitude Browser Engine (`magnitude/`)
- **Type**: Web automation and evaluation framework
- **Components**:
  - Core package: Browser control and task execution
  - Examples: Company management, todo list automation
  - Evals: WebVoyager, basic navigation tests
  - WebDriver integration for Chrome/Firefox
- **Size**: ~40 MB

#### 3. Trinity MCP Server (`trinity-mcp-server/`)
- **Protocol**: Model Context Protocol (stdio)
- **Binary**: `/usr/local/bin/trinity-dsg-mcp`
- **Configuration**: Sources `.env` for DSG ONE settings
- **Purpose**: Exposes desktop automation to MCP clients
- **API URL**: Points to `DSG_ONE_API_URL` when configured

#### 4. Remote Access Stack
- **VNC Server** (x11vnc)
  - Port: 5900
  - Service: `unify-vnc.service`
- **WebSocket Proxy** (websockify)
  - Port: 6080
  - Service: `unify-websockify.service`
- **noVNC Viewer**: Web-based VNC client
- **Use Case**: Remote desktop control

#### 5. System Tray GUI (`gui/`)
- **Application**: `unify-assistant.py`
- **Framework**: GTK+ 3 with AppIndicator
- **Features**:
  - Start/stop services
  - Configure API keys
  - View service status
  - Launch noVNC web viewer
- **Service**: `unify-tray.service`

#### 6. SFTP Synchronization
- **Primary Service**: `unify-sftp.service` (port 22)
- **Sync Service**: `unify-sftp-sync.service`
- **Purpose**: Bidirectional file sync with remote systems
- **Configuration**: Auto-configured during setup

---

## DSG ONE Integration

### Configuration

Located at: `/opt/unify-desktop-assistant/agent-service/.env`

```bash
# DSG ONE API endpoint (empty = gate disabled)
DSG_ONE_API_URL=

# Optional bearer token for authentication
DSG_ONE_TOKEN=

# Gate behavior:
#   enforce    - Block execution on verification failure
#   audit      - Allow if verifier unavailable
#   off        - Disable verification gate
DSG_GATE_MODE=enforce

# Profile for evaluation (default: balanced)
DSG_GATE_PROFILE=balanced

# Verification timeout (milliseconds)
DSG_GATE_TIMEOUT_MS=8000

# Local audit trail (JSONL format)
DSG_EVIDENCE_LOG=/var/log/unify/dsg-evidence.log
```

### Execution Flow

1. **User initiates task** via Agent Service
2. **Magnitude plans actions** (navigation, clicks, input)
3. **DSG ONE gate intercepts** each planned action
4. **Verification endpoint**: `POST /api/dsg/evaluate`
   ```json
   {
     "action": "click",
     "target": "button.submit",
     "context": "form_submission",
     "profile": "balanced"
   }
   ```
5. **Response**: `{ "allowed": true/false, "proof_hash": "..." }`
6. **Execution decision**: Proceed or block
7. **Evidence logged**: JSONL audit trail

### Verification Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| **enforce** | Block if verification fails | Production - strict compliance |
| **audit** | Allow if verifier unavailable | Graceful degradation |
| **off** | Skip verification | Development/testing |

---

## Installation & Setup

### Prerequisites

```bash
# System dependencies (automatically installed)
- bash, curl, ca-certificates, gnupg, git
- python3, python3-pip, python3-venv
- python3-gi, gir1.2-gtk-3.0
- x11vnc, wget, whiptail

# Recommended
- gir1.2-ayatanaappindicator3-0.1 (tray support)
- gdebi (package manager)
```

### Installation

```bash
# Option 1: Using gdebi (interactive)
sudo gdebi unifydesktopassistantdsgone_1.1.0dsg1_amd64.deb

# Option 2: Using dpkg + apt
sudo dpkg -i unifydesktopassistantdsgone_1.1.0dsg1_amd64.deb
sudo apt-get install -f  # Install missing dependencies

# Option 3: Using apt (if in repo)
sudo apt-get install unify-desktop-assistant
```

### Post-Installation Setup

```bash
# 1. Configure DSG ONE integration
sudo nano /opt/unify-desktop-assistant/agent-service/.env
# Edit DSG_ONE_API_URL, DSG_ONE_TOKEN, DSG_GATE_MODE

# 2. Enable and start services
sudo systemctl enable unify-tray.service
sudo systemctl enable unify-agent.service
sudo systemctl enable unify-vnc.service
sudo systemctl enable unify-websockify.service

# 3. Start tray icon (auto-starts other services)
sudo systemctl start unify-tray.service

# 4. Verify installation
sudo systemctl status unify-tray
sudo systemctl status unify-agent

# 5. Access tray icon
# Look for Unify icon in system tray
```

---

## Services Management

### Available Services

```bash
# System tray interface (GUI)
sudo systemctl start|stop|restart|status unify-tray.service

# Agent service (core automation)
sudo systemctl start|stop|restart|status unify-agent.service

# VNC server (remote desktop)
sudo systemctl start|stop|restart|status unify-vnc.service

# WebSocket proxy (web VNC)
sudo systemctl start|stop|restart|status unify-websockify.service

# SFTP server (file sync)
sudo systemctl start|stop|restart|status unify-sftp.service
sudo systemctl start|stop|restart|status unify-sftp-sync.service
```

### Ports

| Service | Port | Protocol | Purpose |
|---------|------|----------|---------|
| Agent Service | 3000 | HTTP | Task automation API |
| VNC Server | 5900 | VNC | Remote desktop |
| WebSocket Proxy | 6080 | WebSocket | noVNC web viewer |
| SFTP Server | 22 | SFTP | File synchronization |

### Logs

```bash
# Tray GUI logs
journalctl -u unify-tray.service -f

# Agent service logs
journalctl -u unify-agent.service -f

# DSG ONE verification logs
tail -f /var/log/unify/dsg-evidence.log

# System logs
/opt/unify-desktop-assistant/logs/
```

---

## API Endpoints

### Agent Service (Port 3000)

#### POST /nav
Navigation planning endpoint

```bash
curl -X POST http://localhost:3000/nav \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "task": "Submit contact form"
  }'
```

Response:
```json
{
  "plan": [
    { "action": "navigate", "target": "https://example.com" },
    { "action": "fill", "selector": "input[name=name]", "value": "John Doe" },
    { "action": "click", "selector": "button[type=submit]" }
  ],
  "estimated_duration_ms": 5000
}
```

#### POST /act
Execute single action

```bash
curl -X POST http://localhost:3000/act \
  -H "Content-Type: application/json" \
  -d '{
    "action": "click",
    "selector": "button.submit",
    "context": "form_submission"
  }'
```

#### POST /execute-actions
Batch action execution

```bash
curl -X POST http://localhost:3000/execute-actions \
  -H "Content-Type: application/json" \
  -d '{
    "actions": [
      { "action": "click", "selector": ".menu" },
      { "action": "type", "selector": "input", "text": "search term" },
      { "action": "click", "selector": "button[type=submit]" }
    ]
  }'
```

### DSG ONE Gate Integration

#### POST /api/dsg/evaluate
Pre-execution verification

**Request:**
```json
{
  "action": "click",
  "target": "button.submit",
  "context": "form_submission",
  "profile": "balanced"
}
```

**Response (Allowed):**
```json
{
  "allowed": true,
  "proof_hash": "sha256:abc123...",
  "audit_event_id": "evt_12345",
  "confidence": 0.99
}
```

**Response (Blocked):**
```json
{
  "allowed": false,
  "reason": "Action violates security policy",
  "policy_rule": "no_submit_forms_with_sensitive_fields",
  "audit_event_id": "evt_12346"
}
```

---

## Trinity MCP Integration

### Running the MCP Server

```bash
# Start Trinity MCP server
/usr/local/bin/trinity-dsg-mcp

# Or as a background service
nohup /usr/local/bin/trinity-dsg-mcp > /var/log/trinity-mcp.log 2>&1 &

# With custom config
DSG_ONE_API_URL=https://dsg.example.com /usr/local/bin/trinity-dsg-mcp
```

### Using with Claude

```bash
# In Claude MCP configuration
{
  "mcpServers": {
    "trinity-dsg": {
      "command": "/usr/local/bin/trinity-dsg-mcp",
      "env": {
        "DSG_ONE_API_URL": "https://dsg.example.com",
        "DSG_ONE_TOKEN": "your-token"
      }
    }
  }
}
```

### Available MCP Tools

- `desktop.navigate(url)` - Navigate to URL
- `desktop.click(selector)` - Click element
- `desktop.type(selector, text)` - Type text
- `desktop.screenshot()` - Take screenshot
- `desktop.wait(ms)` - Wait
- `desktop.evaluate(action)` - Pre-execution verification

---

## Configuration

### Environment Variables

```bash
# DSG ONE Integration
DSG_ONE_API_URL=https://dsg-cinema.example.com
DSG_ONE_TOKEN=bearer_token_here
DSG_GATE_MODE=enforce  # enforce|audit|off
DSG_GATE_PROFILE=balanced
DSG_GATE_TIMEOUT_MS=8000

# Unify Service URLs
ORCHESTRA_URL=https://api.unify.ai/v0
UNITY_COMMS_URL=https://unity-comms-app.run.app

# VNC Configuration
VNC_PORT=5900
VNC_PASSWD_ENCRYPTED=...

# SFTP Configuration
SFTP_PORT=22
SFTP_AUTHORIZED_KEYS_PATH=~/.ssh/authorized_keys

# Logging
DSG_EVIDENCE_LOG=/var/log/unify/dsg-evidence.log
LOG_LEVEL=INFO
```

### Configuration Files

```
/opt/unify-desktop-assistant/
├── agent-service/.env              # Agent configuration
├── environment.conf                 # Default environment
├── systemd/*.service               # Service definitions
├── gui/unify-assistant.py          # Tray application
└── trinity-mcp-server/config.json  # MCP configuration
```

---

## Troubleshooting

### Services Won't Start

```bash
# Check service status
sudo systemctl status unify-agent.service

# View error logs
journalctl -u unify-agent.service -n 50 --no-pager

# Verify configuration
sudo cat /opt/unify-desktop-assistant/agent-service/.env

# Check dependencies
dpkg -l | grep -E "python3|curl|gnupg"
```

### DSG ONE Verification Failing

```bash
# Test connectivity to DSG ONE endpoint
curl -v -X POST $DSG_ONE_API_URL/api/dsg/evaluate \
  -H "Content-Type: application/json" \
  -d '{"action": "test"}'

# Verify API token
echo "Token: $DSG_ONE_TOKEN"

# Check gate mode
grep DSG_GATE_MODE /opt/unify-desktop-assistant/agent-service/.env

# Switch to audit mode for debugging
sudo sed -i 's/DSG_GATE_MODE=.*/DSG_GATE_MODE=audit/' \
  /opt/unify-desktop-assistant/agent-service/.env
```

### Logs Not Appearing

```bash
# Check log directory permissions
sudo ls -la /var/log/unify/

# Create if missing
sudo mkdir -p /var/log/unify
sudo chown unify:unify /var/log/unify

# Verify log file creation
sudo touch /var/log/unify/dsg-evidence.log
sudo chown unify:unify /var/log/unify/dsg-evidence.log

# Check journal logs
journalctl -xe | tail -50
```

### Remote Access Not Working

```bash
# Test VNC port
nc -zv localhost 5900

# Test WebSocket port
curl -v http://localhost:6080/websockify

# Check firewall rules
sudo ufw status
sudo ufw allow 5900/tcp
sudo ufw allow 6080/tcp

# Verify display configuration
echo $DISPLAY
ps aux | grep Xvfb
```

---

## Integration with DSG Cinema Proof Agent

### Combined Architecture

```
User Request (DSG Cinema API)
   ↓
Z3 Solver Verification (z3_main.py)
   ↓
DSG ONE Gate Service (dsg-z3-solver)
   ↓
Desktop Agent (Unify Agent Service)
   ↓
Magnitude Browser Automation
   ↓
Desktop Action Execution
   ↓
Audit Trail (DSG + Unify)
```

### Configuration for Integration

```bash
# 1. Deploy DSG Cinema proof agent
# Point Unify agent to DSG ONE endpoint:
DSG_ONE_API_URL=http://dsg-z3-solver:8080

# 2. Configure verification
DSG_GATE_MODE=enforce
DSG_GATE_PROFILE=balanced

# 3. Enable audit trail
DSG_EVIDENCE_LOG=/var/log/unify/dsg-evidence.jsonl

# 4. Setup MCP integration
# Link Trinity MCP to Claude Code for AI-assisted desktop automation
```

---

## Performance Metrics

### Resource Usage

| Component | CPU | Memory | Disk |
|-----------|-----|--------|------|
| Agent Service | 5-15% | 100-200 MB | 1 GB |
| VNC Server | 2-10% | 50-100 MB | 100 MB |
| Browser Engine | 20-40% | 300-500 MB | 2 GB |
| Trinity MCP | 1-5% | 30-50 MB | 50 MB |
| **Total** | **30-70%** | **500-900 MB** | **3.2 GB** |

### Latency

- Navigation planning: 200-500 ms
- DSG ONE verification: 100-500 ms (gate)
- Action execution: 500-2000 ms (depending on action)
- Total pipeline: 800-3000 ms

---

## Security Considerations

### Authentication

```bash
# Generate API token for DSG ONE
DSG_ONE_TOKEN=$(openssl rand -hex 32)
export DSG_ONE_TOKEN

# Protect configuration file
sudo chmod 600 /opt/unify-desktop-assistant/agent-service/.env
sudo chown unify:unify /opt/unify-desktop-assistant/agent-service/.env
```

### Network Security

```bash
# Restrict VNC to localhost only
# Edit systemd service or iptables rules
sudo iptables -A INPUT -p tcp --dport 5900 -s 127.0.0.1 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 5900 -j DROP
```

### Audit Compliance

```bash
# Enable comprehensive audit trail
DSG_GATE_MODE=enforce

# Verify all actions logged
tail -f /var/log/unify/dsg-evidence.log

# Archive logs for compliance
tar -czf dsg-evidence-$(date +%Y%m%d).tar.gz /var/log/unify/
```

---

## References

- [Unify AI Documentation](https://unify.ai/)
- [Magnitude Framework](https://github.com/unify-ai/magnitude)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [DSG Cinema Proof Agent](./README.md)
- [Monitoring Setup](./MONITORING_SETUP.md)
