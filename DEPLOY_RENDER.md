# Deploy CogniStudy on Render

This setup assumes:

- the app is hosted on **Render**
- the database is hosted on an external **MySQL provider**
- secrets are stored in **Render environment variables**

## 1. Put the project in GitHub

Render deploys from a Git repository, so the project should be pushed to GitHub first.

Before pushing:

- make sure `.gitignore` is active
- do **not** commit real secrets from `db_config.json`, `api_key.txt`, or `.env`
- rotate any secrets that were previously exposed

## 2. Create the MySQL database

Render does not provide first-party MySQL the same way it provides PostgreSQL, so use one of these:

- Railway MySQL
- Aiven MySQL
- PlanetScale
- another hosted MySQL service

Collect these values:

- database host
- database port
- database user
- database password
- database name

## 3. Deploy on Render

### Option A: Blueprint deploy

1. In Render, choose **New +**
2. Select **Blueprint**
3. Connect your GitHub repository
4. Render will detect `render.yaml`
5. Fill in the environment variables before the first deploy

### Option B: Manual web service

If you prefer manual setup:

- **Runtime**: Python
- **Build command**: `pip install -r requirements.txt`
- **Start command**: `streamlit run app.py --server.port=$PORT --server.address=0.0.0.0`

## 4. Add these environment variables in Render

Required:

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

## 5. First boot expectations

On startup, the app runs its database initialization logic automatically.

If the database does not have any admin account yet, the first boot requires:

- `COGNISTUDY_ADMIN_EMAIL`
- `COGNISTUDY_ADMIN_PASSWORD`

The app will stop startup if those are missing or weak.

Make sure the database user has permission to:

- connect to the database
- create tables
- insert and update rows

## 6. Production verification checklist

After Render finishes deployment, test this order:

1. Open the deployed app URL.
2. Sign in as admin.
3. Open **Admin > API Settings** and confirm values are loading correctly.
4. Create a new user account.
5. Confirm the welcome email is delivered.
6. Test **Forgot Password** and confirm the reset code email arrives.
7. Reset the password and confirm it returns to sign in.
8. Generate a reviewer from **System Overview**.
9. Generate a quiz from the reviewer using:
   - Beginner
   - Intermediate
   - Advanced
10. Finish a quiz and confirm **Grade Analytics** updates.
11. Confirm **Reviewer Library** can open, download, and delete entries.
12. Confirm admin pages load correctly:
    - System Overview
    - User Database
    - API Settings
    - Audit Logs

## 7. Recommended next production hardening

After the first successful deployment:

- replace the default admin email if needed
- set a strong production admin password
- rotate the Gmail app password again if it was ever shared
- rotate the AI API key if it was ever stored in plaintext locally
- keep `COGNISTUDY_ALLOW_INSECURE_SECRET_STORAGE=false`
- consider adding a custom domain later
