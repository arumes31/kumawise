import re
import ipaddress
import time
import os
import logging
import uuid
from typing import Tuple, Dict, Any, Optional
from flask import Flask, request, jsonify, Response, g
from connectwise import ConnectWiseClient
from celery import Celery
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import redis
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

app = Flask(__name__)

# Configure ProxyFix if behind a reverse proxy
if os.environ.get('USE_PROXY') == 'true':
    num_proxies = int(os.environ.get('PROXY_FIX_COUNT', 1))
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=num_proxies, x_proto=num_proxies, x_host=num_proxies, x_port=num_proxies)

# Celery Configuration
celery_broker = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
celery = Celery('kumawise', broker=celery_broker)
redis_client = redis.Redis.from_url(celery_broker)

# Configure logging with Correlation ID (request_id)
class CorrelationFilter(logging.Filter):
    def filter(self, record):
        record.request_id = getattr(g, 'request_id', 'SYS')
        return True

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(request_id)s] %(message)s'
)
logger = logging.getLogger(__name__)
logger.addFilter(CorrelationFilter())

# Metrics
WEBHOOK_COUNT = Counter('kumawise_webhooks_total', 'Total number of webhooks received', ['status'])
PSA_TASK_COUNT = Counter('kumawise_psa_tasks_total', 'Total number of PSA tasks processed', ['type', 'result'])
PSA_TASK_DURATION = Histogram('kumawise_psa_task_duration_seconds', 'Duration of PSA tasks', ['type'])

cw_client = ConnectWiseClient()

@app.before_request
def set_request_id():
    """Extract or generate a correlation ID for the request."""
    req_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
    g.request_id = req_id

def get_remote_addr() -> str:
    """
    Returns the effective remote address.
    Supports Cloudflare header CF-Connecting-IP if USE_CLOUDFLARE is true.
    """
    if os.environ.get('USE_CLOUDFLARE') == 'true':
        cf_ip = request.headers.get('CF-Connecting-IP')
        if cf_ip:
            return cf_ip
    return request.remote_addr

def handle_alert_logic(data: Dict[str, Any], request_id: str):
    """
    Core logic for processing an alert. Accepts request_id for logging traceability.
    """
    extra = {'request_id': request_id}
    start_time = time.time()
    heartbeat = data.get('heartbeat', {})
    monitor = data.get('monitor', {})
    status = heartbeat.get('status') # 0 = Down, 1 = Up
    monitor_name = monitor.get('name', 'Unknown Monitor')
    msg = data.get('msg', 'No message')
    
    alert_type = "DOWN" if status == 0 else "UP"

    # Unique identifier for the ticket summary
    prefix = os.environ.get('CW_TICKET_PREFIX', 'Uptime Kuma Alert:')
    ticket_summary = f"{prefix} {monitor_name}" if prefix else monitor_name

    try:
        if status == 0: # DOWN
            logger.info(f"Processing DOWN alert for {monitor_name}", extra=extra)
            existing_ticket = cw_client.find_open_ticket(ticket_summary)
            if existing_ticket:
                logger.info(f"Ticket already exists for {monitor_name} (ID: {existing_ticket['id']}). Skipping.", extra=extra)
                PSA_TASK_COUNT.labels(type='create', result='skipped').inc()
                return
            
            # Extract Company ID from Monitor Name
            # Format expectation: "... #CW123 ..." -> company_id = 123
            company_id_match = re.search(r'#CW(\w+)', monitor_name)
            company_id = company_id_match.group(1) if company_id_match else None

            # Create new ticket
            description = f"Monitor: {monitor_name}\nURL: {monitor.get('url', 'N/A')}\nError: {msg}\nTime: {heartbeat.get('time')}\nRequest ID: {request_id}"
            cw_client.create_ticket(ticket_summary, description, monitor_name, company_id=company_id)
            PSA_TASK_COUNT.labels(type='create', result='success').inc()

        elif status == 1: # UP
            logger.info(f"Processing UP alert for {monitor_name}", extra=extra)
            # Find existing ticket to close
            existing_ticket = cw_client.find_open_ticket(ticket_summary)
            if existing_ticket:
                resolution = f"Monitor {monitor_name} is back UP.\nMessage: {msg}\nTime: {heartbeat.get('time')}\nRequest ID: {request_id}"
                cw_client.close_ticket(existing_ticket['id'], resolution)
                PSA_TASK_COUNT.labels(type='close', result='success').inc()
            else:
                logger.info(f"No open ticket found for {monitor_name} to close.", extra=extra)
                PSA_TASK_COUNT.labels(type='close', result='skipped').inc()

        PSA_TASK_DURATION.labels(type=alert_type).observe(time.time() - start_time)

    except Exception as exc:
        logger.error(f"Error processing {alert_type} alert: {exc}", extra=extra)
        PSA_TASK_COUNT.labels(type=alert_type.lower(), result='error').inc()
        # Retry with exponential backoff
        retry_delay = 2 ** self.request.retries * 60
        raise self.retry(exc=exc, countdown=retry_delay)

