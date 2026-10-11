# RemindME 🔔

A web app that keeps track of your subscriptions, free trials and personal tasks, and sends you an email before anything renews, expires or is due, so you never pay for something you forgot about.

![Home page](screenshots/home.png)

## Features

- Sign up / log in, with a preferred currency (€, $ or £) chosen at registration
- Dashboard with an overview of upcoming renewals, expiring trials and tasks

**Subscriptions**
- Add, edit, renew and delete subscriptions, grouped by category (Entertainment, Music, Gaming, Cloud Storage and more)
- Monthly or yearly billing, with automatic monthly and yearly cost totals
- Auto-renew support: renewal dates move forward automatically, while subscriptions without auto-renew are marked as expired
- Status tracking: active, canceled or expired

**Free trials**
- Track trials of services or products, including the cost after the trial ends
- Get reminded before a trial turns into a paid plan

**General tasks**
- Personal tasks and deadlines with due dates
- Mark tasks as done, with overdue tasks highlighted

**Email reminders**
- Choose how many days in advance you want to be reminded for each item
- A daily job checks all users and sends a single summary email with everything coming up, sorted by urgency

## Screenshots

**Subscriptions overview**

![Subscriptions overview](screenshots/subscriptions.png)

## How the email reminders work

Reminders are handled by a separate script (`notifier.py`) that runs once a day as a **Render Cron Job**. It loads the Flask app context, checks every user's subscriptions, free trials and tasks, and collects the items that fall inside each item's reminder window. If there is anything to report, it sends one HTML summary email per user through the **SendGrid API**.

## Tech stack

- **Backend:** Python, Flask, Flask-SQLAlchemy, Flask-Login, Flask-WTF
- **Email:** SendGrid API
- **Scheduling:** Render Cron Job
- **Frontend:** HTML, CSS, JavaScript, Bootstrap 5
- **Database:** PostgreSQL on Supabase (production), SQLite (local development)
- **Deployment:** Render (Gunicorn)

## Run locally

```bash
# Clone the repository
git clone https://github.com/georgios-toumpoglou/Remind-me.git
cd Remind-me

# Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# Install dependencies
pip install -r requirements.txt

# Run the app
python main.py
```

Then open http://127.0.0.1:5000 in your browser. The database tables are created automatically on the first run.

To send the reminder emails manually (instead of waiting for the daily job):

```bash
python notifier.py
```

### Environment variables

Create a `.env` file in the project folder (it is loaded automatically and excluded from Git):

```env
SECRET_KEY=your-secret-key
DATABASE_URL=postgresql://user:password@host:5432/dbname
SENDGRID_API_KEY=your-sendgrid-api-key
SENDGRID_FROM_EMAIL=your-verified-sender@example.com
TEST_MODE=False
```

| Variable | Description | Required |
|---|---|---|
| `SECRET_KEY` | Flask secret key for sessions and forms | Recommended |
| `DATABASE_URL` | PostgreSQL connection string (falls back to a local SQLite file if not set) | No |
| `SENDGRID_API_KEY` | API key from [SendGrid](https://sendgrid.com), needed only for the reminder emails | For emails |
| `SENDGRID_FROM_EMAIL` | Verified sender address in SendGrid | For emails |
| `TEST_MODE` | Set to `True` to send all reminders immediately, ignoring the reminder windows (useful for testing) | No |

The web app itself works without SendGrid. The SendGrid variables are only needed to send the reminder emails.

## Live demo

A live version is available on request. Feel free to contact me through [LinkedIn](https://www.linkedin.com/in/georgios-toumpoglou).

## Author

**Georgios Toumpoglou**
[GitHub](https://github.com/georgios-toumpoglou) · [LinkedIn](https://www.linkedin.com/in/georgios-toumpoglou)
