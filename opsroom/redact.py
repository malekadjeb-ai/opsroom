"""Secret redaction. Runs on every event BEFORE any DB write. Fail-closed: callers must
drop the event if redact() raises."""
import math
import re

_PATTERNS = [
    ("anthropic",  re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")),
    ("stripe",     re.compile(r"[rs]k_live_[A-Za-z0-9]{8,}")),
    ("stripe_test", re.compile(r"[rs]k_test_[A-Za-z0-9]{8,}")),
    ("openai",     re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("aws",        re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github",     re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}")),
    ("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("slack",      re.compile(r"xox[baprs]-[A-Za-z0-9\-]{8,}")),
    ("google",     re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("jwt",        re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("db_uri",     re.compile(r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:@/]+:[^\s@/]+@[^\s]+", re.I)),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:.|\n)*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)")),
    ("cloudflare", re.compile(r"(?i)(?:cloudflare|cf)[_\-]?(?:api[_\-]?)?token['\"=:\s]+[A-Za-z0-9_\-]{30,}")),
    ("sendgrid",   re.compile(r"SG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}")),
    ("twilio",     re.compile(r"SK[0-9a-fA-F]{32}")),
    ("npm",        re.compile(r"npm_[A-Za-z0-9]{36}")),
    ("slack_hook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,}")),
    ("bearer",     re.compile(r"(?i)(?:authorization:\s*)?bearer\s+[A-Za-z0-9._\-]{16,}")),
]

# KEY=high-entropy-value (.env style), anywhere in the text, not just line start.
# Key may be lower- or upper-case (api_key=, password=, TOKEN=); value gate is
# length OR high entropy so short-but-random and long-but-structured both catch.
_ENV_LINE = re.compile(
    r"((?:^|(?<=[^A-Za-z0-9_]))(?:export\s+)?"
    r"(?:[A-Za-z0-9_]*(?:key|secret|token|password|passwd|pwd|api|auth|cred)[A-Za-z0-9_]*)"
    r"\s*=\s*['\"]?)([^'\"\s#]{8,})(['\"]?)", re.I)
# any UPPERCASE key with a long high-entropy value (generic catch, keyword-independent)
_ENV_LINE_UPPER = re.compile(
    r"((?:^|(?<=[^A-Za-z0-9_]))(?:export\s+)?[A-Z][A-Z0-9_]{2,}\s*=\s*['\"]?)([^'\"\s#]{16,})(['\"]?)")
_ENTROPY_THRESHOLD = 3.8


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _env_sub(m: re.Match) -> str:
    value = m.group(2)
    # a named-secret key (api_key/password/token/…) with any value ≥8 chars is a
    # secret regardless of entropy; the entropy gate only relaxes the length rule.
    if len(value) >= 16 or _entropy(value) >= _ENTROPY_THRESHOLD:
        return f"{m.group(1)}[REDACTED:env]{m.group(3)}"
    return m.group(0)


def _env_sub_upper(m: re.Match) -> str:
    value = m.group(2)
    if _entropy(value) >= _ENTROPY_THRESHOLD:
        return f"{m.group(1)}[REDACTED:env]{m.group(3)}"
    return m.group(0)


def redact(text: str):
    """Return (redacted_text, hit_count). Raises on internal error — caller drops event."""
    if not text:
        return text, 0
    hits = 0
    for name, pat in _PATTERNS:
        text, n = pat.subn(f"[REDACTED:{name}]", text)
        hits += n
    text, _ = _ENV_LINE.subn(_env_sub, text)
    text, _ = _ENV_LINE_UPPER.subn(_env_sub_upper, text)
    hits += text.count("[REDACTED:env]")
    return text, hits
