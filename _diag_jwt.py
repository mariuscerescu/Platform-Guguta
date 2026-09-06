"""Debug authlib expired-token validation."""
import time

from authlib.jose import JsonWebToken
from cryptography.hazmat.primitives.asymmetric import rsa

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
jwt = JsonWebToken(["RS256"])
now = int(time.time())
claims = {"iss": "https://x", "aud": "guguta-dev", "sub": "s",
          "exp": now - 3600, "iat": now - 3600}
token = jwt.encode({"alg": "RS256"}, claims, key)
decoded = jwt.decode(token, key)
print("decoded exp:", decoded.get("exp"))
try:
    decoded.validate(now=now, leeway=60)
    print("validate: PASSED (token expired accepted!)")
except Exception as exc:
    print("validate raised:", type(exc).__name__, exc)
