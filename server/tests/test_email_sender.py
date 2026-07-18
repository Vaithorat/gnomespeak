import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handlers.email_sender import EmailSender


class TestEmailSender:
    def setup_method(self):
        self.config = MagicMock()
        secrets = {
            "smtp_server": "smtp.example.com",
            "smtp_port": "587",
            "smtp_username": "user@example.com",
            "smtp_password": "secret",
        }
        self.config.get_secret.side_effect = lambda key: secrets.get(key)
        self.sender = EmailSender(self.config)

    def test_invalid_recipient_rejected(self):
        result = self.sender.send("bad\naddr@example.com", "Hello", "Body")
        assert result["success"] is False
        assert "invalid" in result["message"].lower()

    def test_invalid_subject_rejected(self):
        result = self.sender.send("user@example.com", "Hi\r\nBcc: x@y.com", "Body")
        assert result["success"] is False
        assert "invalid header" in result["message"].lower()

    def test_ssl_used_for_port_465(self):
        self.config.get_secret.side_effect = lambda key: {
            "smtp_server": "smtp.example.com",
            "smtp_port": "465",
            "smtp_username": "user@example.com",
            "smtp_password": "secret",
        }.get(key)
        sender = EmailSender(self.config)

        with patch("handlers.email_sender.smtplib.SMTP_SSL") as mock_smtp_ssl:
            server = mock_smtp_ssl.return_value.__enter__.return_value
            result = sender.send("user@example.com", "Hello", "Body")
            assert result["success"] is True
            server.login.assert_called_once_with("user@example.com", "secret")
            server.send_message.assert_called_once()
