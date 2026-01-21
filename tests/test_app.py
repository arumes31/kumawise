import pytest
import time
from unittest.mock import MagicMock, patch, ANY
from app import app, process_alert

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@patch('app.cw_client')
def test_health(mock_cw, client):
    """Test the health endpoint."""
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json['status'] == "ok"
    assert "queue_size" in response.json

@patch('app.cw_client')
def test_webhook_queues_request(mock_cw, client):
    """Test that the webhook queues the request and returns 202."""
    payload = {
        "heartbeat": {"status": 0, "time": "2026-01-21 22:00:00"},
        "monitor": {"name": "Test Monitor"},
        "msg": "Test"
    }
    
    with patch('app.task_queue') as mock_queue:
        response = client.post('/webhook', json=payload)
        
        assert response.status_code == 202
        assert response.json['status'] == "queued"
        mock_queue.put.assert_called_once_with(payload)

@patch('app.cw_client')
def test_process_alert_down_create_ticket(mock_cw):
    """Test the background logic for creating a ticket."""
    mock_cw.find_open_ticket.return_value = None
    mock_cw.create_ticket.return_value = {"id": 12345}
    
    data = {
        "heartbeat": {"status": 0, "time": "2026-01-21 22:00:00"},
        "monitor": {"name": "Test Monitor #CW-COMP-1", "url": "http://example.com"},
        "msg": "Connection timeout"
    }
    
    process_alert(data)
    
    mock_cw.find_open_ticket.assert_called_once()
    mock_cw.create_ticket.assert_called_once()

@patch('app.cw_client')
def test_process_alert_up_close_ticket(mock_cw):
    """Test the background logic for closing a ticket."""
    mock_cw.find_open_ticket.return_value = {"id": 12345}
    
    data = {
        "heartbeat": {"status": 1, "time": "2026-01-21 22:05:00"},
        "monitor": {"name": "Test Monitor #CW-COMP-1"},
        "msg": "Back online"
    }
    
    process_alert(data)
    
    mock_cw.close_ticket.assert_called_once_with(12345, ANY)
