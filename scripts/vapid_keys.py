"""Make a VAPID key pair for web push (app/push.py). Run once and put both lines in the server's environment:

    python scripts/vapid_keys.py

Keep the private key secret. Changing the pair later unsubscribes every device (players turn push on again).
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


key = ec.generate_private_key(ec.SECP256R1())
private = b64url(key.private_numbers().private_value.to_bytes(32, "big"))
public = b64url(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
print(f"VAPID_PUBLIC_KEY={public}")
print(f"VAPID_PRIVATE_KEY={private}")
