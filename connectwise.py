import os
import requests
import base64
import logging
from typing import Optional, Dict, Any, Union

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ConnectWiseClient:
    """
    A client wrapper for the ConnectWise Manage API (REST).
    """
    def __init__(self) -> None:
        self.base_url: str = os.getenv('CW_URL', 'https://api-na.myconnectwise.net/v4_6_release/apis/3.0')
        self.company: Optional[str] = os.getenv('CW_COMPANY')
        self.public_key: Optional[str] = os.getenv('CW_PUBLIC_KEY')
        self.private_key: Optional[str] = os.getenv('CW_PRIVATE_KEY')
        self.client_id: Optional[str] = os.getenv('CW_CLIENT_ID')
        
        # Configuration for tickets
        self.service_board_name: str = os.getenv('CW_SERVICE_BOARD', 'Service Board')
        self.status_new: str = os.getenv('CW_STATUS_NEW', 'New')
        self.status_closed: str = os.getenv('CW_STATUS_CLOSED', 'Closed')
        
        if not all([self.base_url, self.company, self.public_key, self.private_key]):
            logger.warning("ConnectWise credentials are missing. API calls will fail.")

        self.headers: Dict[str, str] = self._get_headers()

    def _get_headers(self) -> Dict[str, str]:
        """Constructs the authorization headers."""
        if not self.company or not self.public_key or not self.private_key:
            return {}
            
        auth_string = f"{self.company}+{self.public_key}:{self.private_key}"
        auth_header = f"Basic {base64.b64encode(auth_string.encode()).decode()}"
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if self.client_id:
            headers["clientId"] = self.client_id
        return headers

    def find_open_ticket(self, summary_contains: str) -> Optional[Dict[str, Any]]:
        """
        Finds an open ticket with a summary containing the specified text.
        
        Args:
            summary_contains: The text to search for in the ticket summary.
            
        Returns:
            The ticket dictionary if found, otherwise None.
        """
        try:
            # Filter for tickets that are NOT closed and contain the summary text
            conditions = f"closedFlag=false AND summary contains '{summary_contains}'"
            params = {
                "conditions": conditions,
                "pageSize": 1
            }
            
            response = requests.get(f"{self.base_url}/service/tickets", headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            return None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error finding ticket: {e}")
            if e.response:
                logger.error(f"Response: {e.response.text}")
            return None

    def create_ticket(self, summary: str, description: str, monitor_name: str, company_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Creates a new service ticket.
        
        Args:
            summary: Ticket summary/title.
            description: Ticket description/notes.
            monitor_name: Name of the monitor (for logging).
            company_id: Optional specific ConnectWise Company ID/Identifier.
            
        Returns:
            The created ticket dictionary or None if failed.
        """
        try:
            payload = {
                "summary": summary,
                "recordType": "ServiceTicket",
                "board": {"name": self.service_board_name},
                "status": {"name": self.status_new},
                "initialDescription": description,
            }
            
            # Priority: passed company_id > env var > none
            target_company_id = company_id or os.getenv('CW_DEFAULT_COMPANY_ID')
            
            if target_company_id:
                payload["company"] = {"identifier": target_company_id}

            response = requests.post(f"{self.base_url}/service/tickets", headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            
            ticket = response.json()
            logger.info(f"Created ticket #{ticket.get('id')} for {monitor_name}")
            return ticket
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error creating ticket: {e}")
            if e.response:
                logger.error(f"Response: {e.response.text}")
            return None

    def close_ticket(self, ticket_id: int, resolution: str) -> bool:
        """
        Closes a ticket by updating its status and adding a resolution note.
        
        Args:
            ticket_id: The ID of the ticket to close.
            resolution: The resolution note text.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            # 1. Update status to closed
            patch_payload = [
                {
                    "op": "replace",
                    "path": "/status/name",
                    "value": self.status_closed
                }
            ]
            
            response = requests.patch(f"{self.base_url}/service/tickets/{ticket_id}", headers=self.headers, json=patch_payload, timeout=30)
            response.raise_for_status()
            
            # 2. Add resolution note
            note_payload = {
                "text": resolution,
                "detailDescriptionFlag": True,
                "internalAnalysisFlag": False,
                "resolutionFlag": True
            }
            requests.post(f"{self.base_url}/service/tickets/{ticket_id}/notes", headers=self.headers, json=note_payload, timeout=30)

            logger.info(f"Closed ticket #{ticket_id}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Error closing ticket #{ticket_id}: {e}")
            if e.response:
                logger.error(f"Response: {e.response.text}")
            return False
