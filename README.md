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
- **Persistent Queuing:** Uses Redis and Celery to ensure no alerts are lost during downtime or restarts.
- **Auto-Ticketing:** Creates a ticket in ConnectWise when a monitor goes DOWN.
- **Auto-Resolution:** Closes the corresponding ticket when the monitor comes back UP.
- **Smart Parsing:** Extracts Company ID from monitor names (e.g., `My Server #CW123`) for correct assignment.
- **Traceability:** Correlation IDs (Request IDs) injected into all logs and tickets for end-to-end tracking.
- **Resilience:** Automatic retries with exponential backoff for PSA API calls.
- **Observability:** Built-in Prometheus metrics and deep health checks.

## Configuration

The application is configured via environment variables.

| Variable | Description | Required | Default |
|----------|-------------|:--------:|---------|
| `CW_URL` | ConnectWise API Base URL | No | `https://api-na.myconnectwise.net/v4_6_release/apis/3.0` |
| `CW_COMPANY` | Your ConnectWise Company ID | **Yes** | - |
| `CW_PUBLIC_KEY` | API Public Key | **Yes** | - |
| `CW_PRIVATE_KEY` | API Private Key | **Yes** | - |
| `CW_CLIENT_ID` | API Client ID | **Yes** | - |
| `REDIS_PASSWORD` | Optional password for Redis security | No | - |
| `CW_SERVICE_BOARD` | Service Board Name | No | `Service Board` |
| `CW_STATUS_NEW` | Status for new tickets | No | `New` |
| `CW_STATUS_CLOSED` | Status for closed tickets | No | `Closed` |
| `CW_DEFAULT_COMPANY_ID` | Fallback CW Company ID | No | - |
| `CW_TICKET_PREFIX` | Prefix for ticket summary | No | `Uptime Kuma Alert:` |
| `PSA_RATE_LIMIT` | Celery task rate limit (e.g., `10/m`, `2/s`) | No | `60/m` |
| `WEBHOOK_SECRET` | Optional shared secret(s) for authentication. Multiple keys can be provided as a comma-separated list. If set, requests must include a valid `X-KumaWise-Secret` header. | No | - |
| `CELERY_BROKER_URL` | Redis connection string | No | `redis://redis:6379/0` |
| `TRUSTED_IPS` | Whitelist IPs/CIDRs (comma-sep) | No | `0.0.0.0/0` (All) |
| `USE_PROXY` | Enable Reverse Proxy support (X-Forwarded-For) | No | `false` |
| `PROXY_FIX_COUNT` | Number of upstream proxies | No | `1` |
| `USE_CLOUDFLARE` | Enable Cloudflare (CF-Connecting-IP) support | No | `false` |
| `PORT` | Webhook Port | No | `5000` |

## Deployment

### Docker (GHCR Image)

You can pull the pre-built image directly from GitHub Container Registry:

```bash
docker pull ghcr.io/arumes31/kumawise:latest
docker run -d -p 5000:5000 --env-file .env ghcr.io/arumes31/kumawise:latest
```

### Docker Compose (Recommended)

The recommended way to deploy is using Docker Compose, which includes the Proxy, Worker, and Redis.

```bash
# Download the example file
curl -O https://raw.githubusercontent.com/arumes31/kumawise/main/docker-compose.ghcr.yml

# Rename and Configure
mv docker-compose.ghcr.yml docker-compose.yml
# Edit docker-compose.yml with your credentials

# Run
docker-compose up -d
```

## Monitoring

- **Basic Health:** `GET /health` (Verifies API and Redis connectivity)
- **Detailed Health:** `GET /health/detailed` (Verifies Celery workers and CW config)
- **Metrics:** `GET /metrics` (Prometheus formatted metrics)

## Security

### Webhook Secret (Recommended)

To prevent unauthorized entities from creating tickets, configure one or more `WEBHOOK_SECRET` tokens.

1.  **Proxy Side:** Set the environment variable `WEBHOOK_SECRET=token1,token2`.
2.  **Uptime Kuma Side:**
    *   Go to your Webhook Notification settings.
    *   Add a **Custom Header**:
        *   Name: `X-KumaWise-Secret`
        *   Value: `token1` (or `token2`)

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

## Development

### Running Tests
```bash
pytest
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.