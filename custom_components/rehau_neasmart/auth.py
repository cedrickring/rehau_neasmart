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
        self.medium_id = None
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
        _LOGGER.debug("Starting OAuth authorization flow")
        params = {
            "response_type": "code",
            "client_id": self.CLIENT_ID,
            "redirect_uri": self.REDIRECT_URI,
            "scope": "email roles profile offline_access groups",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "nonce": self.nonce,
        }

        async with self.session.get(
            f"{self.BASE_URL}/authorize", params=params, headers=self.IOS_HEADERS, allow_redirects=False
        ) as response:
            _LOGGER.debug(f"Authorization response status: {response.status}")
            if response.status == 302:
                location = response.headers.get("Location", "")
                if "request_id=" in location:
                    params_str = location.split("?")[1] if "?" in location else ""
                    for param in params_str.split("&"):
                        if param.startswith("request_id="):
                            self.request_id = param.split("=")[1]
                            _LOGGER.debug(f"Got request_id: {self.request_id}")
                            break

    async def login(self, username: str, password: str) -> bool:
        """Login with username and password."""
        _LOGGER.debug(f"Attempting login for user: {username}")
        if not self.request_id:
            await self.start_authorization_flow()

        payload = {"username": username, "password": password, "request_id": self.request_id}

        async with self.session.post(
            f"{self.BASE_URL}/login-srv/login", json=payload, headers=self.IOS_HEADERS, allow_redirects=False
        ) as response:
            _LOGGER.debug(f"Login response status: {response.status}")
            if response.status == 302:
                location = response.headers.get("Location", "")
                params_str = location.split("?")[1] if "?" in location else ""
                params = {}
                for param in params_str.split("&"):
                    if "=" in param:
                        key, value = param.split("=", 1)
                        params[key] = value.replace("&amp;", "&")

                self.sub = params.get("sub")
                self.request_id = params.get("request_id")
                _LOGGER.debug("Login successful")
                return True
            _LOGGER.warning(f"Login failed with status: {response.status}")
            return False

    async def initiate_mfa_email(self) -> bool:
        """Initiate MFA email verification."""
        if not self.sub or not self.request_id:
            raise ValueError("Must call login() first")

        _LOGGER.debug("Initiating MFA email verification")
        payload = {
            "sub": self.sub,
            "medium_id": self.medium_id or "101e2b44-60d1-45e3-b649-f5ef7d75f5a0",
            "request_id": self.request_id,
            "usage_type": "MULTIFACTOR_AUTHENTICATION",
        }

        async with self.session.post(
            f"{self.BASE_URL}/verification-srv/v2/authenticate/initiate/email", json=payload, headers=self.IOS_HEADERS
        ) as response:
            _LOGGER.debug(f"MFA initiation response status: {response.status}")
            if response.status == 200:
                data = await response.json()
                success = data.get("success", False)
                _LOGGER.debug(f"MFA email initiated: {success}")
                return success
            _LOGGER.warning(f"MFA initiation failed with status: {response.status}")
            return False

    async def verify_mfa_code(self, code: str) -> bool:
        """Verify MFA code."""
        _LOGGER.debug("Verifying MFA code")
        payload = {
            "sub": self.sub,
            "medium_id": self.medium_id or "101e2b44-60d1-45e3-b649-f5ef7d75f5a0",
            "request_id": self.request_id,
            "usage_type": "MULTIFACTOR_AUTHENTICATION",
            "code": code,
        }

        async with self.session.post(
            f"{self.BASE_URL}/verification-srv/v2/authenticate/authenticate/email", json=payload, headers=self.IOS_HEADERS
        ) as response:
            _LOGGER.debug(f"MFA verification response status: {response.status}")
            if response.status == 200:
                data = await response.json()
                success = data.get("success", False)
                _LOGGER.debug(f"MFA code verified: {success}")
                return success
            _LOGGER.warning(f"MFA verification failed with status: {response.status}")
            return False

    async def complete_mfa_login(self) -> bool:
        """Complete MFA login and get authorization code."""
        _LOGGER.debug("Completing MFA login to get authorization code")
        payload = {"request_id": self.request_id}

        async with self.session.post(
            f"{self.BASE_URL}/login-srv/precheck/continue", json=payload, headers=self.IOS_HEADERS, allow_redirects=False
        ) as response:
            _LOGGER.debug(f"MFA completion response status: {response.status}")
            if response.status == 302:
                location = response.headers.get("Location", "")
                if "code=" in location:
                    for param in location.split("?")[1].split("&"):
                        if param.startswith("code="):
                            self.code = param.split("=")[1]
                            _LOGGER.debug("Authorization code obtained")
                            return True
            _LOGGER.warning(f"Failed to complete MFA login with status: {response.status}")
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
            f"{self.BASE_URL}/token-srv/token", json=payload, headers=self.IOS_HEADERS
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
            f"{self.BASE_URL}/token-srv/token", json=payload, headers=self.IOS_HEADERS
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
            if response.status in [200, 201]:
                data = await response.json()
                if data.get("success"):
                    zones_count = len(data.get("data", {}).get("zones", []))
                    _LOGGER.info(f"Installation data retrieved successfully, found {zones_count} zones")
                    return data.get("data", {})
                raise ValueError(f"API returned success=false: {data}")
            raise ValueError(f"Failed to get install data: {response.status}")
