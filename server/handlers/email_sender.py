import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class EmailSender:
    def __init__(self, config):
        self.config = config

    def _get_config(self):
        return {
            "smtp_server": self.config.get_secret("smtp_server")
            or "smtp.gmail.com",
            "smtp_port": int(self.config.get_secret("smtp_port") or "587"),
            "smtp_username": self.config.get_secret("smtp_username") or "",
            "smtp_password": self.config.get_secret("smtp_password") or "",
        }

    def send(self, to: str, subject: str, body: str) -> dict:
        smtp_cfg = self._get_config()
        if not smtp_cfg["smtp_username"] or not smtp_cfg["smtp_password"]:
            return {
                "success": False,
                "message": "Email not configured. Set SMTP credentials in settings.",
            }

        msg = MIMEMultipart()
        msg["From"] = smtp_cfg["smtp_username"]
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(
                smtp_cfg["smtp_server"], smtp_cfg["smtp_port"]
            ) as server:
                server.starttls(context=context)
                server.login(
                    smtp_cfg["smtp_username"], smtp_cfg["smtp_password"]
                )
                server.send_message(msg)
            return {"success": True, "message": f"Email sent to {to}"}
        except smtplib.SMTPAuthenticationError:
            return {
                "success": False,
                "message": "Email authentication failed. Check SMTP credentials.",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to send email: {str(e)}",
            }
