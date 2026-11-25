# Intelligent Support Routing

A runnable research prototype that classifies a customer request and ranks suitable support teams. It provides a small browser interface, a JSON API, a confidence-aware human-review path, and a synthetic dataset for demonstration.

## Run locally

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/uvicorn support_router.api:app --reload
```

Open <http://127.0.0.1:8000>. The API also exposes `/health`, `/api/teams`, `/api/route`, and `/api/requests`; interactive API documentation is available at `/docs`.

## Configure support teams and training examples

Set a private admin password before starting the server:

```bash
export SUPPORT_ADMIN_PASSWORD='choose-a-long-private-password'
.venv/bin/uvicorn support_router.api:app --reload
```

Open <http://127.0.0.1:8000/admin> and sign in with username `admin` and the password you configured. Authorized staff can update team names, routing descriptions, phone numbers, and customer instructions. They can also add a sample customer request and its verified team; the sample is saved locally and the model retrains immediately. Settings and examples are stored in `support_router.sqlite3` (override its path with `SUPPORT_ROUTER_DB`).

The admin page can also create a new support team. Enter its name, responsibilities, optional contact details, customer instructions, and at least one representative request with the correct team. The initial example is saved with the new team and the routing model is retrained. Add more diverse, verified examples from the existing training-example form to improve routing; one example alone is not enough to establish reliable performance.

The demo initializes Enat HR (`0912121212`) and IT (`0986680289`) contacts and example requests for employee-record corrections, password resets, and KYC maker/checker role questions. Verify contact details with the organization before relying on them. Access-role changes must follow organizational authorization and access-control policies. Use this prototype locally or behind HTTPS, and do not expose it directly to the public internet.

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

This compares a keyword baseline against TF-IDF/Logistic Regression using stratified cross-validation on the included synthetic examples. Results are only a pipeline demonstration; meaningful research conclusions require authorized real-world data, careful splits, and a reviewed evaluation design.
# ai-intelligent-support-routing
