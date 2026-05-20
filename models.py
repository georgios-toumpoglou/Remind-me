"""
RemindME - Database Models
==========================
Defines all SQLAlchemy ORM models for the RemindME application.
Each model maps to a PostgreSQL (Supabase) table and includes
relationships, constraints, and helper properties.

Models:
    - User         : Registered user account
    - Subscription : Paid recurring subscription tracker
    - FreeTrial    : Free trial tracker with expiry detection
    - Reminder     : General personal task / deadline tracker
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import date

db = SQLAlchemy()


# ── User ───────────────────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    """
    Represents a registered user.

    Attributes:
        id            : Primary key, auto-incremented.
        name          : Display name provided at registration.
        email         : Unique email address used for login and notifications.
        password      : Hashed password (Werkzeug PBKDF2-SHA256).
        currency      : Preferred currency (EUR/USD/GBP) — set once at registration,
                        applied to all subscription cost calculations and summary cards.

    Relationships:
        subscriptions : One-to-many → Subscription
        free_trials   : One-to-many → FreeTrial
        reminders     : One-to-many → Reminder
    """
    __tablename__ = 'users'

    id       = db.Column(db.Integer,     primary_key=True)
    name     = db.Column(db.String(100), nullable=False)
    email    = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    currency = db.Column(db.String(3),   nullable=False, default='EUR')

    # Relationships — cascade delete removes all user data on account deletion
    subscriptions = db.relationship('Subscription', backref='owner', lazy=True, cascade='all, delete-orphan')
    free_trials   = db.relationship('FreeTrial',    backref='owner', lazy=True, cascade='all, delete-orphan')
    reminders     = db.relationship('Reminder',     backref='owner', lazy=True, cascade='all, delete-orphan')


# ── Subscription ───────────────────────────────────────────────────────────────
class Subscription(db.Model):
    """
    Represents a paid recurring subscription.

    Attributes:
        id            : Primary key, auto-incremented.
        user_id       : Foreign key → users.id
        name          : Service name (e.g. Netflix, Spotify).
        category      : Category label (Entertainment, Music, Gaming, etc.).
        billing_cycle : Payment frequency — 'monthly' or 'yearly'.
        cost          : Subscription cost in the user's chosen currency.
        renewal_date  : Next renewal or expiry date.
        auto_renew    : Whether the subscription renews automatically.
                        If False and renewal_date has passed → status becomes Expired.
        status        : Current state — 'active', 'canceled', or 'expired'.
        reminder_days : How many days before renewal_date to send an email alert.
        notes         : Optional free-text notes (e.g. 'family plan', 'student discount').

    Properties:
        is_expired    : Returns True if renewal_date has passed and auto_renew is False.
    """
    __tablename__ = 'subscriptions'

    id            = db.Column(db.Integer,     primary_key=True)
    user_id       = db.Column(db.Integer,     db.ForeignKey('users.id'), nullable=False)
    name          = db.Column(db.String(100), nullable=False)
    category      = db.Column(db.String(50),  nullable=False)
    billing_cycle = db.Column(db.String(10),  nullable=False, default='monthly')  # 'monthly' | 'yearly'
    cost          = db.Column(db.Float,        nullable=False)
    renewal_date  = db.Column(db.Date,         nullable=False)
    auto_renew    = db.Column(db.Boolean,      nullable=False, default=True)
    status        = db.Column(db.String(10),   nullable=False, default='active')   # 'active' | 'canceled' | 'expired'
    reminder_days = db.Column(db.Integer,      nullable=False, default=7)          # days before renewal to notify
    notes         = db.Column(db.String(500),  nullable=True)

    @property
    def is_expired(self):
        """
        Returns True if the renewal date has passed and auto-renew is disabled.
        Used by the dashboard to automatically mark subscriptions as expired.
        """
        return not self.auto_renew and self.renewal_date <= date.today()


# ── FreeTrial ──────────────────────────────────────────────────────────────────
class FreeTrial(db.Model):
    """
    Represents a free trial for a service or one-time purchase.

    The primary purpose is to remind the user before the trial converts
    to a paid subscription or charges a one-time fee.

    Attributes:
        id            : Primary key, auto-incremented.
        user_id       : Foreign key → users.id
        name          : Service or app name.
        trial_type    : 'service' (recurring after trial) or 'one_time' (single charge).
        trial_days    : Trial duration in days — 7, 14, or 30.
        start_date    : Date the trial started.
        expiry_date   : Date the trial ends (start_date + trial_days).
        cost_after    : Amount that will be charged if not canceled.
        status        : Current state — 'active', 'canceled', or 'converted'.
        reminder_days : How many days before expiry_date to send an email alert.

    Properties:
        is_expired    : Returns True if expiry_date has passed and status is still active.
    """
    __tablename__ = 'free_trials'

    id            = db.Column(db.Integer,     primary_key=True)
    user_id       = db.Column(db.Integer,     db.ForeignKey('users.id'), nullable=False)
    name          = db.Column(db.String(100), nullable=False)
    trial_type    = db.Column(db.String(10),  nullable=False, default='service')   # 'service' | 'one_time'
    trial_days    = db.Column(db.Integer,     nullable=False, default=7)           # 7 | 14 | 30
    start_date    = db.Column(db.Date,        nullable=False, default=date.today)
    expiry_date   = db.Column(db.Date,        nullable=False)
    cost_after    = db.Column(db.Float,       nullable=True)                       # None if free after trial
    status        = db.Column(db.String(10),  nullable=False, default='active')    # 'active' | 'canceled' | 'converted'
    reminder_days = db.Column(db.Integer,     nullable=False, default=3)           # default 3 days — trials are urgent

    @property
    def is_expired(self):
        """
        Returns True if the trial has passed its expiry date and is still marked active.
        Used by the dashboard to flag unconverted/uncanceled trials.
        """
        return self.status == 'active' and self.expiry_date < date.today()


# ── Reminder ───────────────────────────────────────────────────────────────────
class Reminder(db.Model):
    """
    Represents a general personal task or deadline.

    The simplest model — just a title, a due date, a reminder offset,
    and a done/pending status. Examples: car insurance renewal,
    bill payment, appointment, etc.

    Attributes:
        id            : Primary key, auto-incremented.
        user_id       : Foreign key → users.id
        title         : Short description of the task (e.g. 'Renew car insurance').
        due_date      : The deadline date for the task.
        reminder_days : How many days before due_date to send an email alert.
        status        : Current state — 'pending' or 'done'.

    Properties:
        is_overdue    : Returns True if due_date has passed and status is still pending.
    """
    __tablename__ = 'reminders'

    id            = db.Column(db.Integer,     primary_key=True)
    user_id       = db.Column(db.Integer,     db.ForeignKey('users.id'), nullable=False)
    title         = db.Column(db.String(200), nullable=False)
    due_date      = db.Column(db.Date,        nullable=False)
    reminder_days = db.Column(db.Integer,     nullable=False, default=7)
    status        = db.Column(db.String(10),  nullable=False, default='pending')   # 'pending' | 'done'
    notes         = db.Column(db.String(500), nullable=True)

    @property
    def is_overdue(self):
        """
        Returns True if the due date has passed and the task is still pending.
        Used by the dashboard to highlight overdue reminders.
        """
        return self.status == 'pending' and self.due_date <= date.today()
