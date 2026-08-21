
import json
import sys
from pathlib import Path

TOKEN_PATH   = Path(__file__).parent / "token.json"
CLIENT_PATH  = Path(__file__).parent / "oauth_client.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def main() -> None:
    if not CLIENT_PATH.is_file():
        print("ERROR: oauth_client.json not found.")
        print()
        print("Steps to create it:")
        print("  1. Go to https://console.cloud.google.com/apis/credentials")
        print("  2. Click 'Create Credentials' -> 'OAuth client ID'")
        print("  3. Application type: Desktop app -> click Create")
        print("  4. Click 'Download JSON', rename it to oauth_client.json")
        print("  5. Place oauth_client.json in the agent/ folder")
        print("  6. Run this script again: python oauth_login.py")
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import]

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_PATH), SCOPES)

    print()
    print("=" * 60)
    print("  STEP 1: Copy the URL below and open it in Chrome")
    print("          (use whichever profile/account you want)")
    print("=" * 60)
    print()

    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    auth_url, _ = flow.authorization_url(prompt="consent")

    print("Open this URL in Chrome (any profile/account):")
    print()
    print(auth_url)
    print()
    print("After clicking Allow, Google will show a code. Paste it here:")
    code = input("Enter the authorization code: ").strip()

    flow.fetch_token(code=code)
    creds = flow.credentials

    TOKEN_PATH.write_text(creds.to_json())
    print()
    print(f"token.json saved at: {TOKEN_PATH}")
    print("The agent will now create Google Sheets under your account.")
    print("You don't need to run this script again -- the token auto-refreshes.")


if __name__ == "__main__":
    main()
