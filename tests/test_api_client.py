
import pytest
from unittest.mock import Mock, patch
from czds_utils.api_client import CZDSClient
from czds_utils.errors import APIError

class TestCZDSClient:
    @pytest.fixture
    def client(self):
        return CZDSClient(
            base_url="https://api.example.com",
            username="testuser",
            password="testpassword",
            auth_url="https://auth.example.com",
            validate_ssl=False
        )

    @patch("requests.Session.post")
    def test_authenticate_success_json(self, mock_post, client):
        """Test authentication with valid JSON response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "accessToken": "valid_token_123",
            "message": "Authentication Successful"
        }
        mock_response.text = '{"accessToken": "valid_token_123"}'
        mock_post.return_value = mock_response

        token = client.authenticate()
        
        assert token == "valid_token_123"
        assert client._access_token == "valid_token_123"
        
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs['json'] == {
            "username": "testuser",
            "password": "testpassword"
        }

    @patch("requests.Session.post")
    def test_authenticate_success_fallback(self, mock_post, client):
        """Test authentication fallback to plain text (backward compatibility)."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.text = "raw_token_xyz"
        mock_post.return_value = mock_response

        token = client.authenticate()
        
        assert token == "raw_token_xyz"
        
    @patch("requests.Session.post")
    def test_authenticate_failure_401(self, mock_post, client):
        """Test authentication failure."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_post.return_value = mock_response

        with pytest.raises(APIError) as exc:
            client.authenticate()
        assert "Authentication failed" in str(exc.value)

    @patch("requests.Session.get")
    def test_get_zone_links_success(self, mock_get, client):
        """Test fetching zone links."""
        # Mock successful auth first
        client._access_token = "valid_token"
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            "https://api.example.com/czds/downloads/example.com.zone",
            "https://api.example.com/czds/downloads/test.org.zone"
        ]
        mock_get.return_value = mock_response

        links = client.get_zone_links()
        
        assert len(links) == 2
        assert "valid_token" in mock_get.call_args[1]['headers']['Authorization']