@celery.task(bind=True, max_retries=5, default_retry_delay=60)
def process_alert_task(self, data: Dict[str, Any], request_id: str):
    """
    Celery task wrapper with retry logic.
    """
    try:
        handle_alert_logic(data, request_id)
    except Exception as exc:
        # Re-raise for celery retry mechanism if it's not a logic error we handled
        if not isinstance(exc, (ValueError, KeyError)): # Simple example of logic error exclusion
             raise self.retry(exc=exc)
        raise exc

def is_ip_trusted(remote_addr: str) -> bool:
    trusted_env = os.environ.get('TRUSTED_IPS')
    if not trusted_env or "0.0.0.0/0" in trusted_env:
        return True
    try:
        client_ip = ipaddress.ip_address(remote_addr)
        for rule in trusted_env.split(','):
            rule = rule.strip()
            if not rule: continue
            if client_ip in ipaddress.ip_network(rule, strict=False):
                return True
    except ValueError:
        return False
    return False

@app.route('/webhook', methods=['POST'])
def webhook() -> Tuple[Response, int]:
    request_id = g.request_id
    remote_addr = get_remote_addr()
    
    # 1. IP Filtering
    if remote_addr and not is_ip_trusted(remote_addr):
        logger.warning(f"Access denied for IP: {remote_addr}")
        WEBHOOK_COUNT.labels(status='forbidden').inc()
        return jsonify({"status": "error", "message": "Forbidden", "request_id": request_id}), 403

    # 2. Secret Token Authentication (Optional)
    webhook_secret = os.environ.get('WEBHOOK_SECRET')
    if webhook_secret:
        provided_secret = request.headers.get('X-KumaWise-Secret')
        if provided_secret != webhook_secret:
            logger.warning(f"Unauthorized access attempt with invalid secret from {remote_addr}")
            WEBHOOK_COUNT.labels(status='unauthorized').inc()
            return jsonify({"status": "error", "message": "Unauthorized", "request_id": request_id}), 401

    data = request.json
    if not data:
        WEBHOOK_COUNT.labels(status='bad_request').inc()
        return jsonify({"status": "error", "message": "No JSON payload received", "request_id": request_id}), 400

    process_alert_task.delay(data, request_id)
    WEBHOOK_COUNT.labels(status='queued').inc()
    return jsonify({
        "status": "queued", 
        "message": "Alert received and queued", 
        "request_id": request_id
    }), 202

@app.route('/health', methods=['GET'])
def health() -> Tuple[Response, int]:
    """Basic health check with Redis ping."""
    try:
        redis_client.ping()
        return jsonify({"status": "ok", "timestamp": time.time()}), 200
    except Exception:
        return jsonify({"status": "error", "message": "Redis unreachable"}), 503

@app.route('/health/detailed', methods=['GET'])
def health_detailed() -> Tuple[Response, int]:
    """Deep health check including Redis and Celery status."""
    health_status = "ok"
    redis_ok = False
    celery_workers = []
    try:
        redis_ok = redis_client.ping()
    except Exception:
        health_status = "error"
    try:
        inspector = celery.control.inspect()
        active = inspector.active()
        if active:
            celery_workers = list(active.keys())
        else:
            health_status = "error"
    except Exception:
        health_status = "error"

    cw_configured = all([cw_client.base_url, cw_client.company, cw_client.public_key, cw_client.private_key, cw_client.client_id])
    
    return jsonify({
        "status": health_status,
        "timestamp": time.time(),
        "services": {
            "redis": {"status": "ok" if redis_ok else "error"},
            "celery": {"status": "ok" if celery_workers else "error", "active_workers": celery_workers},
            "connectwise": {"configured": cw_configured}
        }
    }), 200 if health_status == "ok" else 503

@app.route('/metrics', methods=['GET'])
def metrics() -> Response:
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)