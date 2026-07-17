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
]

# KEY=high-entropy-value (.env style), anywhere in the text, not just line start
_ENV_LINE = re.compile(
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
    text, n = _ENV_LINE.subn(_env_sub, text)
    # subn counts all matches; only count actual redactions
    if "[REDACTED:env]" in text and n:
        hits += text.count("[REDACTED:env]")
    return text, hits
