import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import json
import os
from datetime import datetime


def load_email_config(config_file):
    with open(config_file, 'r') as file:
        return json.load(file)


def send_email(subject, body, *, config_file='email_config.json', outage_start_time=None, file_path=None):
    config = load_email_config(config_file)

    sender_email = config['sender_email']
    receiver_emails = config['receiver_emails']
    smtp_server = config['smtp_server']
    smtp_port = config['smtp_port']
    smtp_username = config['smtp_username']
    smtp_password = config['smtp_password']

    server = None
    try:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        server.login(smtp_username, smtp_password)

        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = ", ".join(receiver_emails)
        message["Subject"] = subject

        if outage_start_time:
            body += f"\nVýpadek začal: {outage_start_time.strftime('%Y-%m-%d %H:%M:%S')}"

        message.attach(MIMEText(body, "plain"))

        if file_path:
            with open(file_path, "rb") as file:
                attachment = MIMEBase("application", "octet-stream")
                attachment.set_payload(file.read())
            encoders.encode_base64(attachment)
            attachment.add_header("Content-Disposition", f"attachment; filename={os.path.basename(file_path)}")
            message.attach(attachment)

        server.sendmail(sender_email, receiver_emails, message.as_string())
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass


class StatusReporter:
    def __init__(self, email_config_file: str):
        self.email_config_file = email_config_file

    def report(self, subject: str, body: str, outage_start_time: datetime = None, file_path: str = None):
        send_email(subject, body, config_file=self.email_config_file, outage_start_time=outage_start_time, file_path=file_path)
