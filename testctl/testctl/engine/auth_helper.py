"""
Generate HS256 JWTs compatible with the Boundaryless auth gateway.

JWT structure mirrors what auth.boundaryless.com issues:
  uid   (int)    — auth server user ID; maps to users.auth_uid in the app DB
  sub   (str)    — string form of uid
  email (str)    — user email; used by syncUser() to link/create people records
  name  (str)    — display name
  role  (str)    — primary role string
  roles (list)   — all roles; synced into user_roles on each callback
  aud   (str)    — must match AUTH_APP_SLUG / jwt_aud in config/auth.php
  iat / exp      — standard JWT timing claims
"""

import base64
import hashlib
import hmac
import json
import time


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate(
    secret: str,
    uid: int,
    email: str,
    name: str,
    role: str,
    roles: list[str],
    aud: str,
    ttl: int = 3600,
) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    payload = _b64url(json.dumps({
        "uid":   uid,
        "sub":   str(uid),
        "email": email,
        "name":  name,
        "role":  role,
        "roles": roles,
        "aud":   aud,
        "iat":   now,
        "exp":   now + ttl,
    }, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    sig = _b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"
