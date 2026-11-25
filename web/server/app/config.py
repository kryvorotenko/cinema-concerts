"""Settings from environment variables (compose.yaml, .env); one image runs every process."""

import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


INSTANCE = os.environ.get("INSTANCE", "local")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/app")
POOL_MIN = _int("POOL_MIN", 1)
POOL_SIZE = _int("POOL_SIZE", 10)
POOL_TIMEOUT_S = _float("POOL_TIMEOUT_S", 2.0)
STATEMENT_TIMEOUT_MS = _int("STATEMENT_TIMEOUT_MS", 2000)

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9094")
TOPIC_DOMAIN_EVENTS = os.environ.get("TOPIC_DOMAIN_EVENTS", "domain-events")
TOPIC_NOTIFICATIONS = os.environ.get("TOPIC_NOTIFICATIONS", "notifications")
TOPIC_TICKET_TELEMETRY = os.environ.get("TOPIC_TICKET_TELEMETRY", "ticket-telemetry")
HOLD_MINUTES = _int("HOLD_MINUTES", 10)
HOLD_MAX_SEATS = _int("HOLD_MAX_SEATS", 10)
HOLD_SWEEP_S = _float("HOLD_SWEEP_S", 5.0)
IDEMPOTENCY_TTL_S = _int("IDEMPOTENCY_TTL_S", 86400)
IDEMPOTENCY_PURGE_S = _float("IDEMPOTENCY_PURGE_S", 60.0)
IDEMPOTENCY_PURGE_BATCH = _int("IDEMPOTENCY_PURGE_BATCH", 500)
SESSION_COOKIE = os.environ.get("SESSION_COOKIE", "session")
SESSION_TTL_S = _int("SESSION_TTL_S", 3600)
SESSION_PURGE_S = _float("SESSION_PURGE_S", 60.0)
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "off") == "on"
WEB_API_TOKEN = os.environ.get("WEB_API_TOKEN", "dev-token")
WS_TICKET_TTL_SECONDS = _int("WS_TICKET_TTL_SECONDS", 30)
GROUP_ID = os.environ.get("GROUP_ID", INSTANCE)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
EXTERNAL_URL = os.environ.get("EXTERNAL_URL", "http://localhost:8090")
FLAGS_URL = os.environ.get("FLAGS_URL", "http://localhost:8099")
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "http://localhost:8180/realms/project")
OIDC_INTERNAL_URL = os.environ.get("OIDC_INTERNAL_URL", OIDC_ISSUER)
CLIENT_ORIGIN = os.environ.get("CLIENT_ORIGIN", "http://localhost:8081")

OTEL_ENABLED = os.environ.get("OTEL_ENABLED", "off") == "on"
OTEL_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

# experiment modes: what each value changes is yours to write
INVARIANT_MODE = os.environ.get("INVARIANT_MODE", "protected")
RATE_LIMIT_PER_MIN = _int("RATE_LIMIT_PER_MIN", 120)
JWT_REVOCATION = os.environ.get("JWT_REVOCATION", "on") == "on"

PROBLEM_BASE = os.environ.get("PROBLEM_BASE", "https://example.edu/problems/")

FAULTS = os.environ.get("FAULTS", "off") == "on"
FAULT_DIR = os.environ.get("FAULT_DIR", "/faults")
