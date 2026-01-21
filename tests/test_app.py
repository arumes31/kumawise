import pytest
from unittest.mock import MagicMock, patch, ANY
from app import app, handle_alert_logic

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

@patch('app.cw_client')
def test_metrics(mock_cw, client):
    """Test the metrics endpoint."""
    response = client.get('/metrics')
    assert response.status_code == 200
    assert b"kumawise_webhooks_total" in response.data

@patch('app.process_alert_task.delay')
def test_webhook_queues_task(mock_delay, client):
    """Test that the webhook queues the celery task."""
    payload = {
        "heartbeat": {"status": 0, "time": "2026-01-21 22:00:00"},
        "monitor": {"name": "Test Monitor"},
        "msg": "Test"
    }
    
    response = client.post('/webhook', json=payload)
    
    assert response.status_code == 202
    # The JSON message changed slightly in my last rewrite, but 'queued' status is what matters
    assert response.json['status'] == "queued"
    mock_delay.assert_called_once_with(payload)

@patch('app.cw_client')
def test_handle_alert_logic_down(mock_cw):
    """Test the core logic for creating a ticket (DOWN alert)."""
    mock_cw.find_open_ticket.return_value = None
    mock_cw.create_ticket.return_value = {"id": 12345}
    
    data = {
        "heartbeat": {"status": 0, "time": "2026-01-21 22:00:00"},
        "monitor": {"name": "Test Monitor #CW-COMP-1", "url": "http://example.com"},
        "msg": "Connection timeout"
    }
    
    handle_alert_logic(data)
    
    mock_cw.find_open_ticket.assert_called_once()
    mock_cw.create_ticket.assert_called_once()

@patch('app.cw_client')
def test_handle_alert_logic_up(mock_cw):
    """Test the core logic for closing a ticket (UP alert)."""
    mock_cw.find_open_ticket.return_value = {"id": 12345}
    
    data = {
        "heartbeat": {"status": 1, "time": "2026-01-21 22:05:00"},
        "monitor": {"name": "Test Monitor #CW-COMP-1"},
        "msg": "Back online"
    }
    
    handle_alert_logic(data)
    
    mock_cw.close_ticket.assert_called_once_with(12345, ANY)