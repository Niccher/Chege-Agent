from backend.app.security.scrubber import scrub_secrets


def test_scrub_aws_key():
    text = "Error accessing S3 with key AKIAIOSFODNN7EXAMPLE in bucket."
    scrubbed = scrub_secrets(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in scrubbed
    assert "[REDACTED_AWS_KEY]" in scrubbed


def test_scrub_github_pat():
    text = "Cloning with token ghp_123456789012345678901234567890123456"
    scrubbed = scrub_secrets(text)
    assert "ghp_123456789012345678901234567890123456" not in scrubbed
    assert "[REDACTED_GITHUB_PAT]" in scrubbed


def test_scrub_openai_api_key():
    text = "Authorization failed for sk-abcdef1234567890abcdef1234567890"
    scrubbed = scrub_secrets(text)
    assert "sk-abcdef1234567890abcdef1234567890" not in scrubbed
    assert "[REDACTED_API_KEY]" in scrubbed


def test_scrub_private_key():
    text = """
    -----BEGIN RSA PRIVATE KEY-----
    MIIEowIBAAKCAQEA0Y1+
    -----END RSA PRIVATE KEY-----
    """
    scrubbed = scrub_secrets(text)
    assert "MIIEowIBAAKCAQEA0Y1+" not in scrubbed
    assert "[REDACTED_PRIVATE_KEY]" in scrubbed


def test_clean_text_remains_unchanged():
    text = "Just a standard log message without any secrets."
    assert scrub_secrets(text) == text
