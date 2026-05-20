"""
RemindME - Subscription & Task Reminder Web Application
========================================================
A Flask-based web application that helps users track their subscriptions,
free trials, and personal reminders. Features user authentication,
email notifications via SendGrid, and automated renewal alerts.

Author  : Georgios Toumpoglou
Stack   : Python, Flask, SQLAlchemy, PostgreSQL (Supabase), Bootstrap 5
Deploy  : Render (GitHub integration)
"""

import os
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, SubmitField, FloatField, BooleanField, TextAreaField, DateField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# Import db instance and all models from models.py
from models import db, User, Subscription, FreeTrial, Reminder

# Load environment variables from .env file (SECRET_KEY, DATABASE_URL)
load_dotenv()

app = Flask(__name__)

# ── Application Configuration ──────────────────────────────────────────────────
# SECRET_KEY is used by Flask-WTF for CSRF protection and session signing.
# DATABASE_URL falls back to a local SQLite file for development convenience.
app.config['SECRET_KEY']                     = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI']        = os.getenv('DATABASE_URL', 'sqlite:///remindme.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # Suppresses deprecation warning

# ── Extension Initialisation ───────────────────────────────────────────────────
# Bind the SQLAlchemy db instance (defined in models.py) to this Flask app.
db.init_app(app)

# Create all tables on startup
with app.app_context():
    db.create_all()

# Flask-Login manages user sessions (login, logout, @login_required protection).
login_manager = LoginManager(app)
login_manager.login_view             = 'login'
login_manager.login_message          = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'


@login_manager.user_loader
def load_user(user_id):
    """
    Required callback for Flask-Login.
    Reloads the user object from the database using the ID stored in the session.
    """
    return db.session.get(User, int(user_id))


# ── Helper — currency symbol ───────────────────────────────────────────────────
def get_currency_symbol(currency):
    """Returns the currency symbol for the given currency code."""
    return {'EUR': '€', 'USD': '$', 'GBP': '£'}.get(currency, '€')


# ── Helper — auto-advance renewal date ────────────────────────────────────────
def advance_renewal_date(sub):
    """
    If a subscription has auto-renew ON and its renewal date has passed,
    advances the renewal date by 1 month (monthly) or 1 year (yearly)
    until it is in the future. Simulates automatic renewal behaviour.
    """
    if sub.auto_renew and sub.status == 'active' and sub.renewal_date <= date.today():
        if sub.billing_cycle == 'monthly':
            while sub.renewal_date < date.today():
                sub.renewal_date += relativedelta(months=1)
        else:
            while sub.renewal_date < date.today():
                sub.renewal_date += relativedelta(years=1)


# ── Forms (Flask-WTF) ──────────────────────────────────────────────────────────
CATEGORIES = [
    ('Entertainment', 'Entertainment'), ('Music', 'Music'),
    ('Gaming', 'Gaming'), ('Software & Productivity', 'Software & Productivity'),
    ('Cloud Storage', 'Cloud Storage'), ('News & Media', 'News & Media'),
    ('Health & Fitness', 'Health & Fitness'), ('Education', 'Education'),
    ('Food & Delivery', 'Food & Delivery'), ('Shopping', 'Shopping'),
    ('Finance', 'Finance'), ('VPN & Security', 'VPN & Security'),
    ('Other', 'Other')
]

REMINDER_CHOICES = [
    ('1', '1 day before'), ('3', '3 days before'), ('7', '7 days before'),
    ('14', '14 days before'), ('30', '30 days before')
]


class RegisterForm(FlaskForm):
    """
    Registration form.
    Collects name, email, preferred currency, and password (with confirmation).
    Currency is set once here and applies to all subscription entries for this user.
    """
    name     = StringField('Full Name',          validators=[DataRequired(), Length(min=2, max=100)])
    email    = StringField('Email',              validators=[DataRequired(), Email()])
    currency = SelectField('Currency',           choices=[('EUR', '€ Euro'), ('USD', '$ US Dollar'), ('GBP', '£ British Pound')])
    password = PasswordField('Password',         validators=[DataRequired(), Length(min=6, message='Password must be at least 6 characters.')])
    confirm  = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password', message='Passwords must match.')])
    submit   = SubmitField('Create Account')


