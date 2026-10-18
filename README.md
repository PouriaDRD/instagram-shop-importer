# Selora Instagram Importer

Desktop importer for crawling Instagram shop content, reviewing products locally, and securely sending selected data and media to the **Selora** API.

The application runs as a local Flask web interface and can be packaged as a standalone Windows executable with PyInstaller.

## Features

* Crawl Instagram profiles and media using Playwright
* Persistent local sessions and media cache
* Select posts, images and product information before import
* Send selected products and assets to Selora
* Persistent Selora workspace coordination and locking
* Resume-safe media upload checkpoints
* Separate **Crawl** and **Selora Sync** statuses
* Detailed Selora connection diagnostics:

  * DNS failures
  * SSL/TLS errors
  * connection/read timeouts
  * connection refused/reset
  * proxy/network errors
  * API response errors
* Automatic retry for temporary Selora network failures
* SQLite WAL mode and lock handling
* Automatic legacy database migration with pre-migration backup
* Single-instance protection on Windows
* Safe Exit with best-effort Selora lock release
* Structured application, HTTP, crawler, media and upload logs

## Tech Stack

* Python
* Flask
* SQLAlchemy
* SQLite
* Flask-Migrate / Alembic
* Playwright
* Requests
* Pillow
* PyInstaller
* Pytest

## Project Structure

```text
app/
├── crawler/           # Instagram crawling
├── integrations/      # Selora API integration
├── models/            # SQLAlchemy models
├── repositories/      # Database access
├── routes/            # Flask routes
├── services/          # Application/business services
├── static/            # CSS, JS and images
├── templates/         # Jinja templates
└── runtime_*.py       # Desktop runtime services

migrations/            # Database migrations
tests/                 # Automated tests
run.py                 # Application entry point
requirements.txt
SeloraInstagramImporter.spec
```

## Development Setup

Clone the repository:

```bash
git clone https://github.com/PouriaDRD/instagram-shop-importer.git
cd instagram-shop-importer
```

Create and activate a virtual environment on Windows:

```bat
python -m venv .venv
.venv\Scripts\activate
```

Install dependencies:

```bat
pip install -r requirements.txt
```

Install the Playwright browser if required:

```bat
python -m playwright install chromium
```

Create the environment file:

```bat
copy .env.example .env
```

Then configure `.env`.

## Environment Variables

```env
DEBUG="false"
SECRET_KEY="change-me"

LOG_LEVEL="INFO"

HOSTNAME="127.0.0.1"
PORT="5050"

DATABASE_URL="sqlite:///instagram_importer.db"

PLAYWRIGHT_HEADLESS="true"
PLAYWRIGHT_TIMEOUT_MS="30000"

SELORA_API_BASE_URL="https://your-selora-domain.example"
SELORA_API_KEY="selora_xxxxxxxxxxxxxxxxx"

SELORA_API_CONNECT_TIMEOUT_SECONDS="30"
SELORA_API_READ_TIMEOUT_SECONDS="30"
```

### Important

`SELORA_API_KEY` must never be committed to Git.

For production/operator builds, keep the real `.env` beside the Windows executable.

## Run Locally

```bat
python run.py
```

The importer starts by default at:

```text
http://127.0.0.1:5050
```

The browser is opened automatically.

## Database & Migrations

The desktop application uses SQLite.

At startup it automatically:

1. configures SQLite with WAL mode and a busy timeout;
2. detects legacy database schemas;
3. creates a backup when migration is required;
4. upgrades the database to the current schema.

Backups are stored under:

```text
instance/backups/
```

Do not delete the `instance/` directory when updating an operator installation unless the local data is intentionally being reset.

## Windows Build

The application is packaged using:

```text
SeloraInstagramImporter.spec
```

Build it with:

```bat
.venv\Scripts\activate

pyinstaller --clean --noconfirm SeloraInstagramImporter.spec
```

The resulting executable will be available at:

```text
dist\SeloraInstagramImporter.exe
```

### Operator Package

The operator normally needs:

```text
SeloraInstagramImporter.exe
.env
```

If Playwright cannot find a compatible browser on the operator machine, install Chromium or configure the required browser executable.

The application prevents multiple importer instances from running simultaneously.

## Safe Exit

Use the **خروج امن** button inside the application instead of terminating the process manually.

Safe Exit:

* stops accepting new operations;
* waits for active requests;
* attempts to release active Selora workspace locks;
* clears stale local lock state;
* closes database resources;
* shuts down the local server.

## Session Status

The Sessions page shows Crawl and Selora states independently.

Examples:

```text
Crawl:
- Pending
- Running
- Completed
- Failed

Selora:
- Not sent
- Sending
- Sent
- Last send failed
```

Remote workflow states such as review, approval, import and rejection are also displayed when available.

## Logs

Runtime logs are written to the local `logs/` directory.

Relevant logs include application, HTTP, crawler, media, upload and Selora integration activity.

When reporting a problem, include the logs from the time the issue occurred.

## Tests

Run the test suite with:

```bat
pytest
```

Tests cover crawler flows, persistence, import lifecycle, validation, Selora integration, logging and related application behavior.

## Updating an Operator Installation

Recommended update flow:

```text
1. Use Safe Exit
2. Keep .env and instance/
3. Replace SeloraInstagramImporter.exe
4. Start the new executable
5. Allow startup database migration to finish
6. Verify the Sessions page and Selora connection
```

## License

Licensed under the MIT License.

## Instagram accounts for desktop operators

On the local Importer, open **حساب‌های اینستاگرام** in the navigation menu.
Each operator adds a clearly labeled Instagram account, signs in exclusively on
`instagram.com` in the separate Chrome window, and waits for the UI to confirm
that the local session has been saved. Two-factor authentication is handled by
Instagram, never by Selora. The operator then selects the saved account on the
crawl form; the selected storage-state path is pinned for that crawl job.

Accounts are stored separately under `instance/instagram_operator_accounts/`
(ignored by Git). Neither credentials nor cookies are stored in the database
or returned by the account-management endpoints. A graceful Importer shutdown
cancels any outstanding login window. Removing an account deletes
its **local** session; operators should separately use Instagram's security
settings if they need to revoke a server-side session. If operators share a
Windows login, the OS does not isolate their browser sessions: use distinct
Windows user accounts or add Importer authentication for strict separation.

This does not guarantee all Instagram posts will be available: the platform can
still enforce rate limits, security checkpoints, or content access controls.
The old `CONNECT_INSTAGRAM.ps1` remains available for legacy single-session use.
