#!/usr/bin/env python3
"""Generate a VAPID key pair for web push, replacing `npm run vapid`.

Usage: python scripts/vapid.py
"""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02


def main() -> None:
    v = Vapid02()
    v.generate_keys()
    pub_bytes = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    public_b64 = base64.urlsafe_b64encode(pub_bytes).decode().rstrip("=")
    private_pem = v.private_pem().decode()

    print("Add these to your .env (see .env.example):\n")
    print(f"VAPID_PUBLIC_KEY={public_b64}")
    print("VAPID_PRIVATE_KEY=<paste the PEM below as one env var, keeping the newlines>")
    print("VAPID_SUBJECT=mailto:you@example.com\n")
    print("--- VAPID_PRIVATE_KEY PEM ---")
    print(private_pem)


if __name__ == "__main__":
    main()
