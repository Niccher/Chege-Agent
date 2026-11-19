import re

# Regular expressions for common secret signatures (SEC-08)
SECRET_PATTERNS = [
    # AWS Access Key ID
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    # GitHub Personal Access Token
    (re.compile(r"\bghp_[a-zA-Z0-9]{36}\b"), "[REDACTED_GITHUB_PAT]"),
    (re.compile(r"\bgithub_pat_[a-zA-Z0-9_]{82}\b"), "[REDACTED_GITHUB_TOKEN]"),
    # OpenAI / OpenRouter style API keys
    (re.compile(r"\bsk-[a-zA-Z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
    # Slack Tokens
    (re.compile(r"\bxox[baprs]-[0-9a-zA-Z]{10,48}\b"), "[REDACTED_SLACK_TOKEN]"),
    # Private Key blocks
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # Generic bearer tokens / basic auth in headers
    (
        re.compile(r"(?i)\bBearer\s+[a-zA-Z0-9_\-\.]{20,}\b"),
        "Bearer [REDACTED_BEARER_TOKEN]",
    ),
]


def scrub_secrets(text: str) -> str:
    """
    Scan and redact sensitive tokens and credentials from strings before
    logging or returning them to the model context.
    """
    if not text:
        return ""
    
    scrubbed = text
    for pattern, replacement in SECRET_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed
