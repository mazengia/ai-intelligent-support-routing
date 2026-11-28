import re


_PATTERNS = (
    (
        re.compile(
            r"\b(?:password|passcode|otp|verification code|one[- ]time code)"
            r"\s*(?::|=|\bis\b)\s*[A-Za-z0-9!@#$%^&*._-]{4,}\b",
            re.IGNORECASE,
        ),
        "[REDACTED_CREDENTIAL]",
    ),
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "[REDACTED_EMAIL]"),
    (
        re.compile(
            r"\b(?:account(?: number| no\.?)?|card number|customer id|member id|"
            r"national id|reference number|username|full name|date of birth|dob|address)"
            r"\s*[:=#-]\s*[A-Za-z0-9][A-Za-z0-9@._/-]*",
            re.IGNORECASE,
        ),
        "[REDACTED_IDENTIFIER]",
    ),
    (
        re.compile(
            r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)"
        ),
        "[REDACTED_NUMBER]",
    ),
    (re.compile(r"https?://\S+", re.IGNORECASE), "[REDACTED_URL]"),
)


def redact_pii(text: str) -> str:
    """Redact common direct identifiers and credentials before retaining text."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
