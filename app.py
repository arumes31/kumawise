from flask import Flask, request, jsonify, Response
import logging
import os
import re
from typing import Tuple, Dict, Any, Optional
from connectwise import ConnectWiseClient

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

cw_client = ConnectWiseClient()

@app.route('/webhook', methods=['POST'])
def webhook() -> Tuple[Response, int]:
    """
    Webhook endpoint to receive alerts from Uptime Kuma.
    Expects a JSON payload with 'heartbeat', 'monitor', and 'msg'.
    """
    data: Optional[Dict[str, Any]] = request.json
    
    if not data:
        return jsonify({"status": "error", "message": "No JSON payload received"}), 400

    heartbeat: Dict[str, Any] = data.get('heartbeat', {})
    monitor: Dict[str, Any] = data.get('monitor', {})
    
    status: Optional[int] = heartbeat.get('status') # 0 = Down, 1 = Up
    monitor_name: str = monitor.get('name', 'Unknown Monitor')
    msg: str = data.get('msg', 'No message')
    
    # Unique identifier for the ticket summary to find it later
    # Format: "Uptime Kuma Alert: [Monitor Name]"
    ticket_summary_prefix = "Uptime Kuma Alert:"
    ticket_summary = f"{ticket_summary_prefix} {monitor_name}"

    if status == 0: # DOWN
        logger.info(f"Received DOWN alert for {monitor_name}")
        
        # Check if ticket already exists
        existing_ticket = cw_client.find_open_ticket(ticket_summary)
        
        if existing_ticket:
            logger.info(f"Ticket already exists for {monitor_name} (ID: {existing_ticket['id']}). Skipping creation.")
            return jsonify({"status": "skipped", "message": "Ticket already exists"}), 200
        
        # Extract Company ID from Monitor Name
        # Format expectation: "... #CW123 ..." -> company_id = 123
        company_id_match = re.search(r'#CW(\w+)', monitor_name)
        company_id = company_id_match.group(1) if company_id_match else None

        # Create new ticket
        description = f"Monitor: {monitor_name}\nURL: {monitor.get('url', 'N/A')}\nError: {msg}\nTime: {heartbeat.get('time')}"
        new_ticket = cw_client.create_ticket(ticket_summary, description, monitor_name, company_id=company_id)
        
        if new_ticket:
            return jsonify({"status": "created", "ticket_id": new_ticket['id']}), 201
        else:
            return jsonify({"status": "error", "message": "Failed to create ticket"}), 500

    elif status == 1: # UP
        logger.info(f"Received UP alert for {monitor_name}")
        
        # Find existing ticket to close
        existing_ticket = cw_client.find_open_ticket(ticket_summary)
        
        if existing_ticket:
            resolution = f"Monitor {monitor_name} is back UP.\nMessage: {msg}\nTime: {heartbeat.get('time')}"
            success = cw_client.close_ticket(existing_ticket['id'], resolution)
            
            if success:
                return jsonify({"status": "closed", "ticket_id": existing_ticket['id']}), 200
            else:
                return jsonify({"status": "error", "message": "Failed to close ticket"}), 500
        else:
            logger.info(f"No open ticket found for {monitor_name} to close.")
            return jsonify({"status": "skipped", "message": "No open ticket found"}), 200

    return jsonify({"status": "ignored", "message": "Status not relevant"}), 200

@app.route('/health', methods=['GET'])
def health() -> Tuple[Response, int]:
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
