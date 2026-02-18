"""Authentication for Rehau Nea Smart."""
import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class RehauAuthClient:
    """Handle Rehau authentication."""

    BASE_URL = "https://accounts.rehau.com"
    CLIENT_ID = "3f5d915d-a06f-42b9-89cc-2e5d63aa96f1"
    REDIRECT_URI = "https://rehau-smartheating-email-gallery-public.s3.eu-central-1.amazonaws.com/publicimages/preprod/rehau.jpg"

    IOS_HEADERS = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": "app://ios.neasmart.de",
        "Connection": "keep-alive",
    }

    def __init__(self, session: aiohttp.ClientSession):
        """Initialize the auth client."""
        self.session = session
        self._generate_pkce_pair()
        self.sub = None
        self.request_id = None
        self.track_id = None
        self.medium_id = None
        self.exchange_id = None
        self.status_id = None
        self.code = None
        self.access_token = None
        self.refresh_token = None
        self.expires_at = None
        self.sid = None

    def _generate_pkce_pair(self):
        """Generate PKCE code verifier and challenge."""
        self.code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
        challenge_bytes = hashlib.sha256(self.code_verifier.encode("utf-8")).digest()
        self.code_challenge = base64.urlsafe_b64encode(challenge_bytes).decode("utf-8").rstrip("=")
        self.nonce = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode("utf-8").rstrip("=")

    async def start_authorization_flow(self):
        """Start OAuth authorization flow."""
        from urllib.parse import urlparse, parse_qs

        _LOGGER.debug("Starting OAuth authorization flow")
        params = {
            "client_id": self.CLIENT_ID,
            "redirect_uri": self.REDIRECT_URI,
            "response_type": "code",
            "scope": "email roles profile offline_access groups",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "nonce": self.nonce,
        }

        async with self.session.get(
            f"{self.BASE_URL}/authz-srv/authz", params=params, headers=self.IOS_HEADERS, allow_redirects=False
        ) as response:
            _LOGGER.debug(f"Authorization response status: {response.status}")
            if response.status == 302:
                location = response.headers.get("Location", "")
                # Try parsing with requestId (capital I)
                if "requestId=" in location:
                    parsed = urlparse(location)
                    params_parsed = parse_qs(parsed.query)
                    self.request_id = params_parsed.get('requestId', [None])[0]
                    _LOGGER.debug(f"Got request_id: {self.request_id}")
                # Fallback to request_id (lowercase)
                elif "request_id=" in location:
                    params_str = location.split("?")[1] if "?" in location else ""
                    for param in params_str.split("&"):
                        if param.startswith("request_id="):
                            self.request_id = param.split("=")[1]
                            _LOGGER.debug(f"Got request_id: {self.request_id}")
                            break

    async def login(self, username: str, password: str) -> bool:
        """Login with username and password."""
        from urllib.parse import urlparse, parse_qs

        _LOGGER.debug(f"Attempting login for user: {username}")
        if not self.request_id:
            await self.start_authorization_flow()

        # Use form data, not JSON
        data = {
            "username": username,
            "username_type": "email",
            "password": password,
            "requestId": self.request_id,
            "rememberMe": "true"
        }

        async with self.session.post(
            f"{self.BASE_URL}/login-srv/login", data=data, allow_redirects=False
        ) as response:
            _LOGGER.debug(f"Login response status: {response.status}")
            if response.status == 302:
                location = response.headers.get("Location", "")
                parsed = urlparse(location)
                params = parse_qs(parsed.query)

                self.track_id = params.get("track_id", [None])[0]
                self.sub = params.get("sub", [None])[0]
                # Keep the original request_id if not in redirect
                if 'requestId' in params:
                    self.request_id = params.get("requestId", [None])[0]
                elif 'request_id' in params:
                    self.request_id = params.get("request_id", [None])[0]

                _LOGGER.debug(f"Login successful, track_id: {self.track_id}, sub: {self.sub}, request_id: {self.request_id}")
                return True
            _LOGGER.warning(f"Login failed with status: {response.status}")
            return False

    async def initiate_mfa_email(self) -> bool:
        """Initiate MFA email verification."""
        if not self.sub or not self.request_id:
            raise ValueError("Must call login() first")

        _LOGGER.debug("Initiating MFA email verification")

        # Optionally get configured MFA methods first
        try:
            async with self.session.get(
                f"{self.BASE_URL}/verification-srv/v2/setup/public/configured/list?sub={self.sub}"
            ) as list_response:
                if list_response.status == 200:
                    configured = await list_response.json()
                    email_methods = [m for m in configured.get('data', []) if m.get('verification_type') == 'EMAIL']
                    if email_methods:
                        self.medium_id = email_methods[0].get('id')
                        _LOGGER.debug(f"Found configured email MFA method: {self.medium_id}")
        except Exception as e:
            _LOGGER.debug(f"Could not get configured MFA methods: {e}, using default")

        payload = {
            "sub": self.sub,
            "medium_id": self.medium_id or "101e2b44-60d1-45e3-b649-f5ef7d75f5a0",
            "request_id": self.request_id,
            "usage_type": "MULTIFACTOR_AUTHENTICATION",
        }

        async with self.session.post(
            f"{self.BASE_URL}/verification-srv/v2/authenticate/initiate/email", json=payload
        ) as response:
            _LOGGER.debug(f"MFA initiation response status: {response.status}")
            if response.status == 200:
                data = await response.json()
                # Extract exchange_id and status_id from response
                response_data = data.get("data", {})
                exchange_id_data = response_data.get("exchange_id", {})
                self.exchange_id = exchange_id_data.get("exchange_id")
                self.status_id = response_data.get("status_id")
                masked_email = response_data.get("medium_text", "your email")

                _LOGGER.info(f"MFA code sent to: {masked_email}")
                _LOGGER.debug(f"Exchange ID: {self.exchange_id}")
                return True
            _LOGGER.warning(f"MFA initiation failed with status: {response.status}")
            return False

    async def verify_mfa_code(self, code: str) -> bool:
        """Verify MFA code."""
        if not self.exchange_id or not self.sub:
            raise ValueError("Must call initiate_mfa_email() first")

        _LOGGER.debug("Verifying MFA code")
        _LOGGER.debug(f"Using exchange_id: {self.exchange_id}, status_id: {self.status_id}")
        
        payload = {
            "pass_code": code,
            "exchange_id": self.exchange_id,
            "sub": self.sub
        }

        async with self.session.post(
            f"{self.BASE_URL}/verification-srv/v2/authenticate/authenticate/email", json=payload
        ) as response:
            _LOGGER.debug(f"MFA verification response status: {response.status}")
            if response.status == 200:
                data = await response.json()
                success = data.get("success", False)
                if success:
                    _LOGGER.info("MFA code verified successfully")
                    # Note: status_id should already be set from initiate_mfa_email
                    # But let's log it to be sure
                    _LOGGER.debug(f"MFA verified, status_id is: {self.status_id}")
                    return True
                else:
                    error_msg = data.get("error", {}).get("error", "Unknown error")
                    _LOGGER.warning(f"MFA verification failed: {error_msg}")
                    return False
            response_text = await response.text()
            _LOGGER.warning(f"MFA verification failed with status: {response.status}, body: {response_text}")
            return False

    async def complete_mfa_login(self) -> bool:
        """Complete MFA login and get authorization code."""
        from urllib.parse import urlparse, parse_qs

        if not self.track_id or not self.status_id or not self.sub:
            raise ValueError("Must complete MFA verification first")

        _LOGGER.debug("Completing MFA login to get authorization code")
        _LOGGER.debug(f"Using track_id: {self.track_id}, request_id: {self.request_id}, status_id: {self.status_id}")

        # Use form data with all required fields
        # Try using request_id first if available, otherwise fall back to track_id
        request_id_to_use = self.request_id if self.request_id else self.track_id
        
        data = {
            "status_id": self.status_id,
            "track_id": self.track_id,
            "requestId": request_id_to_use,
            "sub": self.sub,
            "verificationType": "EMAIL"
        }

        async with self.session.post(
            f"{self.BASE_URL}/login-srv/precheck/continue/{self.track_id}", data=data, allow_redirects=False
        ) as response:
            _LOGGER.debug(f"MFA completion response status: {response.status}")
            
            # Log the response body for debugging on failure
            if response.status != 302:
                response_text = await response.text()
                _LOGGER.warning(f"MFA completion failed. Status: {response.status}, Body: {response_text}")
                _LOGGER.debug(f"Request data was: {data}")
                return False
                
            if response.status == 302:
                location = response.headers.get("Location", "")
                parsed = urlparse(location)
                params = parse_qs(parsed.query)

                self.code = params.get("code", [None])[0]
                if self.code:
                    _LOGGER.info("Authorization code obtained")
                    return True
                else:
                    _LOGGER.warning("No authorization code in redirect response")
                    return False

    async def get_tokens(self) -> dict[str, Any]:
        """Exchange authorization code for tokens."""
        if not self.code:
            raise ValueError("Must complete login flow first")

        _LOGGER.debug("Exchanging authorization code for tokens")
        payload = {
            "grant_type": "authorization_code",
            "code": self.code,
            "redirect_uri": self.REDIRECT_URI,
            "client_id": self.CLIENT_ID,
            "code_verifier": self.code_verifier,
        }

        async with self.session.post(
            f"{self.BASE_URL}/token-srv/token", json=payload
        ) as response:
            if response.status == 200:
                data = await response.json()
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                self.sid = data.get("sid")
                expires_in = data.get("expires_in", 86400)
                self.expires_at = datetime.now() + timedelta(seconds=expires_in)
                _LOGGER.info(f"Tokens obtained successfully, expires in {expires_in}s")
                return data
            raise ValueError(f"Token exchange failed: {response.status}")

    async def refresh_access_token(self) -> dict[str, Any]:
        """Refresh the access token."""
        if not self.refresh_token:
            raise ValueError("No refresh token available")

        _LOGGER.debug("Refreshing access token")
        payload = {"grant_type": "refresh_token", "refresh_token": self.refresh_token, "client_id": self.CLIENT_ID}

        async with self.session.post(
            f"{self.BASE_URL}/token-srv/token", json=payload
        ) as response:
            if response.status == 200:
                data = await response.json()
                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")
                self.sid = data.get("sid")
                expires_in = data.get("expires_in", 86400)
                self.expires_at = datetime.now() + timedelta(seconds=expires_in)
                _LOGGER.info(f"Token refreshed successfully, expires in {expires_in}s")
                return data
            raise ValueError(f"Token refresh failed: {response.status}")

    async def get_valid_token(self) -> str:
        """Get a valid access token, refreshing if needed."""
        if not self.access_token:
            raise ValueError("No access token available")

        # Refresh if token expires in less than 5 minutes
        if self.expires_at and datetime.now() >= self.expires_at - timedelta(minutes=5):
            _LOGGER.debug("Token expires soon, triggering automatic refresh")
            await self.refresh_access_token()
        else:
            _LOGGER.debug("Token still valid, no refresh needed")

        return self.access_token

    async def introspect_token(self) -> dict[str, Any]:
        """Introspect the access token."""
        token = await self.get_valid_token()

        async with self.session.post(
            f"{self.BASE_URL}/token-srv/introspect",
            json={"token": token},
            headers={**self.IOS_HEADERS, "Content-Type": "application/json"},
        ) as response:
            if response.status == 200:
                data = await response.json()
                if data.get("active"):
                    _LOGGER.debug("Token introspection successful - token is active")
                    return data
                raise ValueError("Token is not active")
            raise ValueError(f"Token introspection failed: {response.status}")

    async def get_install_data(self, email: str, install_id: str) -> dict[str, Any]:
        """Get installation data from API."""
        token = await self.get_valid_token()

        _LOGGER.debug(f"Fetching installation data for install_id: {install_id}")
        params = {"demand": install_id, "installsList": install_id}

        async with self.session.get(
            f"https://api.nea2aws.aws.rehau.cloud/v2/users/{email}/getDataofInstall",
            headers={**self.IOS_HEADERS, "Authorization": token},
            params=params,
        ) as response:
            _LOGGER.debug(f"Installation data response status: {response.status}")
            _LOGGER.debug(f"Response content-type: {response.content_type}")
            
            if response.status in [200, 201]:
                # Some responses might be text/plain but contain JSON
                try:
                    # Try to parse as JSON regardless of content-type
                    text = await response.text()
                    _LOGGER.debug(f"Response body (first 200 chars): {text[:200]}")
                    data = json.loads(text)
                    
                    if data.get("success"):
                        zones_count = len(data.get("data", {}).get("zones", []))
                        _LOGGER.info(f"Installation data retrieved successfully, found {zones_count} zones")
                        return data.get("data", {})
                    raise ValueError(f"API returned success=false: {data}")
                except json.JSONDecodeError as e:
                    _LOGGER.error(f"Failed to parse response as JSON: {e}")
                    _LOGGER.error(f"Response body: {text}")
                    raise ValueError(f"Invalid JSON response from API: {e}")
            
            # Log error response
            error_text = await response.text()
            _LOGGER.error(f"Failed to get install data. Status: {response.status}, Body: {error_text}")
            raise ValueError(f"Failed to get install data: {response.status}")
