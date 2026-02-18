#!/usr/bin/env python3
"""
Test automatic token refresh in get_valid_token() method

This script simulates an expired token by modifying the expiration time
and verifies that get_valid_token() automatically refreshes it.
"""
import json
from datetime import datetime, timedelta
from auth_client import RehauAuthClient


def main():
    print("=== Rehau Automatic Token Refresh Test ===\n")

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

        # Show current expiration
        current_expiry = token_data.get('expires_at')
        print(f"Current expiration: {current_expiry}")
    except Exception as e:
        print(f"❌ Error loading tokens: {e}")
        return

    # Step 2: Create a backup
    print("\nStep 2: Creating backup of tokens...")
    backup_data = token_data.copy()
    print("✅ Backup created")

    # Step 3: Simulate an expired token
    print("\nStep 3: Simulating expired token...")
    print("Setting expiration to 1 minute from now (triggers auto-refresh)")

    # Set expiration to 1 minute from now (within the 5-minute buffer)
    expired_time = datetime.now() + timedelta(minutes=1)
    token_data['expires_at'] = expired_time.isoformat()

    # Save the modified token
    with open(auth_client.TOKEN_FILE, 'w') as f:
        json.dump(token_data, f, indent=2)

    print(f"✅ Token expiration set to: {token_data['expires_at']}")
    print("   (This should trigger automatic refresh)")

    # Step 4: Call get_valid_token - should trigger refresh
    print("\nStep 4: Calling get_valid_token()...")
    print("Expected: Should automatically refresh the token")

    try:
        valid_token = auth_client.get_valid_token()
        print("✅ get_valid_token() completed successfully")

        # Check if token was refreshed
        new_token_data = auth_client.load_tokens()
        new_expiry = new_token_data.get('expires_at')

        print(f"\nNew expiration: {new_expiry}")

        # Compare expiration times
        if new_expiry != token_data['expires_at']:
            print("✅ Token was automatically refreshed!")

            # Calculate new expiration time
            new_expiry_dt = datetime.fromisoformat(new_expiry)
            hours_valid = (new_expiry_dt - datetime.now()).total_seconds() / 3600
            print(f"New token valid for: {hours_valid:.2f} hours")
        else:
            print("⚠️  Token was NOT refreshed (expiration unchanged)")

    except Exception as e:
        print(f"❌ get_valid_token() failed: {e}")

        # Restore backup
        print("\nRestoring backup tokens...")
        with open(auth_client.TOKEN_FILE, 'w') as f:
            json.dump(backup_data, f, indent=2)
        print("✅ Backup restored")
        return

    # Step 5: Verify new token works
    print("\nStep 5: Verifying new token with introspection...")
    try:
        introspect_result = auth_client.introspect_token()
        print("✅ Token introspection successful")
        print(f"Token is active: {introspect_result.get('active')}")
    except Exception as e:
        print(f"❌ Token verification failed: {e}")

    print("\n" + "="*60)
    print("✅ Automatic token refresh test completed!")
    print("="*60)

    # Show summary
    print("\nSummary:")
    print(f"  Original expiration: {backup_data.get('expires_at')}")
    print(f"  Simulated expiration: {expired_time.isoformat()}")
    print(f"  New expiration: {new_token_data.get('expires_at')}")
    print(f"  Refresh triggered: {'Yes' if new_token_data.get('expires_at') != expired_time.isoformat() else 'No'}")


if __name__ == "__main__":
    main()
