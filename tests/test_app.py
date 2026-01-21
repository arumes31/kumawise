from unittest.mock import ANY, patch

import pytest

from app import app, handle_alert_logic


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@patch('app.redis_client.ping')
@patch('app.cw_client')
def test_health(mock_cw, mock_ping, client):
    """Test the health endpoint."""
    mock_ping.return_value = True
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json['status'] == "ok"

@patch('app.redis_client.ping')
@patch('app.cw_client')
def test_health_redis_down(mock_cw, mock_ping, client):
    """Test the health endpoint when Redis is down."""
    mock_ping.side_effect = Exception("Redis connection failed")
    response = client.get('/health')
    assert response.status_code == 503
    assert response.json['status'] == "error"

@patch('app.cw_client')
def test_metrics(mock_cw, client):
    """Test the metrics endpoint."""
    response = client.get('/metrics')
    assert response.status_code == 200
    assert b"kumawise_webhooks_total" in response.data

@patch('app.process_alert_task.delay')
def test_webhook_queues_task(mock_delay, client):
    """Test that the webhook queues the celery task and returns a request_id."""
    payload = {
        "heartbeat": {"status": 0, "time": "2026-01-21 22:00:00"},
        "monitor": {"name": "Test Monitor"},
        "msg": "Test"
    }
    
    response = client.post('/webhook', json=payload)
    
    assert response.status_code == 202
    assert response.json['status'] == "queued"
    assert "request_id" in response.json
    # Verify that the task was queued with the same request_id
    mock_delay.assert_called_once_with(payload, response.json['request_id'])

@patch('app.redis_client')
@patch('app.cw_client')
def test_handle_alert_logic_down_with_cache(mock_cw, mock_redis):
    """Test DOWN alert when ticket is in Redis cache."""
    mock_redis.get.return_value = b"12345"
    
    data = {
        "heartbeat": {"status": 0},
        "monitor": {"name": "Cached Monitor"},
        "msg": "Down"
    }
    
    with app.app_context():
        handle_alert_logic(data, "req-123")
    
    # Should check cache but NOT call ConnectWise
    mock_redis.get.assert_called_once()
    mock_cw.find_open_ticket.assert_not_called()
    mock_cw.create_ticket.assert_not_called()

@patch('app.redis_client')
@patch('app.cw_client')
def test_handle_alert_logic_up_with_cache(mock_cw, mock_redis):
    """Test UP alert when ticket is in Redis cache."""
    mock_redis.get.return_value = b"12345"
    mock_cw.close_ticket.return_value = True
    
    data = {
        "heartbeat": {"status": 1},
        "monitor": {"name": "Cached Monitor"},
        "msg": "Up"
    }
    
    with app.app_context():
        handle_alert_logic(data, "req-123")
    
    # Should use ID from cache, close ticket, and delete cache key
    mock_cw.close_ticket.assert_called_once_with(12345, ANY)
    mock_redis.delete.assert_called_once()

@patch('app.redis_client')
@patch('app.cw_client')
def test_handle_alert_logic_custom_prefix(mock_cw, mock_redis):
    """Test the custom ticket summary prefix."""
    mock_redis.get.return_value = None
    mock_cw.find_open_ticket.return_value = None
    
    data = {
        "heartbeat": {"status": 0, "time": "2026-01-21 22:00:00"},
        "monitor": {"name": "Test Monitor"},
        "msg": "Test"
    }
    
    with patch.dict('os.environ', {'CW_TICKET_PREFIX': 'CUSTOM PREFIX:'}):
        with app.app_context():
            handle_alert_logic(data, "test-req-id")
            mock_cw.find_open_ticket.assert_called_once_with("CUSTOM PREFIX: Test Monitor")