class LoginForm(FlaskForm):
    """
    Login form.
    Authenticates the user by email and password against the stored hash.
    """
    email    = StringField('Email',      validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit   = SubmitField('Log In')


class SubscriptionAddForm(FlaskForm):
    """
    Add new subscription form.
    All fields map directly to the Subscription model.
    """
    name          = StringField('Name',          validators=[DataRequired(), Length(max=100)])
    category      = SelectField('Category',      choices=CATEGORIES)
    billing_cycle = SelectField('Billing',       choices=[('monthly', 'Monthly'), ('yearly', 'Yearly')])
    cost          = FloatField('Cost',           validators=[DataRequired(), NumberRange(min=0.01, message='Cost must be greater than 0.')])
    renewal_date  = DateField('Renewal Date',    validators=[DataRequired()])
    reminder_days = SelectField('Remind me',     choices=REMINDER_CHOICES)
    auto_renew    = BooleanField('Auto-Renew')
    notes         = TextAreaField('Notes',       validators=[Length(max=500)])
    submit        = SubmitField('Add Subscription')

    def validate_renewal_date(self, field):
        """Prevents adding a subscription with a renewal date in the past or today."""
        if field.data and field.data <= date.today():
            raise ValidationError('Renewal date must be in the future.')


class SubscriptionEditForm(FlaskForm):
    """
    Edit existing subscription form.
    Same fields as Add, with the addition of Status so the user
    can manually set a subscription to Canceled.
    """
    name          = StringField('Name',          validators=[DataRequired(), Length(max=100)])
    category      = SelectField('Category',      choices=CATEGORIES)
    billing_cycle = SelectField('Billing',       choices=[('monthly', 'Monthly'), ('yearly', 'Yearly')])
    cost          = FloatField('Cost',           validators=[DataRequired(), NumberRange(min=0.01)])
    renewal_date  = DateField('Renewal Date',    validators=[DataRequired()])
    reminder_days = SelectField('Remind me',     choices=REMINDER_CHOICES)
    status        = SelectField('Status',        choices=[('active', 'Active'), ('canceled', 'Canceled')])
    # Note: 'Expired' is set automatically by the app when renewal_date passes and auto_renew is OFF.
    auto_renew    = BooleanField('Auto-Renew')
    notes         = TextAreaField('Notes',       validators=[Length(max=500)])
    submit        = SubmitField('Save Changes')




class FreeTrialAddForm(FlaskForm):
    # Add new free trial form.
    # expiry_date is calculated automatically: start_date + trial_days.
    name          = StringField('Name',            validators=[DataRequired(), Length(max=100)])
    trial_type    = SelectField('Type',            choices=[('service', 'Service (recurring after trial)'), ('one_time', 'One-time purchase')])
    trial_days    = SelectField('Trial Duration',  choices=[('7', '7 days'), ('14', '14 days'), ('30', '30 days')])
    start_date    = DateField('Start Date',        validators=[DataRequired()])
    cost_after    = FloatField('Cost after trial', validators=[NumberRange(min=0)], default=None)
    reminder_days = SelectField('Remind me',       choices=REMINDER_CHOICES, default='3')
    submit        = SubmitField('Add Free Trial')


class FreeTrialEditForm(FlaskForm):
    # Edit existing free trial form.
    # Includes status so user can manually set Canceled or Converted.
    name          = StringField('Name',            validators=[DataRequired(), Length(max=100)])
    trial_type    = SelectField('Type',            choices=[('service', 'Service (recurring after trial)'), ('one_time', 'One-time purchase')])
    trial_days    = SelectField('Trial Duration',  choices=[('7', '7 days'), ('14', '14 days'), ('30', '30 days')])
    start_date    = DateField('Start Date',        validators=[DataRequired()])
    cost_after    = FloatField('Cost after trial', validators=[NumberRange(min=0)], default=None)
    reminder_days = SelectField('Remind me',       choices=REMINDER_CHOICES)
    status        = SelectField('Status',          choices=[('active', 'Active'), ('canceled', 'Canceled'), ('converted', 'Converted')])
    submit        = SubmitField('Save Changes')



class TaskAddForm(FlaskForm):
    # Add new general task form.
    title         = StringField('Task',      validators=[DataRequired(), Length(max=200)])
    due_date      = DateField('Due Date',    validators=[DataRequired()])
    reminder_days = SelectField('Remind me', choices=REMINDER_CHOICES)
    notes         = TextAreaField('Notes',   validators=[Length(max=500)])
    submit        = SubmitField('Add Task')

    def validate_due_date(self, field):
        """Prevents adding a task with a due date in the past or today."""
        if field.data and field.data <= date.today():
            raise ValidationError('Due date must be in the future.')


class TaskEditForm(FlaskForm):
    # Edit existing task form.
    title         = StringField('Task',      validators=[DataRequired(), Length(max=200)])
    due_date      = DateField('Due Date',    validators=[DataRequired()])
    reminder_days = SelectField('Remind me', choices=REMINDER_CHOICES)
    notes         = TextAreaField('Notes',   validators=[Length(max=500)])
    status        = SelectField('Status',    choices=[('pending', 'Pending'), ('done', 'Done')])
    submit        = SubmitField('Save Changes')

# ── Routes — Auth ──────────────────────────────────────────────────────────────
@app.route('/')
def index():
    """
    Landing page — visible to all visitors (authenticated or not).
    Passes empty form instances so modals render correctly on first visit.
    """
    return render_template('index.html',
                           form_register=RegisterForm(),
                           form_login=LoginForm())


@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    Handles new user registration.
    - Redirects already-authenticated users straight to the dashboard.
    - On valid POST: hashes the password, creates the User record, and
      redirects to the landing page with a success flash message.
    - On duplicate email or validation failure: re-renders the registration
      modal with inline field errors.
    """
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = RegisterForm()
    if form.validate_on_submit():

        # Prevent duplicate accounts for the same email address
        if User.query.filter_by(email=form.email.data).first():
            flash('This email is already registered. Please log in.', 'error')
            return render_template('index.html',
                                   form_register=form,
                                   form_login=LoginForm(),
                                   show_register=True)

        new_user = User(
            name     = form.name.data,
            email    = form.email.data,
            password = generate_password_hash(form.password.data),
            currency = form.currency.data
        )
        db.session.add(new_user)
        db.session.commit()
        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('index'))

    # Validation failed — reopen the register modal with field errors visible
    return render_template('index.html',
                           form_register=form,
                           form_login=LoginForm(),
                           show_register=True)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handles user authentication.
    - Redirects already-authenticated users straight to the dashboard.
    - On valid credentials: starts a Flask-Login session and redirects to dashboard.
    - On failure: re-renders the login modal with a generic error message
      (intentionally vague to avoid revealing whether email or password was wrong).
    """
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')

    # Validation failed — reopen the login modal with error visible
    return render_template('index.html',
                           form_register=RegisterForm(),
                           form_login=form,
                           show_login=True)


@app.route('/logout')
@login_required
def logout():
    """
    Terminates the current user session and redirects to the landing page.
    """
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


# ── Routes — Dashboard ─────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    """
    Notifications home page — first page the user sees after login.
    Checks all subscriptions, free trials, and reminders for upcoming deadlines
    and builds a notifications list to display as alert cards.
    Auto-expires overdue subscriptions (auto_renew OFF) and advances
    renewal dates for auto-renewing subscriptions.
    """
    notifications = []

    # Check subscriptions — auto-expire or auto-advance, then collect upcoming renewals
    subs = Subscription.query.filter_by(user_id=current_user.id).all()
    for sub in subs:

        # Auto-expire: renewal date passed and auto-renew is OFF
        if sub.is_expired and sub.status == 'active':
            sub.status = 'expired'
            db.session.commit()

        # Auto-advance: renewal date passed and auto-renew is ON
        advance_renewal_date(sub)
        db.session.commit()

        # Notify if active and renewal is within reminder_days
        if sub.status == 'active':
            days_left = (sub.renewal_date - date.today()).days
            if 1 <= days_left <= sub.reminder_days:
                symbol = get_currency_symbol(current_user.currency)
                notifications.append({
                    'type'       : 'subscription',
                    'message'    : f'Your <strong>{sub.name}</strong> subscription renews in <strong>{days_left} day{"s" if days_left != 1 else ""}</strong> ({sub.renewal_date.strftime("%d/%m/%Y")}).',
                    'description': f'{"Auto-renewal is ON." if sub.auto_renew else "Auto-renewal is OFF — remember to renew manually!"} Cost: {symbol}{sub.cost:.2f}',
                    'days_left'  : days_left
                })

    # Check free trials — collect expiring trials
    trials = FreeTrial.query.filter_by(user_id=current_user.id, status='active').all()
    for trial in trials:
        days_left = (trial.expiry_date - date.today()).days
        if 1 <= days_left <= trial.reminder_days:
            symbol = get_currency_symbol(current_user.currency)
            if trial.cost_after:
                if trial.trial_type == 'service':
                    cost_info = f'You will be charged {symbol}{trial.cost_after:.2f} automatically after expiry.'
                else:
                    cost_info = f'You will need to purchase it for {symbol}{trial.cost_after:.2f}.'
            else:
                cost_info = 'No charge after expiry.'
            notifications.append({
                'type'       : 'free_trial',
                'message'    : f'Your free trial of <strong>{trial.name}</strong> expires in <strong>{days_left} day{"s" if days_left != 1 else ""}</strong> ({trial.expiry_date.strftime("%d/%m/%Y")}).',
                'description': cost_info,
                'days_left'  : days_left
            })

    # Check reminders — collect upcoming tasks
    reminders = Reminder.query.filter_by(user_id=current_user.id, status='pending').all()
    for reminder in reminders:
        days_left = (reminder.due_date - date.today()).days
        if 1 <= days_left <= reminder.reminder_days:
            notifications.append({
                'type'       : 'general_task',
                'message'    : f'Reminder: <strong>{reminder.title}</strong> is due in <strong>{days_left} day{"s" if days_left != 1 else ""}</strong> ({reminder.due_date.strftime("%d/%m/%Y")}).',
                'description': 'Mark it as done once completed.',
                'days_left'  : days_left
            })

    # Sort notifications by urgency — most urgent first
    notifications.sort(key=lambda x: x['days_left'])

    return render_template('dashboard.html', notifications=notifications)


# ── Routes — Subscriptions ─────────────────────────────────────────────────────
@app.route('/subscriptions')
@login_required
def subscriptions():
    """
    Displays all subscriptions for the current user.
    Auto-expires overdue subscriptions (auto_renew OFF) and advances
    renewal dates for auto-renewing subscriptions.
    Calculates monthly and yearly cost totals for active subscriptions.
    """
    subs = Subscription.query.filter_by(user_id=current_user.id).all()

    for sub in subs:
        # Auto-expire any overdue subscriptions with auto-renew OFF
        if sub.is_expired and sub.status == 'active':
            sub.status = 'expired'
        # Auto-advance renewal date for subscriptions with auto-renew ON
        advance_renewal_date(sub)

    db.session.commit()

    # Calculate summary costs:
    # Monthly cost = sum of all monthly subscriptions only
    # Yearly cost  = (monthly subscriptions × 12) + sum of yearly subscriptions
    active_subs  = [s for s in subs if s.status == 'active']
    monthly_cost = sum(s.cost for s in active_subs if s.billing_cycle == 'monthly')
    yearly_cost  = (monthly_cost * 12) + sum(s.cost for s in active_subs if s.billing_cycle == 'yearly')

    return render_template('subscriptions.html',
                           subscriptions   = subs,
                           form_add        = SubscriptionAddForm(),
                           form_edit       = SubscriptionEditForm(),
                           currency_symbol = get_currency_symbol(current_user.currency),
                           monthly_cost    = monthly_cost,
                           yearly_cost     = yearly_cost)


@app.route('/subscriptions/add', methods=['POST'])
@login_required
def add_subscription():
    """
    Handles the Add Subscription form submission.
    On success: creates the Subscription record and redirects back to the list.
    On failure: re-renders the subscriptions page with the Add modal open and errors visible.
    """
    form = SubscriptionAddForm()
    if form.validate_on_submit():
        new_sub = Subscription(
            user_id       = current_user.id,
            name          = form.name.data,
            category      = form.category.data,
            billing_cycle = form.billing_cycle.data,
            cost          = form.cost.data,
            renewal_date  = form.renewal_date.data,
            auto_renew    = form.auto_renew.data,
            reminder_days = int(form.reminder_days.data),
            notes         = form.notes.data or None
        )
        db.session.add(new_sub)
        db.session.commit()
        flash(f'"{new_sub.name}" added successfully!', 'success')
        return redirect(url_for('subscriptions'))

    # Validation failed — reopen the Add modal with errors
    subs         = Subscription.query.filter_by(user_id=current_user.id).all()
    active_subs  = [s for s in subs if s.status == 'active']
    monthly_cost = sum(s.cost for s in active_subs if s.billing_cycle == 'monthly')
    yearly_cost  = (monthly_cost * 12) + sum(s.cost for s in active_subs if s.billing_cycle == 'yearly')

    return render_template('subscriptions.html',
                           subscriptions   = subs,
                           form_add        = form,
                           form_edit       = SubscriptionEditForm(),
                           currency_symbol = get_currency_symbol(current_user.currency),
                           monthly_cost    = monthly_cost,
                           yearly_cost     = yearly_cost,
                           show_add        = True)


@app.route('/subscriptions/edit/<int:sub_id>', methods=['POST'])
@login_required
def edit_subscription(sub_id):
    """
    Handles the Edit Subscription form submission.
    Verifies the subscription belongs to the current user before updating.
    On success: updates the record and redirects back to the list.
    """
    sub  = Subscription.query.filter_by(id=sub_id, user_id=current_user.id).first_or_404()
    form = SubscriptionEditForm()

    if form.validate_on_submit():
        sub.name          = form.name.data
        sub.category      = form.category.data
        sub.billing_cycle = form.billing_cycle.data
        sub.cost          = form.cost.data
        sub.renewal_date  = form.renewal_date.data
        sub.auto_renew    = form.auto_renew.data
        sub.status        = form.status.data
        sub.reminder_days = int(form.reminder_days.data)
        sub.notes         = form.notes.data or None
        db.session.commit()
        flash(f'"{sub.name}" updated successfully!', 'success')
        return redirect(url_for('subscriptions'))

    # Validation failed — reopen the Edit modal with errors
    subs         = Subscription.query.filter_by(user_id=current_user.id).all()
    active_subs  = [s for s in subs if s.status == 'active']
    monthly_cost = sum(s.cost for s in active_subs if s.billing_cycle == 'monthly')
    yearly_cost  = (monthly_cost * 12) + sum(s.cost for s in active_subs if s.billing_cycle == 'yearly')

    return render_template('subscriptions.html',
                           subscriptions   = subs,
                           form_add        = SubscriptionAddForm(),
                           form_edit       = form,
                           currency_symbol = get_currency_symbol(current_user.currency),
                           monthly_cost    = monthly_cost,
                           yearly_cost     = yearly_cost,
                           show_edit       = True)


@app.route('/subscriptions/delete/<int:sub_id>', methods=['POST'])
@login_required
def delete_subscription(sub_id):
    """
    Permanently deletes a subscription.
    Verifies ownership before deletion to prevent unauthorised access.
    """
    sub  = Subscription.query.filter_by(id=sub_id, user_id=current_user.id).first_or_404()
    name = sub.name
    db.session.delete(sub)
    db.session.commit()
    flash(f'"{name}" deleted successfully.', 'info')
    return redirect(url_for('subscriptions'))


@app.route('/subscriptions/renew/<int:sub_id>', methods=['POST'])
@login_required
def renew_subscription(sub_id):
    """
    Renews an expired subscription by setting a new renewal date
    and restoring the status to active.
    """
    sub      = Subscription.query.filter_by(id=sub_id, user_id=current_user.id).first_or_404()
    new_date = request.form.get('renewal_date')
    if new_date:
        sub.renewal_date = datetime.strptime(new_date, '%Y-%m-%d').date()
        sub.status       = 'active'
        db.session.commit()
        flash(f'"{sub.name}" renewed successfully!', 'success')
    return redirect(url_for('subscriptions'))




# ── Routes — Free Trials ───────────────────────────────────────────────────────
@app.route('/free-trials')
@login_required
def free_trials():
    """
    Displays all free trials for the current user.
    Auto-expires trials where expiry_date has passed and status is still active.
    """
    trials = FreeTrial.query.filter_by(user_id=current_user.id).all()

    # Auto-expire any trials whose expiry date has passed or is today
    for trial in trials:
        if trial.status == 'active' and trial.expiry_date <= date.today():
            trial.status = 'expired'
    db.session.commit()

    return render_template('free_trials.html',
                           trials          = trials,
                           form_add        = FreeTrialAddForm(),
                           form_edit       = FreeTrialEditForm(),
                           currency_symbol = get_currency_symbol(current_user.currency),
                           today           = date.today())


@app.route('/free-trials/add', methods=['POST'])
@login_required
def add_free_trial():
    """
    Handles the Add Free Trial form submission.
    Calculates expiry_date automatically from start_date + trial_days.
    """
    form = FreeTrialAddForm()
    if form.validate_on_submit():
        t_days    = int(form.trial_days.data)
        start     = form.start_date.data
        expiry    = start + relativedelta(days=t_days)
        new_trial = FreeTrial(
            user_id       = current_user.id,
            name          = form.name.data,
            trial_type    = form.trial_type.data,
            trial_days    = t_days,
            start_date    = start,
            expiry_date   = expiry,
            cost_after    = form.cost_after.data if form.cost_after.data else None,
            reminder_days = int(form.reminder_days.data)
        )
        db.session.add(new_trial)
        db.session.commit()
        flash(f'"{new_trial.name}" free trial added!', 'success')
        return redirect(url_for('free_trials'))

    trials = FreeTrial.query.filter_by(user_id=current_user.id).all()
    return render_template('free_trials.html',
                           trials          = trials,
                           form_add        = form,
                           form_edit       = FreeTrialEditForm(),
                           currency_symbol = get_currency_symbol(current_user.currency),
                           today           = date.today(),
                           show_add        = True)


@app.route('/free-trials/edit/<int:trial_id>', methods=['POST'])
@login_required
def edit_free_trial(trial_id):
    """
    Handles the Edit Free Trial form submission.
    Recalculates expiry_date if start_date or trial_days changed.
    """
    trial = FreeTrial.query.filter_by(id=trial_id, user_id=current_user.id).first_or_404()
    form  = FreeTrialEditForm()

    if form.validate_on_submit():
        t_days              = int(form.trial_days.data)
        new_expiry          = form.start_date.data + relativedelta(days=t_days)
        trial.name          = form.name.data
        trial.trial_type    = form.trial_type.data
        trial.trial_days    = t_days
        trial.start_date    = form.start_date.data
        trial.expiry_date   = new_expiry
        trial.cost_after    = form.cost_after.data if form.cost_after.data else None
        trial.reminder_days = int(form.reminder_days.data)
        # Auto-restore to active if new expiry date is in the future
        if new_expiry > date.today():
            trial.status = 'active'
        else:
            trial.status = form.status.data
        db.session.commit()
        flash(f'"{trial.name}" updated successfully!', 'success')
        return redirect(url_for('free_trials'))

    trials = FreeTrial.query.filter_by(user_id=current_user.id).all()
    return render_template('free_trials.html',
                           trials          = trials,
                           form_add        = FreeTrialAddForm(),
                           form_edit       = form,
                           currency_symbol = get_currency_symbol(current_user.currency),
                           today           = date.today(),
                           show_edit       = True)


@app.route('/free-trials/delete/<int:trial_id>', methods=['POST'])
@login_required
def delete_free_trial(trial_id):
    """
    Permanently deletes a free trial.
    Verifies ownership before deletion.
    """
    trial = FreeTrial.query.filter_by(id=trial_id, user_id=current_user.id).first_or_404()
    name  = trial.name
    db.session.delete(trial)
    db.session.commit()
    flash(f'"{name}" deleted successfully.', 'info')
    return redirect(url_for('free_trials'))



# ── Routes — General Tasks ─────────────────────────────────────────────────────
@app.route('/general-tasks')
@login_required
def general_tasks():
    """Displays all general tasks for the current user, sorted by due date."""
    tasks = Reminder.query.filter_by(user_id=current_user.id).order_by(Reminder.due_date).all()
    return render_template('general_tasks.html',
                           tasks    = tasks,
                           form_add = TaskAddForm(),
                           form_edit= TaskEditForm(),
                           today    = date.today())


@app.route('/general-tasks/add', methods=['POST'])
@login_required
def add_task():
    """Handles the Add Task form submission."""
    form = TaskAddForm()
    if form.validate_on_submit():
        new_task = Reminder(
            user_id       = current_user.id,
            title         = form.title.data,
            due_date      = form.due_date.data,
            reminder_days = int(form.reminder_days.data),
            notes         = form.notes.data or None
        )
        db.session.add(new_task)
        db.session.commit()
        flash(f'"{new_task.title}" added successfully!', 'success')
        return redirect(url_for('general_tasks'))

    tasks = Reminder.query.filter_by(user_id=current_user.id).order_by(Reminder.due_date).all()
    return render_template('general_tasks.html',
                           tasks    = tasks,
                           form_add = form,
                           form_edit= TaskEditForm(),
                           today    = date.today(),
                           show_add = True)


@app.route('/general-tasks/edit/<int:task_id>', methods=['POST'])
@login_required
def edit_task(task_id):
    """Handles the Edit Task form submission."""
    task = Reminder.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()
    form = TaskEditForm()

    if form.validate_on_submit():
        task.title         = form.title.data
        task.due_date      = form.due_date.data
        task.reminder_days = int(form.reminder_days.data)
        task.notes         = form.notes.data or None
        task.status        = form.status.data
        db.session.commit()
        flash(f'"{task.title}" updated successfully!', 'success')
        return redirect(url_for('general_tasks'))

    tasks = Reminder.query.filter_by(user_id=current_user.id).order_by(Reminder.due_date).all()
    return render_template('general_tasks.html',
                           tasks     = tasks,
                           form_add  = TaskAddForm(),
                           form_edit = form,
                           today     = date.today(),
                           show_edit = True)


@app.route('/general-tasks/done/<int:task_id>', methods=['POST'])
@login_required
def done_task(task_id):
    """Marks a task as done."""
    task = Reminder.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()
    task.status = 'done'
    db.session.commit()
    flash(f'"{task.title}" marked as done!', 'success')
    return redirect(url_for('general_tasks'))


@app.route('/general-tasks/delete/<int:task_id>', methods=['POST'])
@login_required
def delete_task(task_id):
    """Permanently deletes a task."""
    task = Reminder.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()
    name = task.title
    db.session.delete(task)
    db.session.commit()
    flash(f'"{name}" deleted successfully.', 'info')
    return redirect(url_for('general_tasks'))

# ── Database Initialisation & Entry Point ──────────────────────────────────────
if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Creates all tables if they do not already exist
    app.run(debug=True, host='0.0.0.0')  # host='0.0.0.0' enables LAN access for mobile testing
