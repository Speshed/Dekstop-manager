import keyring
from typing import Optional

KEYRING_SERVICE = "LarixNexus"

def save_credential(username: str, credential_type: str, value: str) -> bool:
    """Save credential to system keyring.
    
    Args:
        username: User identifier
        credential_type: Type of credential (e.g., 'password', 'refresh_token', 'access_token')
        value: Credential value
    
    Returns:
        True if successful
    """
    try:
        key = f"{username}:{credential_type}"
        keyring.set_password(KEYRING_SERVICE, key, value)
        print(f"[KEYRING DEBUG] save_credential: saved {credential_type} for {username}")
        return True
    except Exception as e:
        print(f"[KEYRING DEBUG] save_credential ERROR: {e}")
        return False

def get_credential(username: str, credential_type: str) -> Optional[str]:
    """Get credential from system keyring.
    
    Args:
        username: User identifier
        credential_type: Type of credential
    
    Returns:
        Credential value or None
    """
    try:
        key = f"{username}:{credential_type}"
        result = keyring.get_password(KEYRING_SERVICE, key)
        if result:
            print(f"[KEYRING DEBUG] get_credential: found {credential_type} for {username}")
        else:
            print(f"[KEYRING DEBUG] get_credential: NOT found {credential_type} for {username}")
        return result
    except Exception as e:
        print(f"[KEYRING DEBUG] get_credential ERROR: {e}")
        return None

def delete_credential(username: str, credential_type: str) -> bool:
    """Delete credential from system keyring.
    
    Args:
        username: User identifier
        credential_type: Type of credential
    
    Returns:
        True if successful
    """
    try:
        key = f"{username}:{credential_type}"
        keyring.delete_password(KEYRING_SERVICE, key)
        return True
    except Exception:
        return False

def clear_all_credentials(username: str) -> None:
    """Clear all credentials for a user."""
    for cred_type in ['password', 'refresh_token', 'access_token']:
        try:
            delete_credential(username, cred_type)
        except Exception:
            pass

def debug_credentials_status(username: str) -> None:
    """Debug function to check what credentials are stored."""
    from .settings import load_settings
    
    print(f"\n{'='*60}")
    print(f"[CREDENTIALS DEBUG] Status for user: {username}")
    print(f"{'='*60}")
    
    for cred_type in ['password', 'refresh_token', 'access_token']:
        cred = get_credential(username, cred_type)
        if cred:
            print(f"  [+] {cred_type:15s}: FOUND ({cred[:10]}...)")
        else:
            print(f"  [-] {cred_type:15s}: NOT FOUND")
    
    settings = load_settings()
    print(f"\n[SETTINGS DEBUG] settings.json:")
    print(f"  last_username:  {settings.get('last_username', 'NOT SET')}")
    print(f"  remember_me:    {settings.get('remember_me', False)}")
    print(f"  auto_login:     {settings.get('auto_login', False)}")
    print(f"{'='*60}\n")
