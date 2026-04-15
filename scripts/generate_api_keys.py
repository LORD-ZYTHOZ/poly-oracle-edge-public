"""
Generate Polymarket CLOB API credentials from your Polygon wallet.
Run once, save output to .env

Usage:
    PRIVATE_KEY=0x... python scripts/generate_api_keys.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

PRIVATE_KEY = os.environ.get("PRIVATE_KEY")
if not PRIVATE_KEY:
    print("ERROR: set PRIVATE_KEY env var first")
    print("  export PRIVATE_KEY=0xyour_private_key_here")
    sys.exit(1)

client = ClobClient(
    host="https://clob.polymarket.com",
    key=PRIVATE_KEY,
    chain_id=POLYGON,
)

creds = client.create_or_derive_api_creds()

print("\n=== Add these to your .env ===\n")
print(f"POLY_PRIVATE_KEY={PRIVATE_KEY}")
print(f"POLY_API_KEY={creds.api_key}")
print(f"POLY_API_SECRET={creds.api_secret}")
print(f"POLY_API_PASSPHRASE={creds.api_passphrase}")
print("\n==============================\n")
