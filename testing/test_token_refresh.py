#!/usr/bin/env python3
"""
Test token refresh functionality

This script tests:
1. Loading existing tokens
2. Checking token expiration
3. Refreshing the access token
4. Verifying the new token works
"""
import json
from datetime import datetime
from auth_client import RehauAuthClient


def print_token_info(token_data: dict, label: str = "Token Info"):
    """Print token information."""
    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"{'='*60}")
    print(f"Access Token (first 20 chars): {token_data.get('access_token', 'N/A')[:20]}...")
    print(f"Refresh Token: {token_data.get('refresh_token', 'N/A')[:20]}...")
    print(f"Expires At: {token_data.get('expires_at', 'N/A')}")
    print(f"Session ID (sid): {token_data.get('sid', 'N/A')}")

    # Calculate time until expiration
    if token_data.get('expires_at'):
        try:
            expires_at = datetime.fromisoformat(token_data['expires_at'])
            now = datetime.now()
            time_left = expires_at - now
            hours = time_left.total_seconds() / 3600
            print(f"Time until expiration: {hours:.2f} hours")

            if hours < 0:
                print("⚠️  Token has EXPIRED")
            elif hours < 1:
                print("⚠️  Token expires SOON (less than 1 hour)")
            else:
                print("✅ Token is still valid")
        except Exception as e:
            print(f"Error parsing expiration time: {e}")


def main():
    print("=== Rehau Token Refresh Test ===\n")

    # Initialize auth client
    auth_client = RehauAuthClient()

    # Step 1: Load existing tokens
    print("Step 1: Loading existing tokens...")
    try:
        token_data = auth_client.load_tokens()
        if not token_data:
            print("❌ No tokens found. Please run 'python auth_client.py' first.")
            return
        print("✅ Tokens loaded successfully")
        print_token_info(token_data, "Current Token Info")
    except Exception as e:
        print(f"❌ Error loading tokens: {e}")
        return

    # Step 2: Check if token is expired
    print("\n\nStep 2: Checking token expiration...")
    is_expired = auth_client.is_token_expired(token_data)

    if is_expired:
        print("⚠️  Token is expired or expiring soon (within 5 minutes)")
        should_refresh = True
    else:
        print("✅ Token is still valid")
        # Ask user if they want to test refresh anyway
        response = input("\nDo you want to test refresh anyway? (y/n): ").strip().lower()
        should_refresh = response == 'y'

    if not should_refresh:
        print("\n✅ Token refresh test skipped - token is valid")

        # Test introspection
        print("\n\nStep 3: Testing token introspection...")
        try:
            introspect_result = auth_client.introspect_token()
            print("✅ Token introspection successful")
            print(f"Token is active: {introspect_result.get('active')}")
            print(f"Subject (sub): {introspect_result.get('sub')}")
            print(f"Identity (isub): {introspect_result.get('isub')}")
        except Exception as e:
            print(f"❌ Token introspection failed: {e}")
        return

    # Step 3: Refresh the token
    print("\n\nStep 3: Refreshing access token...")
    try:
        refresh_token = token_data.get('refresh_token')
        if not refresh_token:
            print("❌ No refresh token found in token file")
            return

        print(f"Using refresh token: {refresh_token[:20]}...")
        new_tokens = auth_client.refresh_access_token(refresh_token)
        print("✅ Token refresh successful!")

        # Save new tokens
        auth_client.save_tokens(new_tokens)
        print("✅ New tokens saved to file")

        # Print new token info
        new_token_data = auth_client.load_tokens()
        print_token_info(new_token_data, "New Token Info")

    except Exception as e:
        print(f"❌ Token refresh failed: {e}")
        print("\nPossible reasons:")
        print("  - Refresh token has expired")
        print("  - Refresh token has been revoked")
        print("  - Network connection issues")
        print("\nSolution: Delete rehau_tokens.json and run 'python auth_client.py' to re-authenticate")
        return

    # Step 4: Verify new token works
    print("\n\nStep 4: Verifying new token...")
    try:
        introspect_result = auth_client.introspect_token()
        print("✅ New token is valid!")
        print(f"Token is active: {introspect_result.get('active')}")
        print(f"Subject (sub): {introspect_result.get('sub')}")
        print(f"Identity (isub): {introspect_result.get('isub')}")
        print(f"Session ID: {introspect_result.get('sid')}")
    except Exception as e:
        print(f"❌ New token verification failed: {e}")
        return

    # Step 5: Test getting valid token (should not refresh again)
    print("\n\nStep 5: Testing get_valid_token() method...")
    try:
        valid_token = auth_client.get_valid_token()
        print("✅ get_valid_token() returned successfully")
        print(f"Token (first 20 chars): {valid_token[:20]}...")
    except Exception as e:
        print(f"❌ get_valid_token() failed: {e}")

    print("\n" + "="*60)
    print("✅ Token refresh test completed successfully!")
    print("="*60)


if __name__ == "__main__":
    main()
