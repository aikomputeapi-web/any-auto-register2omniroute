import pytest

from core.email_domain_policy import validate_email_domain_policy


def test_policy_disabled_skips_validation():
    validate_email_domain_policy("user@example.com", {"email_domain_rule_enabled": "0"})


def test_policy_checks_domain_level_count():
    with pytest.raises(ValueError, match="At least required 4 class"):
        validate_email_domain_policy(
            "user@a1b2.example.com",
            {
                "email_domain_rule_enabled": "1",
                "email_domain_level_count": "4",
            },
        )


def test_policy_checks_letter_and_digit_count():
    with pytest.raises(ValueError, match="contains at least 2 English letters and 2 numbers"):
        validate_email_domain_policy(
            "user@ab.example.com",
            {
                "email_domain_rule_enabled": "1",
                "email_domain_level_count": "2",
            },
        )


def test_policy_accepts_valid_n_level_domain():
    validate_email_domain_policy(
        "user@a1.b2.example.com",
        {
            "email_domain_rule_enabled": "1",
            "email_domain_level_count": "4",
        },
    )
