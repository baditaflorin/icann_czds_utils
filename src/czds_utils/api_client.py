"""CZDS API client with secure authentication and error handling.

This module provides a secure interface to ICANN's Centralized Zone Data Service API.
All inputs are validated and all network errors are handled safely.
"""

import logging
import time
from typing import Optional, List, Dict, Any, BinaryIO
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from czds_utils.errors import APIError, ValidationError
from czds_utils.validators import Validators


class CZDSClient:
    """Client for ICANN CZDS API with secure authentication and error handling."""

    # API endpoints
    AUTHENTICATE_ENDPOINT = "/api/authenticate"
    ZONE_LINKS_ENDPOINT = "/czds/downloads/links"

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        auth_url: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        validate_ssl: bool = True
    ):
        """Initialize CZDS API client.

        Args:
            base_url: Base URL for CZDS API (validated)
            username: CZDS username (validated)
            password: CZDS password
            auth_url: Base URL for Authentication API (optional, validated)
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries for failed requests
            validate_ssl: Whether to validate SSL certificates

        Raises:
            ValidationError: If inputs are invalid
        """
        # Validate inputs
        self.base_url = Validators.validate_url(base_url, 'base_url').rstrip('/')
        
        # Validate auth_url if provided, otherwise default to base_url (for backward compatibility)
        if auth_url:
            self.auth_url = Validators.validate_url(auth_url, 'auth_url').rstrip('/')
        else:
            self.auth_url = self.base_url

        self.username = Validators.validate_username(username, 'username')

        if not password:
            raise ValidationError("Password cannot be empty", 'password')
        self.password = password

        self.timeout = Validators.validate_integer(timeout, 'timeout', min_value=1, max_value=300)
        self.max_retries = Validators.validate_integer(max_retries, 'max_retries', min_value=0, max_value=10)
        self.validate_ssl = validate_ssl

        self._logger = logging.getLogger(__name__)
        self._session = self._create_session()
        self._access_token: Optional[str] = None

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic.

        Returns:
            Configured requests.Session
        """
        session = requests.Session()

        # Configure retry strategy for transient failures
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def authenticate(self) -> str:
        """Authenticate with CZDS API and get access token.

        Returns:
            Access token

        Raises:
            APIError: If authentication fails
        """
        url = f"{self.auth_url}{self.AUTHENTICATE_ENDPOINT}"

        # Prepare authentication payload
        payload = {
            "username": self.username,
            "password": self.password
        }

        try:
            self._logger.info("Authenticating with CZDS API...")

            response = self._session.post(
                url,
                json=payload,
                timeout=self.timeout,
                verify=self.validate_ssl,
                headers={"Content-Type": "application/json"}
            )

            # Handle authentication errors
            if response.status_code == 401:
                raise APIError(
                    f"Authentication failed for user {self.username}",
                    status_code=401
                )
            elif response.status_code != 200:
                raise APIError(
                    f"Authentication failed with status {response.status_code}",
                    status_code=response.status_code
                )

            # Extract access token from response
            try:
                data = response.json()
                self._access_token = data.get("accessToken")
            except ValueError:
                # Fallback if valid JSON is not returned, though unlikely
                self._access_token = response.text.strip()

            if not self._access_token:
                raise APIError(
                    "No access token received from server",
                    status_code=response.status_code
                )

            self._logger.info("Authentication successful")
            return self._access_token

        except requests.RequestException as e:
            self._logger.error(f"Authentication request failed: {str(e)}")
            raise APIError(f"Authentication request failed: {str(e)}")

    def _ensure_authenticated(self) -> None:
        """Ensure we have a valid access token.

        Raises:
            APIError: If authentication fails
        """
        if not self._access_token:
            self.authenticate()

    def get_zone_links(self) -> List[str]:
        """Get list of available zone file download links.

        Returns:
            List of download URLs

        Raises:
            APIError: If request fails
        """
        self._ensure_authenticated()

        url = f"{self.base_url}{self.ZONE_LINKS_ENDPOINT}"

        try:
            self._logger.info("Fetching zone file links...")

            response = self._session.get(
                url,
                timeout=self.timeout,
                verify=self.validate_ssl,
                headers={"Authorization": f"Bearer {self._access_token}"}
            )

            if response.status_code == 401:
                # Token might have expired, try re-authenticating
                self._logger.info("Access token expired, re-authenticating...")
                self.authenticate()

                # Retry request with new token
                response = self._session.get(
                    url,
                    timeout=self.timeout,
                    verify=self.validate_ssl,
                    headers={"Authorization": f"Bearer {self._access_token}"}
                )

            if response.status_code != 200:
                raise APIError(
                    f"Failed to get zone links: HTTP {response.status_code}",
                    status_code=response.status_code
                )

            links = response.json()

            if not isinstance(links, list):
                raise APIError(
                    f"Unexpected response format: expected list, got {type(links).__name__}"
                )

            self._logger.info(f"Found {len(links)} zone file links")
            return links

        except requests.RequestException as e:
            self._logger.error(f"Failed to get zone links: {str(e)}")
            raise APIError(f"Failed to get zone links: {str(e)}")

    def download_zone_file(
        self,
        download_url: str,
        output_path: Path,
        chunk_size: int = 8192,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """Download a zone file from CZDS.

        Args:
            download_url: Zone file download URL (validated)
            output_path: Path where file will be saved (validated)
            chunk_size: Size of download chunks in bytes
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary with download statistics

        Raises:
            APIError: If download fails
            ValidationError: If inputs are invalid
        """
        self._ensure_authenticated()

        # Validate URL
        download_url = Validators.validate_url(download_url, 'download_url')

        # Validate output path
        if not isinstance(output_path, Path):
            output_path = Path(output_path)

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Validate chunk size
        chunk_size = Validators.validate_integer(
            chunk_size,
            'chunk_size',
            min_value=1024,
            max_value=1048576
        )

        try:
            self._logger.info(f"Downloading zone file from {download_url}")
            start_time = time.time()

            response = self._session.get(
                download_url,
                timeout=self.timeout,
                verify=self.validate_ssl,
                headers={"Authorization": f"Bearer {self._access_token}"},
                stream=True
            )

            if response.status_code == 401:
                # Token expired, re-authenticate and retry
                self._logger.info("Access token expired, re-authenticating...")
                self.authenticate()

                response = self._session.get(
                    download_url,
                    timeout=self.timeout,
                    verify=self.validate_ssl,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    stream=True
                )

            if response.status_code != 200:
                raise APIError(
                    f"Download failed: HTTP {response.status_code}",
                    status_code=response.status_code
                )

            # Get file size if available
            total_size = int(response.headers.get('content-length', 0))

            # Download file in chunks
            bytes_downloaded = 0
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        bytes_downloaded += len(chunk)

                        # Call progress callback if provided
                        if progress_callback and total_size:
                            progress = (bytes_downloaded / total_size) * 100
                            progress_callback(bytes_downloaded, total_size, progress)

            download_time = time.time() - start_time

            stats = {
                'file_path': str(output_path),
                'bytes_downloaded': bytes_downloaded,
                'download_time_seconds': download_time,
                'download_speed_mbps': (bytes_downloaded / 1024 / 1024) / download_time if download_time > 0 else 0
            }

            self._logger.info(
                f"Download complete: {bytes_downloaded} bytes in {download_time:.2f}s "
                f"({stats['download_speed_mbps']:.2f} MB/s)"
            )

            return stats

        except requests.RequestException as e:
            self._logger.error(f"Download failed: {str(e)}")
            raise APIError(f"Download failed: {str(e)}")
        except IOError as e:
            self._logger.error(f"File write failed: {str(e)}")
            raise APIError(f"Failed to write file: {str(e)}")

    def get_zone_info(self, tld: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific TLD zone file.

        Args:
            tld: TLD name (validated)

        Returns:
            Zone information dictionary or None if not found

        Raises:
            APIError: If request fails
            ValidationError: If TLD is invalid
        """
        # Validate TLD
        tld = Validators.validate_tld(tld, 'tld')

        try:
            # Get all zone links
            links = self.get_zone_links()

            # Find the link for this TLD
            tld_pattern = f"/{tld}."
            for link in links:
                if tld_pattern in link.lower():
                    return {
                        'tld': tld,
                        'download_url': link,
                        'available': True
                    }

            return None

        except APIError:
            raise

    def close(self) -> None:
        """Close the API client and cleanup resources."""
        if self._session:
            self._session.close()
            self._logger.debug("API client session closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
