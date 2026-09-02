from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Redis storage so limits hold across multiple API processes (Spec 9.5).
# key_func is the default IP-based extractor. Spec 9.5 also says: "behind a
# proxy, read the client IP from the trusted forwarded header — do not trust
# X-Forwarded-For blindly." No reverse proxy is configured in this project
# yet, so that trusted-hop logic isn't built here — get_remote_address reads
# the direct connecting peer, which is correct until a proxy sits in front.
#
# key_style="endpoint" (hardening pass): slowapi's own default is "url" —
# it buckets by the literal request path, path parameters included. For
# every route this project rate-limits except one that was harmless by
# coincidence (no route with a path parameter had a limit yet). But
# GET /auth/check-username/{username} is rate-limited BECAUSE it's an
# enumeration surface (Spec 9.3), and enumerating usernames means varying
# the one thing "url" bucketing keys on — every distinct username silently
# got its own fresh bucket, so the limit never actually engaged for the
# attack it exists to stop. "endpoint" buckets by the view function's name
# instead, constant regardless of the path parameter.
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL, key_style="endpoint")
