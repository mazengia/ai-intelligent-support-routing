# Intelligent Support Routing

A runnable research prototype that classifies a customer request and ranks suitable support teams. It provides a small browser interface, a JSON API, a confidence-aware human-review path, and a synthetic dataset for demonstration.

Routing requests and optional user feedback are stored in SQLite. Authorized staff can review unresolved requests, assign a verified team, record reviewer notes, and optionally add resolved requests as training examples.

## Run locally

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/uvicorn support_router.api:app --reload
run
.venv/bin/uvicorn export SUPPORT_ADMIN_PASSWORD='choose-a-long-private-password'
.venv/bin/uvicorn .venv/bin/uvicorn support_router.api:app --reload
```

Open <http://127.0.0.1:8000>. The API also exposes `/health`, `/api/teams`, `/api/route`, and `/api/requests`; interactive API documentation is available at `/docs`.

## Configure support teams and training examples

Set a private admin password before starting the server:

```bash
export SUPPORT_ADMIN_PASSWORD='choose-a-long-private-password'
.venv/bin/uvicorn support_router.api:app --reload
```

Open <http://127.0.0.1:8000/admin> and sign in with username `admin` and the password you configured. The admin page uses a signed, HTTP-only, same-site session cookie that lasts up to eight hours, so refreshing the page keeps the workspace available without saving the password in browser storage. Use **Sign out** to end the session. Authorized staff can update team names, routing descriptions, phone numbers, and customer instructions. They can also add a sample customer request and its verified team; the sample is saved locally and the model retrains immediately. Settings and examples are stored in `support_router.sqlite3` (override its path with `SUPPORT_ROUTER_DB`).

The admin page can also create, edit, enable, disable, or permanently delete support teams. The initial demo training examples are copied into the database and can be edited, reassigned, or deleted alongside examples added by admins. Team deletion also deletes its saved examples; disabling a team keeps its information but removes it from customer recommendations. A team must retain at least one training example, and at least one team must remain enabled. Creating a team requires its name, responsibilities, optional contact details, customer instructions, and one representative request with the correct team. Changes retrain the model immediately. Add more diverse, verified examples; one example alone is not enough to establish reliable performance.

The demo initializes Enat HR (`0912121212`) and IT (`0986680289`) contacts and example requests for employee-record corrections, password resets, and KYC maker/checker role questions. Verify contact details with the organization before relying on them. Access-role changes must follow organizational authorization and access-control policies. Use this prototype locally or behind HTTPS, and do not expose it directly to the public internet.

## Admin workspace tabs

After signing in at <http://127.0.0.1:8000/admin>, use the left navigation to open these sections:

| Tab | What it does | How to use it |
| --- | --- | --- |
| **Add a team** | Creates a support team and adds its first labeled request as a training example. | Enter a unique team name, describe the issues it handles, and optionally provide verified contact details and safe customer instructions. Add one representative request and select **Add team and train model**. The team is enabled and immediately available to routing. |
| **Manage teams** | Edits a team's display name, routing description, contact details, and customer guidance. It also controls whether a team is enabled or deleted. | Choose a team, update the fields, and select **Save changes**. Use **Disable team** to remove it from recommendations without deleting it. Use **Delete team** only when you intend to permanently remove the team and its saved training examples. At least one team must stay enabled. |
| **Training examples** | Adds, reviews, corrects, and removes labeled examples used by the routing model. | Enter a representative customer request, choose the team that actually handles it, and select **Save example and retrain**. Existing examples can be edited and reassigned or deleted. Use short, varied, verified examples; avoid personal or sensitive information. |
| **Human review** | Shows unresolved requests that the model could not route confidently. Staff can record the verified destination and optionally use that decision as a training example. | Open a request, choose the correct enabled team, optionally add a reviewer note, then select **Resolve and retrain**. Clear **Add this verified request to training data** if the request should not be used for training. |

Team, description, and training-example changes retrain the model in the running process. On the next server start, the model is rebuilt from the stored examples. The human-review queue contains requests flagged for review; a high-confidence recommendation is not automatically sent to a support team. Use **Sign out** when finished.

## Import authorized organizational tickets

The repository does not contain real organizational tickets. Obtain written approval from the data owner and follow your institution's privacy, retention, and research-ethics requirements before using any. Keep the source CSV outside this repository and use UTF-8 CSV with `text` and `team_id` columns. `team_id` must match an enabled team ID from the admin page. Remove names, addresses, free-form identifiers, and other information that this prototype's automatic redactor may not recognize. The redactor masks common emails, phone/long-number strings, labeled identifiers, credentials, and URLs before data is stored or evaluated; it is not a guarantee of anonymization.

Import sanitized examples into the configured local SQLite database. The explicit confirmation flag is required:

```bash
export SUPPORT_ROUTER_DB="$HOME/support-router-private.sqlite3"
.venv/bin/python -m support_router.import_data "$HOME/private-support-tickets.csv" --confirm-authorized
```

When authorized examples are imported, built-in demo examples are excluded from model training. Restart the server to load the updated model. Do not commit the source CSV or share the SQLite database; restrict file access and delete data according to the data owner's retention policy.

## Held-out evaluation on authorized data

Use the same approved CSV before deployment. Exact normalized duplicates are excluded, and conflicting labels for duplicate requests are rejected. The stratified split is reproducible and defaults to 20% held out:

```bash
.venv/bin/python -m support_router.evaluate \
  --dataset "$HOME/private-support-tickets.csv" \
  --authorized-data \
  --test-size 0.2
```

The report includes accuracy, macro-F1, per-team metrics, and a confusion matrix. These metrics evaluate category classification on the held-out split; they do not establish probability calibration, production readiness, or performance on future requests. Review the split for near-duplicate/leakage and label quality with the data owner. Never report the synthetic demo evaluation as real-world validation.

Customer requests, training examples, reviewer notes, and older stored requests are redacted for common PII patterns before retention. Automatic redaction can miss names, addresses, and unusual identifiers: do not enter sensitive personal or financial data into this prototype, and manually de-identify approved training data. This prototype is not a substitute for a privacy/security review or production-grade data-loss prevention.

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/route \
  -H 'Content-Type: application/json' \
  -d '{"text":"I transferred money but the recipient has not received it"}'
```

## Routing approach

The prototype trains a TF-IDF/Logistic Regression classifier from `support_router/data/demo_tickets.csv`, compares the request with the support-team descriptions using TF-IDF cosine similarity, and blends the category and semantic-ranking signals. Requests below a confidence threshold, with a small top-candidate margin, or with very weak text similarity are referred to human review. The returned score is a ranking signal, **not a calibrated probability**.

The demonstration data and team descriptions are synthetic examples, not evidence of real-world routing performance. Replace them with authorized, privacy-reviewed, consistently labeled organizational data before drawing research conclusions or operationally routing customer requests. This initial implementation recommends teams only; employee expertise and live workload/availability data are not included.

## Tests

```bash
.venv/bin/pytest
```

## Offline baseline comparison

```bash
.venv/bin/python -m support_router.evaluate
```

This compares a keyword baseline against TF-IDF/Logistic Regression using stratified cross-validation on the included synthetic examples. Results are only a pipeline demonstration; use the held-out evaluation command above for authorized data.
# ai-intelligent-support-routing
