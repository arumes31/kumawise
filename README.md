<p align="center">
  <img src="docs/logo.svg" alt="KumaWise Logo" width="400">
</p>

<p align="center">
  <a href="https://github.com/arumes31/kumawise/actions/workflows/docker-build.yml">
    <img src="https://github.com/arumes31/kumawise/actions/workflows/docker-build.yml/badge.svg" alt="Build Status">
  </a>
  <a href="https://github.com/arumes31/kumawise/actions/workflows/security-scan.yml">
    <img src="https://github.com/arumes31/kumawise/actions/workflows/security-scan.yml/badge.svg" alt="Security Scan">
  </a>
  <a href="https://github.com/arumes31/kumawise/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/arumes31/kumawise" alt="License">
  </a>
  <img src="https://img.shields.io/badge/python-3.14-blue.svg" alt="Python 3.14">
</p>

# KumaWise Proxy

A lightweight middleware webhook receiver that bridges **Uptime Kuma** alerts to **ConnectWise Manage** tickets.

## Features

- **Webhook Listener:** Receives alerts from Uptime Kuma.
- **Auto-Ticketing:** Creates a ticket in ConnectWise when a monitor goes DOWN.
- **Auto-Resolution:** Closes the corresponding ticket when the monitor comes back UP.
- **Smart Parsing:** Extracts Company ID from monitor names (e.g., `My Server #CW123`) to assign tickets to the correct company.
- **Deduplication:** Prevents duplicate tickets for the same downtime event.

## Configuration

The application is configured via environment variables.

| Variable | Description | Required | Default |
|----------|-------------|:--------:|---------|
| `CW_URL` | ConnectWise API Base URL | No | `https://api-na.myconnectwise.net/v4_6_release/apis/3.0` |
| `CW_COMPANY` | Your ConnectWise Company ID | Yes | - |
| `CW_PUBLIC_KEY` | API Public Key | Yes | - |
| `CW_PRIVATE_KEY` | API Private Key | Yes | - |
| `CW_CLIENT_ID` | Client ID | Yes | - |
| `CW_SERVICE_BOARD` | Service Board Name | No | `Service Board` |
| `CW_STATUS_NEW` | Status for new tickets | No | `New` |
| `CW_STATUS_CLOSED` | Status for closed tickets | No | `Closed` |
| `CW_DEFAULT_COMPANY_ID` | Fallback CW Company ID | No | - |
| `TRUSTED_IPS` | Whitelist IPs/CIDRs (comma-sep) | No | `0.0.0.0/0` (All) |
| `PORT` | Webhook Port | No | `5000` |

## Deployment

### Docker (GHCR Image)

You can pull the pre-built image directly from GitHub Container Registry:

```bash
docker pull ghcr.io/arumes31/kumawise:latest
docker run -d -p 5000:5000 --env-file .env ghcr.io/arumes31/kumawise:latest
```

### Docker Compose (GHCR Image)

Use the `docker-compose.ghcr.yml` file to run the latest pre-built image.

```bash
# Download the example file
curl -O https://raw.githubusercontent.com/arumes31/kumawise/main/docker-compose.ghcr.yml

# Rename and Configure
mv docker-compose.ghcr.yml docker-compose.yml
# Edit docker-compose.yml with your credentials

# Run
docker-compose up -d
```

### Docker Compose (Build Locally)

1. **Configure:** Update `docker-compose.yml` with your ConnectWise credentials.
2. **Run:**
   ```bash
   docker-compose up -d --build
   ```

### Manual

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Run:**
   ```bash
   # Linux/Mac
   export CW_COMPANY=your_company ...
   python app.py
   
   # Windows (PowerShell)
   $env:CW_COMPANY="your_company"; python app.py
   ```

## Uptime Kuma Setup

1. Go to **Settings > Notification**.
2. Click **Setup Notification**.
3. Notification Type: **Webhook**.
4. Post URL: `http://<your-kumawise-proxy-ip>:5000/webhook`.
5. Method: `POST`.
6. Content Type: `application/json`.

### Monitor Naming Convention

To automatically assign tickets to a specific ConnectWise company, include the Company Identifier in the Monitor Name using the `#CW` prefix.

**Example Monitor Name:** `Web Server - Production #CWMyClient`
*   The proxy will extract `MyClient` and use it as the `company/identifier` in the ConnectWise API call.

### Example Webhook Payload (JSON)

When Uptime Kuma sends an alert, it looks like this:

```json
{
  "heartbeat": {
    "status": 0,
    "time": "2026-01-21 22:00:00"
  },
  "monitor": {
    "name": "Web Server - Production #CWMyClient",
    "url": "https://example.com"
  },
  "msg": "Connection timeout"
}
```

## Development

### Running Tests
```bash
pytest
```
