from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Redis storage so limits hold across multiple API processes (Spec 9.5).
# key_func is the default IP-based extractor. Spec 9.5 also says: "behind a
# proxy, read the client IP from the trusted forwarded header — do not trust
# X-Forwarded-For blindly." No reverse proxy is configured in this project
# yet, so that trusted-hop logic isn't built here — get_remote_address reads
# the direct connecting peer, which is correct until a proxy sits in front.
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)
