import pytest
from unittest.mock import MagicMock, patch, ANY
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
def test_webhook_ip_allowed_default(mock_cw, client):
    """Test that requests are allowed when TRUSTED_IPS is not set."""
    with patch.dict('os.environ', {}, clear=True):
        payload = {
            "heartbeat": {"status": 0, "time": "2026-01-21 22:00:00"},
            "monitor": {"name": "Test Monitor"},
            "msg": "Test"
        }
        response = client.post('/webhook', json=payload)
        # Should proceed (and fail on mock logic or succeed if mock setup correctly, 
        # but definitely NOT 403)
        assert response.status_code != 403

@patch('app.cw_client')
def test_webhook_ip_allowed_wildcard(mock_cw, client):
    """Test that requests are allowed when TRUSTED_IPS includes 0.0.0.0/0."""
    with patch.dict('os.environ', {'TRUSTED_IPS': '0.0.0.0/0'}):
        payload = {"heartbeat": {}, "monitor": {}, "msg": ""}
        response = client.post('/webhook', json=payload, environ_base={'REMOTE_ADDR': '1.2.3.4'})
        assert response.status_code != 403

@patch('app.cw_client')
def test_webhook_ip_allowed_specific(mock_cw, client):
    """Test that requests are allowed from a trusted IP."""
    with patch.dict('os.environ', {'TRUSTED_IPS': '192.168.1.100, 10.0.0.0/24'}):
        # Setup minimal mock to pass the logic inside if access granted
        mock_cw.find_open_ticket.return_value = None
        
        payload = {"heartbeat": {"status": 2}, "monitor": {}, "msg": ""} # Status 2 = Ignored
        
        # Test exact match
        response = client.post('/webhook', json=payload, environ_base={'REMOTE_ADDR': '192.168.1.100'})
        assert response.status_code == 200
        
        # Test CIDR match
        response = client.post('/webhook', json=payload, environ_base={'REMOTE_ADDR': '10.0.0.5'})
        assert response.status_code == 200

@patch('app.cw_client')
def test_webhook_ip_denied(mock_cw, client):
    """Test that requests are denied from an untrusted IP."""
    with patch.dict('os.environ', {'TRUSTED_IPS': '192.168.1.100'}):
        payload = {"heartbeat": {}, "monitor": {}, "msg": ""}
        response = client.post('/webhook', json=payload, environ_base={'REMOTE_ADDR': '192.168.1.101'})
        assert response.status_code == 403
        assert response.json['message'] == "Forbidden"

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
    mock_cw.close_ticket.assert_called_once_with(12345, ANY)

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