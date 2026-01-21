import pytest
from unittest.mock import MagicMock, patch
from app import app

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
    assert response.json == {"status": "ok"}

@patch('app.cw_client')
def test_webhook_down_create_ticket(mock_cw, client):
    """Test that a DOWN alert creates a new ticket when none exists."""
    # Setup mock
    mock_cw.find_open_ticket.return_value = None
    mock_cw.create_ticket.return_value = {"id": 12345}
    
    payload = {
        "heartbeat": {"status": 0, "time": "2026-01-21 22:00:00"},
        "monitor": {"name": "Test Monitor #CW-COMP-1", "url": "http://example.com"},
        "msg": "Connection timeout"
    }
    
    response = client.post('/webhook', json=payload)
    
    assert response.status_code == 201
    assert response.json['status'] == "created"
    assert response.json['ticket_id'] == 12345
    
    # Verify mock calls
    mock_cw.find_open_ticket.assert_called_once()
    mock_cw.create_ticket.assert_called_once()

@patch('app.cw_client')
def test_webhook_down_already_exists(mock_cw, client):
    """Test that a DOWN alert does NOT create a ticket if one is already open."""
    # Setup mock
    mock_cw.find_open_ticket.return_value = {"id": 12345}
    
    payload = {
        "heartbeat": {"status": 0, "time": "2026-01-21 22:00:00"},
        "monitor": {"name": "Test Monitor #CW-COMP-1"},
        "msg": "Connection timeout"
    }
    
    response = client.post('/webhook', json=payload)
    
    assert response.status_code == 200
    assert response.json['status'] == "skipped"
    mock_cw.create_ticket.assert_not_called()

@patch('app.cw_client')
def test_webhook_up_close_ticket(mock_cw, client):
    """Test that an UP alert closes an existing ticket."""
    # Setup mock
    mock_cw.find_open_ticket.return_value = {"id": 12345}
    mock_cw.close_ticket.return_value = True
    
    payload = {
        "heartbeat": {"status": 1, "time": "2026-01-21 22:05:00"},
        "monitor": {"name": "Test Monitor #CW-COMP-1"},
        "msg": "Back online"
    }
    
    response = client.post('/webhook', json=payload)
    
    assert response.status_code == 200
    assert response.json['status'] == "closed"
    mock_cw.close_ticket.assert_called_once_with(12345, pytest.any_str)

@patch('app.cw_client')
def test_webhook_up_no_ticket(mock_cw, client):
    """Test that an UP alert is skipped if no ticket is open."""
    # Setup mock
    mock_cw.find_open_ticket.return_value = None
    
    payload = {
        "heartbeat": {"status": 1, "time": "2026-01-21 22:05:00"},
        "monitor": {"name": "Test Monitor #CW-COMP-1"},
        "msg": "Back online"
    }
    
    response = client.post('/webhook', json=payload)
    
    assert response.status_code == 200
    assert response.json['status'] == "skipped"
    mock_cw.close_ticket.assert_not_called()
