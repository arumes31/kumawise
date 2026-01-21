from flask import Flask, request, jsonify, Response
import logging
import os
import re
import ipaddress
import time
import queue
import threading
from typing import Tuple, Dict, Any, Optional
from connectwise import ConnectWiseClient

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

cw_client = ConnectWiseClient()
task_queue = queue.Queue()

def process_alert(data: Dict[str, Any]):
    """
    Background task to process the alert and interact with ConnectWise.
    """
    try:
        heartbeat = data.get('heartbeat', {})
        monitor = data.get('monitor', {})
        
        status = heartbeat.get('status') # 0 = Down, 1 = Up
        monitor_name = monitor.get('name', 'Unknown Monitor')
        msg = data.get('msg', 'No message')
        
        # Unique identifier for the ticket summary to find it later
        # Format: "Uptime Kuma Alert: [Monitor Name]"
        ticket_summary_prefix = "Uptime Kuma Alert:"
        ticket_summary = f"{ticket_summary_prefix} {monitor_name}"

        if status == 0: # DOWN
            logger.info(f"Processing DOWN alert for {monitor_name}")
            
            # Check if ticket already exists
            existing_ticket = cw_client.find_open_ticket(ticket_summary)
            
            if existing_ticket:
                logger.info(f"Ticket already exists for {monitor_name} (ID: {existing_ticket['id']}). Skipping creation.")
                return
            
            # Extract Company ID from Monitor Name
            # Format expectation: "... #CW123 ..." -> company_id = 123
            company_id_match = re.search(r'#CW(\w+)', monitor_name)
            company_id = company_id_match.group(1) if company_id_match else None

            # Create new ticket
            description = f"Monitor: {monitor_name}\nURL: {monitor.get('url', 'N/A')}\nError: {msg}\nTime: {heartbeat.get('time')}"
            cw_client.create_ticket(ticket_summary, description, monitor_name, company_id=company_id)

        elif status == 1: # UP
            logger.info(f"Processing UP alert for {monitor_name}")
            
            # Find existing ticket to close
            existing_ticket = cw_client.find_open_ticket(ticket_summary)
            
            if existing_ticket:
                resolution = f"Monitor {monitor_name} is back UP.\nMessage: {msg}\nTime: {heartbeat.get('time')}"
                cw_client.close_ticket(existing_ticket['id'], resolution)
            else:
                logger.info(f"No open ticket found for {monitor_name} to close.")
                
    except Exception as e:
        logger.error(f"Error processing alert in background worker: {e}", exc_info=True)

def worker():
    """
    Worker thread that processes tasks from the queue.
    """
    while True:
        try:
            item = task_queue.get()
            process_alert(item)
            task_queue.task_done()
        except Exception as e:
            logger.error(f"Unexpected error in worker thread: {e}", exc_info=True)

# Start the background worker thread
threading.Thread(target=worker, daemon=True).start()

def is_ip_trusted(remote_addr: str) -> bool:
    """
    Checks if the remote IP is in the trusted list.
    If TRUSTED_IPS is not set, allow all.
    If TRUSTED_IPS contains 0.0.0.0/0, allow all.
    """
    trusted_env = os.environ.get('TRUSTED_IPS')
    
    # If not configured, default to allow all (backward compatibility)
    if not trusted_env:
        return True
        
    # Quick check for allow all wildcard
    if "0.0.0.0/0" in trusted_env:
        return True

    try:
        client_ip = ipaddress.ip_address(remote_addr)
        for rule in trusted_env.split(','):
            rule = rule.strip()
            if not rule:
                continue
            
            # ip_network handles both single IPs (as /32) and CIDRs
            network = ipaddress.ip_network(rule, strict=False)
            if client_ip in network:
                return True
                
    except ValueError as e:
        logger.error(f"IP validation error for {remote_addr} against {trusted_env}: {e}")
        return False

    return False

@app.route('/webhook', methods=['POST'])
def webhook() -> Tuple[Response, int]:
    """
    Webhook endpoint to receive alerts from Uptime Kuma.
    Expects a JSON payload with 'heartbeat', 'monitor', and 'msg'.
    Queues the request for background processing.
    """
    # IP Filtering
    if request.remote_addr and not is_ip_trusted(request.remote_addr):
        logger.warning(f"Access denied for IP: {request.remote_addr}")
        return jsonify({"status": "error", "message": "Forbidden"}), 403

    data: Optional[Dict[str, Any]] = request.json
    
    if not data:
        return jsonify({"status": "error", "message": "No JSON payload received"}), 400

    # Queue the processing
    task_queue.put(data)
    
    return jsonify({"status": "queued", "message": "Alert received and queued for processing"}), 202

@app.route('/health', methods=['GET'])
def health() -> Tuple[Response, int]:
    """Basic health check."""
    return jsonify({
        "status": "ok",
        "message": "KumaWise Proxy is running",
        "timestamp": time.time(),
        "queue_size": task_queue.qsize()
    }), 200

@app.route('/health/detailed', methods=['GET'])
def health_detailed() -> Tuple[Response, int]:
    """Detailed health check including configuration status."""
    cw_configured = all([
        cw_client.base_url,
        cw_client.company,
        cw_client.public_key,
        cw_client.private_key,
        cw_client.client_id
    ])
    
    return jsonify({
        "status": "ok",
        "timestamp": time.time(),
        "services": {
            "connectwise": {
                "configured": cw_configured,
                "base_url": cw_client.base_url
            }
        },
        "environment": {
            "trusted_ips_enabled": bool(os.environ.get('TRUSTED_IPS'))
        }
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)