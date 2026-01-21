import re
import ipaddress
import time
import os
import logging
from typing import Tuple, Dict, Any, Optional
from flask import Flask, request, jsonify, Response
from connectwise import ConnectWiseClient
from celery import Celery
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Metrics
WEBHOOK_COUNT = Counter('kumawise_webhooks_total', 'Total number of webhooks received', ['status'])
PSA_TASK_COUNT = Counter('kumawise_psa_tasks_total', 'Total number of PSA tasks processed', ['type', 'result'])
PSA_TASK_DURATION = Histogram('kumawise_psa_task_duration_seconds', 'Duration of PSA tasks', ['type'])

# Celery Configuration
celery_broker = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
celery = Celery('kumawise', broker=celery_broker)

cw_client = ConnectWiseClient()

def handle_alert_logic(data: Dict[str, Any]):
    """
    Core logic for processing an alert. Separated from Celery for testability.
    """
    start_time = time.time()
    heartbeat = data.get('heartbeat', {})
    monitor = data.get('monitor', {})
    status = heartbeat.get('status') # 0 = Down, 1 = Up
    monitor_name = monitor.get('name', 'Unknown Monitor')
    msg = data.get('msg', 'No message')
    
    alert_type = "DOWN" if status == 0 else "UP"
    
    # Unique identifier for the ticket summary
    ticket_summary_prefix = "Uptime Kuma Alert:"
    ticket_summary = f"{ticket_summary_prefix} {monitor_name}"

    if status == 0: # DOWN
        logger.info(f"Processing DOWN alert for {monitor_name}")
        existing_ticket = cw_client.find_open_ticket(ticket_summary)
        if existing_ticket:
            logger.info(f"Ticket already exists for {monitor_name} (ID: {existing_ticket['id']}). Skipping.")
            PSA_TASK_COUNT.labels(type='create', result='skipped').inc()
            return
        
        company_id_match = re.search(r'#CW(\w+)', monitor_name)
        company_id = company_id_match.group(1) if company_id_match else None
        description = f"Monitor: {monitor_name}\nURL: {monitor.get('url', 'N/A')}\nError: {msg}\nTime: {heartbeat.get('time')}"
        cw_client.create_ticket(ticket_summary, description, monitor_name, company_id=company_id)
        PSA_TASK_COUNT.labels(type='create', result='success').inc()

    elif status == 1: # UP
        logger.info(f"Processing UP alert for {monitor_name}")
        existing_ticket = cw_client.find_open_ticket(ticket_summary)
        if existing_ticket:
            resolution = f"Monitor {monitor_name} is back UP.\nMessage: {msg}\nTime: {heartbeat.get('time')}"
            cw_client.close_ticket(existing_ticket['id'], resolution)
            PSA_TASK_COUNT.labels(type='close', result='success').inc()
        else:
            logger.info(f"No open ticket found for {monitor_name} to close.")
            PSA_TASK_COUNT.labels(type='close', result='skipped').inc()

    PSA_TASK_DURATION.labels(type=alert_type).observe(time.time() - start_time)

@celery.task(bind=True, max_retries=5, default_retry_delay=60)
def process_alert_task(self, data: Dict[str, Any]):
    """
    Celery task wrapper with retry logic.
    """
    try:
        handle_alert_logic(data)
    except Exception as exc:
        alert_type = "DOWN" if data.get('heartbeat', {}).get('status') == 0 else "UP"
        logger.error(f"Error processing {alert_type} alert: {exc}")
        PSA_TASK_COUNT.labels(type=alert_type.lower(), result='error').inc()
        retry_delay = 2 ** self.request.retries * 60
        raise self.retry(exc=exc, countdown=retry_delay)

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
    if request.remote_addr and not is_ip_trusted(request.remote_addr):
        WEBHOOK_COUNT.labels(status='forbidden').inc()
        return jsonify({"status": "error", "message": "Forbidden"}), 403

    data = request.json
    if not data:
        WEBHOOK_COUNT.labels(status='bad_request').inc()
        return jsonify({"status": "error", "message": "No JSON payload received"}), 400

    process_alert_task.delay(data)
    WEBHOOK_COUNT.labels(status='queued').inc()
    return jsonify({"status": "queued", "message": "Alert received and queued"}), 202

@app.route('/health', methods=['GET'])
def health() -> Tuple[Response, int]:
    return jsonify({
        "status": "ok",
        "timestamp": time.time()
    }), 200

@app.route('/metrics', methods=['GET'])
def metrics() -> Response:
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
