#!/usr/bin/env python3
"""Quick LLM Gateway connection test."""
import os, sys
from dotenv import load_dotenv

load_dotenv()

def test_connection():
    errors = []

    # Check credentials
    creds = {k: os.getenv(k) for k in [
        'OAUTH_CLIENT_ID', 'OAUTH_CLIENT_SECRET', 'OAUTH_TENANT_ID',
        'OAUTH_SCOPE', 'LLM_MODEL_API_KEY', 'LLM_MODEL_BASE_URL', 'LLM_MODEL_NAME'
    ]}
    missing = [k for k, v in creds.items() if not v]
    if missing:
        return [f"Missing credentials: {', '.join(missing)}"]

    # Get OAuth token
    try:
        import requests
        resp = requests.post(
            f"https://login.microsoftonline.com/{creds['OAUTH_TENANT_ID']}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": creds['OAUTH_CLIENT_ID'],
                  "client_secret": creds['OAUTH_CLIENT_SECRET'], "scope": creds['OAUTH_SCOPE']},
            timeout=10
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
    except Exception as e:
        return [f"OAuth token error: {e}"]

    # Test LLM call
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=creds['LLM_MODEL_API_KEY'],
            base_url=creds['LLM_MODEL_BASE_URL'],
            default_headers={"Authorization": f"Bearer {token}", "X-LLM-Gateway-Key": creds['LLM_MODEL_API_KEY']}
        )
        client.chat.completions.create(
            model=creds['LLM_MODEL_NAME'],
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=5
        )
    except Exception as e:
        return [f"LLM API error: {type(e).__name__}: {e}"]

    return errors

if __name__ == "__main__":
    errors = test_connection()
    if errors:
        print("FAILED:", "; ".join(errors))
        sys.exit(1)
    print("OK")
