# CogniStudy Deployment Checklist

## 1. Production secrets and config

Set these environment variables in your hosting platform:

- `COGNISTUDY_DB_HOST`
- `COGNISTUDY_DB_PORT`
- `COGNISTUDY_DB_USER`
- `COGNISTUDY_DB_PASSWORD`
- `COGNISTUDY_DB_NAME`
- `COGNISTUDY_API_KEY`
- `COGNISTUDY_GMAIL_SENDER_EMAIL`
- `COGNISTUDY_GMAIL_APP_PASSWORD`
- `COGNISTUDY_ADMIN_FULLNAME`
- `COGNISTUDY_ADMIN_EMAIL`
- `COGNISTUDY_ADMIN_PASSWORD`
- `COGNISTUDY_ALLOW_INSECURE_SECRET_STORAGE=false`

Optional:

- `COGNISTUDY_SYSTEM_PROMPT`

The app prefers environment variables first.

For public deployments:

- keep `COGNISTUDY_ALLOW_INSECURE_SECRET_STORAGE=false`
- provide `COGNISTUDY_API_KEY` through the host environment
- provide `COGNISTUDY_GMAIL_APP_PASSWORD` through the host environment
- use `COGNISTUDY_ADMIN_EMAIL` and `COGNISTUDY_ADMIN_PASSWORD` on the first startup so the initial admin can be created

## 2. Database

Provision a MySQL database and make sure the app can reach it from your hosting provider.

The application initializes its schema on startup through `initialize_database()`, so the configured database user must be able to create tables in the target database.

## 3. Startup command

This repo includes a `Procfile`:

```text
web: streamlit run app.py --server.port=$PORT --server.address=0.0.0.0
```

If your platform does not read `Procfile`, use that command as the start command manually.

## 4. Production verification

After deployment, verify these flows in order:

1. Sign in with the admin account.
2. Open Admin > API Settings and confirm the active API and email settings are correct.
3. Create a test user account and confirm the welcome email arrives.
4. Run Forgot Password for that account and confirm the reset email arrives and password reset succeeds.
5. Generate a reviewer from System Overview.
6. Generate a quiz from the reviewer using Beginner, Intermediate, and Advanced to confirm all difficulty paths work.
7. Complete a quiz and confirm Grade Analytics updates.
8. Confirm Reviewer Library open/download/delete actions still work.

## 5. Security follow-up

Before publishing publicly:

- Rotate any API keys or Gmail app passwords that were previously stored in local files or shared in chat.
- Do not commit `db_config.json`, `api_key.txt`, `.env`, or `.streamlit/secrets.toml`.
- Use a strong production value for `COGNISTUDY_ADMIN_PASSWORD`.
- Remove or archive local plaintext secret files after rotating them.
