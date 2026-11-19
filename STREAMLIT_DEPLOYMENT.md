# Streamlit Community Cloud deployment

## Public synthetic sandbox

The prepared deployment now includes `.public-sandbox`. This marker makes the existing `tsh_advisory/app.py` entry point synthetic-only, isolates each visitor in a random server-side session directory, hides credentials/settings, and rejects paid research in Engine and LiveProvider. It does not expose local saved projects. Alternatively use `streamlit_demo.py` as the cloud entry point. Do not remove both protections on a public deployment.

Visitors can edit their session copy, recalculate and export synthetic reports. Reset deletes that copy immediately. Open tabs send a heartbeat; abandoned data expires after one hour, swept every minute while the process is running and at startup. Browser close events are not used as a deletion guarantee. Reconnecting the same WebSocket session may preserve edits until reset or expiry. Downloads already saved by the visitor are outside server cleanup. Names/approvals in the sandbox are simulated identities, not authenticated sign-offs.

For this public demo, do not configure an OpenAI API key. Existing private cloud history is not migrated to anonymous visitors; local projects remain separate. Public sharing is configured in Streamlit, not by making the code repository public.

Create a private GitHub repository named `bioanalytical-advisory` and upload only the contents of the prepared deployment ZIP, after extracting it. Do not upload the ZIP itself or the entire original project folder.

In https://share.streamlit.io choose Create app and select the repository, branch `main`, and main file `tsh_advisory/app.py`. Under Advanced settings choose Python 3.14 to match the locally tested runtime, if available. The dependency versions are taken from the working local environment; the cloud installation still needs verification.

For live runs, add your OpenAI key in Streamlit's private Secrets settings, never in GitHub:

```toml
OPENAI_API_KEY = "your-key-here"
```

Keep access restricted to authorized class reviewers. The app currently shares one local database among its users and does not implement per-user project isolation. A configured provider key can be used by people with app access.

The deployment package excludes existing saved projects, uploaded documents, local configuration, credentials and generated reports. The hosted copy starts empty. Local saved projects remain unchanged.

Community Cloud local storage is not a durable archive. Download report/evidence bundles after each run. This deployment is suitable for a class demonstration; durable production decision records require external storage and authentication work.

After deployment verify: intake opens, a synthetic fixture completes, editable kit/cost tables work, changed intake recalculates without a model call, named approvals save, and PDF/evidence downloads open. Then test one authorized live run. Do not claim the cloud deployment is verified until these checks pass.
