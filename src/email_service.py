"""Email service for password reset and 2FA codes"""
import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

# SMTP Configuration from environment variables
SMTP_HOST = os.environ.get('SMTP_HOST', 'localhost')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM_EMAIL = os.environ.get('SMTP_FROM_EMAIL', 'noreply@softfluid.fr')
SMTP_FROM_NAME = os.environ.get('SMTP_FROM_NAME', 'AI-SwAutoMorph')
SMTP_USE_TLS = os.environ.get('SMTP_USE_TLS', 'true').lower() == 'true'


def send_email(to_email, subject, html_body, text_body=None):
    """Send an email using SMTP configuration"""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg['To'] = to_email

        if text_body:
            msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        if SMTP_USE_TLS:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            server.starttls()
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)

        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)

        server.sendmail(SMTP_FROM_EMAIL, to_email, msg.as_string())
        server.quit()
        logger.info(f"Email sent successfully to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


def send_password_reset_email(to_email, username, reset_url):
    """Send password reset email"""
    subject = f"[{SMTP_FROM_NAME}] Password Reset Request"
    
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #2c3e50; color: white; padding: 20px; text-align: center;">
            <h1>{SMTP_FROM_NAME}</h1>
        </div>
        <div style="padding: 30px; background: #f9f9f9;">
            <h2>Password Reset Request</h2>
            <p>Hello <strong>{username}</strong>,</p>
            <p>A password reset has been requested for your account. Click the button below to set a new password:</p>
            <div style="text-align: center; margin: 30px 0;">
                <a href="{reset_url}" 
                   style="background: #3498db; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; font-size: 16px;">
                    Reset My Password
                </a>
            </div>
            <p style="color: #666; font-size: 14px;">This link will expire in 1 hour.</p>
            <p style="color: #666; font-size: 14px;">If you did not request this reset, you can safely ignore this email.</p>
            <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
            <p style="color: #999; font-size: 12px;">
                If the button doesn't work, copy and paste this URL into your browser:<br>
                <a href="{reset_url}">{reset_url}</a>
            </p>
        </div>
    </body>
    </html>
    """
    
    text_body = f"""Password Reset Request

Hello {username},

A password reset has been requested for your account.
Click the following link to set a new password:

{reset_url}

This link will expire in 1 hour.
If you did not request this reset, you can safely ignore this email.
"""
    
    return send_email(to_email, subject, html_body, text_body)


def send_2fa_code_email(to_email, username, code):
    """Send 2FA verification code via email"""
    subject = f"[{SMTP_FROM_NAME}] Your Verification Code"
    
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #2c3e50; color: white; padding: 20px; text-align: center;">
            <h1>{SMTP_FROM_NAME}</h1>
        </div>
        <div style="padding: 30px; background: #f9f9f9;">
            <h2>Two-Factor Authentication Code</h2>
            <p>Hello <strong>{username}</strong>,</p>
            <p>Your verification code is:</p>
            <div style="text-align: center; margin: 30px 0;">
                <span style="background: #ecf0f1; padding: 15px 30px; font-size: 32px; font-weight: bold; letter-spacing: 8px; border-radius: 5px; font-family: monospace;">
                    {code}
                </span>
            </div>
            <p style="color: #666; font-size: 14px;">This code will expire in 5 minutes.</p>
            <p style="color: #666; font-size: 14px;">If you did not request this code, please secure your account immediately.</p>
        </div>
    </body>
    </html>
    """
    
    text_body = f"""Two-Factor Authentication Code

Hello {username},

Your verification code is: {code}

This code will expire in 5 minutes.
If you did not request this code, please secure your account immediately.
"""
    
    return send_email(to_email, subject, html_body, text_body)
