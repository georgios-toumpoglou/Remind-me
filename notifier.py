"""
RemindME - Email Notification Script
=====================================
Sends daily email reminders to users for:
    - Upcoming subscription renewals
    - Expiring free trials
    - Pending general tasks

Designed to run once per day via Render Cron Job (00:00 UTC).
For local testing, set TEST_MODE=True in .env to send immediately
regardless of reminder_days settings.

Author  : Georgios Toumpoglou
Stack   : Python, Flask-SQLAlchemy, SendGrid
"""

import os
from datetime import date
from dotenv import load_dotenv
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# Load environment variables from .env
load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────
SENDGRID_API_KEY   = os.getenv('SENDGRID_API_KEY')
SENDGRID_FROM_EMAIL = os.getenv('SENDGRID_FROM_EMAIL')
TEST_MODE          = os.getenv('TEST_MODE', 'False').lower() == 'true'
# ──────────────────────────────────────────────────────────────────────────────

# Bootstrap Flask app context so we can access the database
from main import app
from models import db, User, Subscription, FreeTrial, Reminder


def get_currency_symbol(currency):
    """Returns the currency symbol for the given currency code."""
    return {'EUR': '€', 'USD': '$', 'GBP': '£'}.get(currency, '€')


def build_email_body(user, notifications):
    """
    Builds the HTML email body for a user's notifications.
    Each notification is rendered as a styled card.
    Returns the full HTML string.
    """
    symbol = get_currency_symbol(user.currency)

    # Notification cards HTML
    cards_html = ''
    for notif in notifications:

        # Icon and border colour based on notification type
        if notif['type'] == 'subscription':
            icon   = '🔔'
            border = '#0BA9EA'
        elif notif['type'] == 'free_trial':
            icon   = '⏳'
            border = '#e05c5c'
        else:
            icon   = '📋'
            border = '#17C3B2'

        # Red badge if <= 3 days left
        badge_color = '#e05c5c' if notif['days_left'] <= 3 else '#0BA9EA'

        cards_html += f"""
        <div style="background:#B9EDF7; border-left:4px solid {border};
                    border-radius:10px; padding:16px 20px; margin-bottom:14px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:1rem; font-weight:700; color:#5D576B;">
                    {icon} {notif['title']}
                </span>
                <span style="background:{badge_color}; color:white; border-radius:20px;
                             padding:3px 12px; font-size:0.8rem; font-weight:700;">
                    {notif['days_left']} day{'s' if notif['days_left'] != 1 else ''} left
                </span>
            </div>
            <p style="margin:6px 0 0; font-size:0.88rem; color:#5D576B;">
                {notif['description']}
            </p>
        </div>
        """

    total = len(notifications)
    subtitle = f"You have <strong>{total}</strong> upcoming reminder{'s' if total != 1 else ''}."

    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; background:#DCF5FA;
                 margin:0; padding:0;">
        <div style="max-width:600px; margin:30px auto; background:#ffffff;
                    border-radius:16px; overflow:hidden; box-shadow:0 2px 12px rgba(0,0,0,0.08);">

            <!-- Header -->
            <div style="background:#DCF5FA; padding:28px 32px; text-align:center;">
                <img src="https://remindme-jmwy.onrender.com/static/img/logo.png"
                     alt="RemindME" height="50"
                     style="display:block; margin:0 auto 10px;">
                <p style="margin:0; color:#5D576B; font-size:0.95rem;">
                    Daily Notifications
                </p>
            </div>

            <!-- Body -->
            <div style="padding:28px 32px;">
                <p style="color:#5D576B; font-size:1rem; margin-bottom:6px;">
                    Hi <strong>{user.name}</strong>,
                </p>
                <p style="color:#0BA9EA; font-size:0.9rem; font-style:italic;
                           margin-bottom:24px;">
                    {subtitle}
                </p>

                {cards_html}

                <p style="color:#5D576B; font-size:0.85rem; margin-top:24px;">
                    Log in to <a href="#" style="color:#0BA9EA;">RemindME</a>
                    to manage your subscriptions and tasks.
                </p>
            </div>

            <!-- Footer -->
            <div style="background:#DCF5FA; padding:16px 32px; text-align:center;
                        border-top:1px solid rgba(93,87,107,0.1);">
                <p style="margin:0; font-size:0.78rem; color:#5D576B; opacity:0.7;">
                    © 2026 RemindME — Developed by GToumb<br>
                    You are receiving this email because you have an active RemindME account.<br>
                    <span style="color:#e05c5c;">If you don't see future emails in your inbox, please check your spam folder.</span>
                </p>
            </div>

        </div>
    </body>
    </html>
    """


def send_email(to_email, subject, html_body):
    """
    Sends an HTML email via SendGrid.
    Returns True on success, False on failure.
    """
    try:
        message = Mail(
            from_email = SENDGRID_FROM_EMAIL,
            to_emails  = to_email,
            subject    = subject,
            html_content = html_body
        )
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
        print(f"  ✓ Email sent to {to_email}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to send to {to_email}: {e}")
        return False


def check_user(user):
    """
    Checks all subscriptions, free trials, and reminders for a given user.
    Builds a list of notifications and sends an email if there are any.

    In TEST_MODE: sends email regardless of reminder_days (includes all active entries).
    In normal mode: sends only when days_left is within the user's reminder window.
    """
    notifications = []
    symbol        = get_currency_symbol(user.currency)
    today         = date.today()

    # ── Subscriptions ──────────────────────────────────────────────────────────
    subs = Subscription.query.filter_by(user_id=user.id, status='active').all()
    for sub in subs:
        days_left = (sub.renewal_date - today).days
        in_window = TEST_MODE or (1 <= days_left <= sub.reminder_days)
        if in_window:
            notifications.append({
                'type'       : 'subscription',
                'title'      : f'Your {sub.name} subscription renews in {days_left} day{"s" if days_left != 1 else ""} ({sub.renewal_date.strftime("%d/%m/%Y")})',
                'description': f'{"Auto-renewal is ON." if sub.auto_renew else "Auto-renewal is OFF — remember to renew manually!"} Cost: {symbol}{sub.cost:.2f}',
                'days_left'  : days_left
            })

    # ── Free Trials ────────────────────────────────────────────────────────────
    trials = FreeTrial.query.filter_by(user_id=user.id, status='active').all()
    for trial in trials:
        days_left = (trial.expiry_date - today).days
        in_window = TEST_MODE or (1 <= days_left <= trial.reminder_days)
        if in_window:
            if trial.cost_after:
                if trial.trial_type == 'service':
                    desc = f'You will be charged {symbol}{trial.cost_after:.2f} automatically after expiry.'
                else:
                    desc = f'You will need to purchase it for {symbol}{trial.cost_after:.2f}.'
            else:
                desc = 'No charge after expiry.'
            notifications.append({
                'type'       : 'free_trial',
                'title'      : f'Your free trial of {trial.name} expires in {days_left} day{"s" if days_left != 1 else ""} ({trial.expiry_date.strftime("%d/%m/%Y")})',
                'description': desc,
                'days_left'  : days_left
            })

    # ── General Tasks ──────────────────────────────────────────────────────────
    tasks = Reminder.query.filter_by(user_id=user.id, status='pending').all()
    for task in tasks:
        days_left = (task.due_date - today).days
        in_window = TEST_MODE or (1 <= days_left <= task.reminder_days)
        if in_window:
            notifications.append({
                'type'       : 'general_task',
                'title'      : f'Task "{task.title}" is due in {days_left} day{"s" if days_left != 1 else ""} ({task.due_date.strftime("%d/%m/%Y")})',
                'description': task.notes if task.notes else 'Mark it as done once completed.',
                'days_left'  : days_left
            })

    # Sort by urgency — most urgent first
    notifications.sort(key=lambda x: x['days_left'])

    # Send email only if there are notifications
    if notifications:
        subject   = f'RemindME — You have {len(notifications)} upcoming reminder{"s" if len(notifications) != 1 else ""}'
        html_body = build_email_body(user, notifications)
        send_email(user.email, subject, html_body)
    else:
        print(f"  — No notifications for {user.email}")


def run():
    """
    Main entry point.
    Loops through all users and sends notification emails where applicable.
    """
    print(f"\n{'='*50}")
    print(f"RemindME Notifier — {date.today().strftime('%d/%m/%Y')}")
    print(f"Mode: {'TEST (sending all)' if TEST_MODE else 'PRODUCTION'}")
    print(f"{'='*50}\n")

    with app.app_context():
        users = User.query.all()
        print(f"Checking {len(users)} user(s)...\n")
        for user in users:
            print(f"→ {user.name} ({user.email})")
            check_user(user)

    print(f"\n{'='*50}")
    print("Done!")
    print(f"{'='*50}\n")


if __name__ == '__main__':
    run()
