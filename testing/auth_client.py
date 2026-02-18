import requests
import hashlib
import base64
import secrets
import json
import os
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse


class RehauAuthClient:
    BASE_URL = "https://accounts.rehau.com"
    CLIENT_ID = "3f5d915d-a06f-42b9-89cc-2e5d63aa96f1"
    REDIRECT_URI = "https://rehau-smartheating-email-gallery-public.s3.eu-central-1.amazonaws.com/publicimages/preprod/rehau.jpg"
    TOKEN_FILE = "rehau_tokens.json"

    # iOS app headers to mimic the mobile app
    IOS_HEADERS = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": "app://ios.neasmart.de",
        "Connection": "keep-alive"
    }

    def __init__(self):
        self.session = requests.Session()
        # Set default headers for all requests
        self.session.headers.update(self.IOS_HEADERS)

        self.code_verifier = None
        self.code_challenge = None
        self.request_id = None
        self.track_id = None
        self.sub = None
        self.exchange_id = None
        self.status_id = None
        self.medium_id = None
        self.nonce = None
        # Generate PKCE parameters at initialization
        self._generate_pkce_pair()

    def _generate_pkce_pair(self):
        """Generate PKCE code verifier and challenge"""
        self.code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode('utf-8').rstrip('=')
        self.code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(self.code_verifier.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')
        self.nonce = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode('utf-8').rstrip('=')
        return self.code_verifier, self.code_challenge

    def start_authorization_flow(self) -> str:
        """
        Step 0: Start OAuth authorization flow with PKCE
        Returns the request_id to use in subsequent requests
        """
        params = {
            "client_id": self.CLIENT_ID,
            "redirect_uri": self.REDIRECT_URI,
            "response_type": "code",
            "scope": "email roles profile offline_access groups",
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            "nonce": self.nonce
        }

        response = self.session.get(
            f"{self.BASE_URL}/authz-srv/authz",
            params=params,
            allow_redirects=False
        )

        if response.status_code == 302:
            location = response.headers.get('location', '')
            parsed = urlparse(location)
            params_parsed = parse_qs(parsed.query)
            self.request_id = params_parsed.get('requestId', [None])[0]
            print(f"Authorization flow started. Request ID: {self.request_id}")
            return self.request_id
        else:
            raise Exception(f"Failed to start authorization: {response.status_code} - {response.text}")

    def login(self, username: str, password: str) -> dict:
        """
        Step 1: Perform initial login with username and password
        Returns redirect information for MFA
        """
        if not self.request_id:
            raise Exception("Must call start_authorization_flow() first")

        data = {
            "username": username,
            "username_type": "email",
            "password": password,
            "requestId": self.request_id,
            "rememberMe": "true"
        }

        response = self.session.post(
            f"{self.BASE_URL}/login-srv/login",
            data=data,
            allow_redirects=False
        )

        if response.status_code == 302:
            # Extract track_id, sub, and requestId from redirect location
            location = response.headers.get('location', '')
            print(f"Debug - Redirect location: {location}")

            parsed = urlparse(location)
            params = parse_qs(parsed.query)
            print(f"Debug - Parsed params: {params}")

            self.track_id = params.get('track_id', [None])[0]
            self.sub = params.get('sub', [None])[0]
            # Keep the original request_id if not in redirect
            if 'requestId' in params:
                self.request_id = params.get('requestId', [None])[0]

            print(f"Login successful. MFA required.")
            print(f"Track ID: {self.track_id}")
            print(f"Sub: {self.sub}")
            print(f"Request ID: {self.request_id}")

            if not self.track_id or not self.sub:
                raise Exception(f"Missing track_id or sub in redirect. Location: {location}")

            return {
                "status": "mfa_required",
                "track_id": self.track_id,
                "sub": self.sub,
                "request_id": self.request_id
            }
        else:
            raise Exception(f"Login failed: {response.status_code} - {response.text}")

    def initiate_mfa_email(self) -> dict:
        """
        Step 2: Initiate MFA email verification
        This sends the MFA code to the user's email
        """
        if not self.sub or not self.request_id:
            raise Exception("Must call login() first")

        # Get configured MFA methods first (optional, but mirrors the real flow)
        list_response = self.session.get(
            f"{self.BASE_URL}/verification-srv/v2/setup/public/configured/list?sub={self.sub}"
        )

        if list_response.status_code == 200:
            configured = list_response.json()
            email_methods = [m for m in configured.get('data', []) if m.get('verification_type') == 'EMAIL']
            if email_methods:
                self.medium_id = email_methods[0].get('id')

        # Initiate email MFA
        payload = {
            "sub": self.sub,
            "medium_id": self.medium_id or "101e2b44-60d1-45e3-b649-f5ef7d75f5a0",
            "request_id": self.request_id,
            "usage_type": "MULTIFACTOR_AUTHENTICATION"
        }

        response = self.session.post(
            f"{self.BASE_URL}/verification-srv/v2/authenticate/initiate/email",
            json=payload
        )

        if response.status_code == 200:
            data = response.json()
            self.exchange_id = data['data']['exchange_id']['exchange_id']
            self.status_id = data['data']['status_id']
            masked_email = data['data'].get('medium_text', 'your email')

            print(f"MFA code sent to: {masked_email}")
            print(f"Exchange ID: {self.exchange_id}")
            return {
                "status": "mfa_code_sent",
                "exchange_id": self.exchange_id,
                "status_id": self.status_id,
                "email": masked_email
            }
        else:
            raise Exception(f"Failed to initiate MFA: {response.status_code} - {response.text}")

    def verify_mfa_code(self, code: str) -> dict:
        """
        Step 3: Verify the MFA code entered by the user
        """
        if not self.exchange_id or not self.sub:
            raise Exception("Must call initiate_mfa_email() first")

        payload = {
            "pass_code": code,
            "exchange_id": self.exchange_id,
            "sub": self.sub
        }

        response = self.session.post(
            f"{self.BASE_URL}/verification-srv/v2/authenticate/authenticate/email",
            json=payload
        )

        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print("MFA code verified successfully")
                return {"status": "mfa_verified"}
            else:
                raise Exception(f"MFA verification failed: {data.get('error', {}).get('error', 'Unknown error')}")
        else:
            error_data = response.json()
            raise Exception(f"MFA verification failed: {error_data.get('error', {}).get('error', 'Unknown error')}")

    def complete_mfa_login(self) -> dict:
        """
        Step 4: Complete the login after MFA verification
        This continues the precheck flow
        """
        if not self.track_id or not self.status_id or not self.sub:
            raise Exception("Must complete MFA verification first")

        data = {
            "status_id": self.status_id,
            "track_id": self.track_id,
            "requestId": self.track_id,
            "sub": self.sub,
            "verificationType": "EMAIL"
        }

        response = self.session.post(
            f"{self.BASE_URL}/login-srv/precheck/continue/{self.track_id}",
            data=data,
            allow_redirects=False
        )

        if response.status_code == 302:
            location = response.headers.get('location', '')
            parsed = urlparse(location)
            params = parse_qs(parsed.query)

            auth_code = params.get('code', [None])[0]

            print("Login flow completed, authorization code received")
            return {
                "status": "auth_code_received",
                "code": auth_code
            }
        else:
            raise Exception(f"Failed to complete login: {response.status_code} - {response.text}")

    def get_tokens(self, auth_code: str) -> dict:
        """
        Step 5: Exchange authorization code for access token
        """
        if not self.code_verifier:
            raise Exception("Code verifier not initialized")

        payload = {
            "grant_type": "authorization_code",
            "client_id": self.CLIENT_ID,
            "redirect_uri": self.REDIRECT_URI,
            "code_verifier": self.code_verifier,
            "code": auth_code
        }

        response = self.session.post(
            f"{self.BASE_URL}/token-srv/token",
            json=payload
        )

        if response.status_code == 200:
            tokens = response.json()
            print("Access token received successfully")
            return tokens
        else:
            raise Exception(f"Failed to get tokens: {response.status_code} - {response.text}")

    def refresh_access_token(self, refresh_token: str) -> dict:
        """
        Refresh the access token using refresh token
        """
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.CLIENT_ID,
            "refresh_token": refresh_token
        }

        response = self.session.post(
            f"{self.BASE_URL}/token-srv/token",
            json=payload
        )

        if response.status_code == 200:
            tokens = response.json()
            print("Access token refreshed successfully")
            return tokens
        else:
            raise Exception(f"Failed to refresh token: {response.status_code} - {response.text}")

    def save_tokens(self, tokens: dict):
        """Save tokens to file with expiration time"""
        token_data = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_in": tokens["expires_in"],
            "token_type": tokens["token_type"],
            "sub": tokens["sub"],
            "sid": tokens.get("sid"),
            "identity_id": tokens.get("identity_id"),
            "expires_at": (datetime.now() + timedelta(seconds=tokens["expires_in"])).isoformat()
        }

        with open(self.TOKEN_FILE, 'w') as f:
            json.dump(token_data, f, indent=2)
        print(f"Tokens saved to {self.TOKEN_FILE}")

    def load_tokens(self) -> dict:
        """Load tokens from file"""
        if not os.path.exists(self.TOKEN_FILE):
            return None

        with open(self.TOKEN_FILE, 'r') as f:
            return json.load(f)

    def is_token_expired(self, token_data: dict) -> bool:
        """Check if token is expired or will expire soon (within 5 minutes)"""
        if not token_data or "expires_at" not in token_data:
            return True

        expires_at = datetime.fromisoformat(token_data["expires_at"])
        # Consider expired if less than 5 minutes remaining
        return datetime.now() >= (expires_at - timedelta(minutes=5))

    def get_valid_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary
        Returns the access token string
        """
        token_data = self.load_tokens()

        if not token_data:
            raise Exception("No tokens found. Please login first.")

        if self.is_token_expired(token_data):
            print("Token expired or expiring soon, refreshing...")
            try:
                new_tokens = self.refresh_access_token(token_data["refresh_token"])
                self.save_tokens(new_tokens)
                return new_tokens["access_token"]
            except Exception as e:
                raise Exception(f"Failed to refresh token: {e}. Please login again.")
        else:
            print("Using existing valid token")
            return token_data["access_token"]

    def introspect_token(self, force_refresh: bool = False) -> dict:
        """
        Introspect (validate) the access token
        This should be called before connecting to MQTT

        Args:
            force_refresh: If True, refresh the token before introspection
        """
        # Force refresh token if requested
        if force_refresh:
            token_data = self.load_tokens()
            if token_data and token_data.get("refresh_token"):
                print("Refreshing token before introspection...")
                try:
                    new_tokens = self.refresh_access_token(token_data["refresh_token"])
                    self.save_tokens(new_tokens)
                    access_token = new_tokens["access_token"]
                except Exception as e:
                    print(f"Warning: Token refresh failed: {e}")
                    access_token = self.get_valid_token()
            else:
                access_token = self.get_valid_token()
        else:
            access_token = self.get_valid_token()

        response = self.session.post(
            f"{self.BASE_URL}/token-srv/introspect",
            json={"token": access_token},
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            data = response.json()
            print(f"Introspection response: {json.dumps(data, indent=2)}")
            if data.get("active"):
                print("✅ Token introspection successful - token is active")
                return data
            else:
                raise Exception(f"Token is not active. Response: {data}")
        else:
            raise Exception(f"Token introspection failed: {response.status_code} - {response.text}")

    def get_install_data(self, email: str, install_id: str = None) -> dict:
        """
        Get installation data from API
        This must be called before connecting to MQTT
        Returns installation data including devices and hash

        Args:
            email: User email
            install_id: Installation ID (required - get from API or environment)
        """
        if not install_id:
            raise ValueError("install_id is required. Set INSTALL_ID environment variable or pass as parameter.")

        access_token = self.get_valid_token()

        # Call with install_id
        params = {
            "demand": install_id,
            "installsList": install_id
        }

        response = self.session.get(
            f"https://api.nea2aws.aws.rehau.cloud/v2/users/{email}/getDataofInstall",
            headers={"Authorization": access_token},
            params=params
        )

        if response.status_code in [200, 201]:
            data = response.json()
            if data.get("success"):
                return data.get("data", {})
            else:
                raise Exception(f"API returned success=false: {data}")
        else:
            raise Exception(f"Failed to get install data: {response.status_code} - {response.text}")

    def full_login_flow(self, username: str, password: str) -> dict:
        """
        Complete login flow with interactive MFA code input
        """
        print("=== Starting Rehau Login Flow ===\n")

        # Step 0: Start OAuth authorization flow
        print("Step 0: Starting OAuth authorization flow...")
        self.start_authorization_flow()
        print()

        # Step 1: Login with credentials
        print("Step 1: Logging in with credentials...")
        login_result = self.login(username, password)
        print()

        # Step 2: Initiate MFA
        print("Step 2: Initiating MFA email verification...")
        mfa_init_result = self.initiate_mfa_email()
        print()

        # Step 3: Get MFA code from user
        print("Step 3: Waiting for MFA code...")
        mfa_code = input("Enter the MFA code from your email: ").strip()
        print()

        # Step 4: Verify MFA code
        print("Step 4: Verifying MFA code...")
        verify_result = self.verify_mfa_code(mfa_code)
        print()

        # Step 5: Complete login
        print("Step 5: Completing login flow...")
        complete_result = self.complete_mfa_login()
        auth_code = complete_result['code']
        print()

        # Step 6: Get tokens
        print("Step 6: Exchanging authorization code for tokens...")
        tokens = self.get_tokens(auth_code)
        print()

        print("=== Login Flow Complete ===\n")
        return tokens


if __name__ == '__main__':
    client = RehauAuthClient()

    # Check if we have existing tokens
    existing_tokens = client.load_tokens()

    if existing_tokens and not client.is_token_expired(existing_tokens):
        print("Found valid existing tokens!")
        print(f"Token expires at: {existing_tokens['expires_at']}")
        use_existing = input("Use existing token? (y/n): ").strip().lower()

        if use_existing == 'y':
            print("\n=== Using Existing Token ===")
            print(f"Access Token: {existing_tokens['access_token'][:50]}...")
            print(f"Sub: {existing_tokens['sub']}")
            exit(0)

    # Perform login flow
    username = input("Enter your email: ").strip()
    password = input("Enter your password: ").strip()

    try:
        tokens = client.full_login_flow(username, password)

        # Save tokens
        client.save_tokens(tokens)

        print("\n=== Authentication Successful ===")
        print(f"Access Token: {tokens['access_token'][:50]}...")
        print(f"Refresh Token: {tokens['refresh_token']}")
        print(f"Expires In: {tokens['expires_in']} seconds")
        print(f"Sub: {tokens['sub']}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
