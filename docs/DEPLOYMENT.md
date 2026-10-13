# Deployment and expansion points

Nothing is deployed yet. Terraform for stages 1 and 2 is in [`infra/terraform/`](../infra/terraform);
CI validates it and plans both stages against a mocked AWS provider (`tofu test`).

| Stage | What runs where | Status | Rough cost / month |
|---|---|---|---|
| 0. Local | Laptop: lite mode or Docker | Working | $0 |
| 1. First AWS deploy | One EC2 host + S3 + RDS Postgres + CloudFront | Terraform written (`api_mode = "host"`) | ~$80-90 |
| 2. Scale the API | API on ECS Fargate behind an ALB; host keeps Kafka + workers | Terraform written (`api_mode = "fargate"`) | ~$200-220 |
| 3. Harden | HTTPS domain, CI deploys, alarms, more Kafka brokers, scaling workers | Listed below | depends |

Costs are on-demand us-east-1 estimates; check the [AWS pricing calculator](https://calculator.aws/).

## Stage 1: one Linux host

```
Browser ──HTTPS──> CloudFront ──/────────> S3 web bucket
                       └──/api, /ws──> EC2 host :8000 (CloudFront IPs only)
                                         api · pipeline-worker · ml-worker · runtime · Redpanda
                                         → S3 data buckets (instance role) · RDS Postgres (private)
```

- **Host:** `t3.large`, Amazon Linux 2023, 60 GB, Elastic IP, SSM shell (no SSH). First boot runs
  [`host/compose.yml`](../infra/terraform/host/compose.yml): the same image as the local stack.
- **S3:** four buckets suffixed with env + account id; raw demos move to Glacier IR after 30 days.
- **RDS:** Postgres 16 `db.t4g.micro`, private, encrypted, 7-day backups, password in Secrets Manager.
- **Secrets:** `cs2wp-dev/ghcr` (image pull), `cs2wp-dev/app` (later: Kalshi / GRID keys); set by hand.
- **Not created:** NAT gateway, load balancer, ECS (that is stage 2's cost).

**Decide first:** whose AWS account and who has admin; region and a budget alarm; the deployed site is
public to anyone with the URL (it shows match data and lets visitors switch the active model).

**Steps**

1. `aws configure sso`, then `export AWS_PROFILE=<profile>`. Create the budget alarm.
2. State bucket and lock table, once per account:
   ```bash
   ACCT=$(aws sts get-caller-identity --query Account --output text)
   aws s3 mb s3://cs2wp-tfstate-$ACCT
   aws s3api put-bucket-versioning --bucket cs2wp-tfstate-$ACCT --versioning-configuration Status=Enabled
   aws dynamodb create-table --table-name cs2wp-tflock --billing-mode PAY_PER_REQUEST \
     --attribute-definitions AttributeName=LockID,AttributeType=S --key-schema AttributeName=LockID,KeyType=HASH
   ```
   Then uncomment the `backend "s3"` block in `infra/terraform/main.tf`.
3. Apply:
   ```bash
   cd infra/terraform && tofu init && tofu plan -var-file=env/dev.tfvars && tofu apply -var-file=env/dev.tfvars
   tofu output        # web_url, host_instance_id, buckets, cloudfront_id
   ```
4. Image pull credentials: a GitHub classic token with `read:packages`; write
   `{"username":"<user>","password":"<token>"}` to `/tmp/ghcr.json` in an editor, then
   `aws secretsmanager put-secret-value --secret-id cs2wp-dev/ghcr --secret-string file:///tmp/ghcr.json && rm /tmp/ghcr.json`.
5. Start the services: `aws ssm start-session --target $(tofu output -raw host_instance_id)`, then `sudo /opt/cs2wp/start.sh`.
6. Load data from a laptop that has it:
   ```bash
   export CS2WP_STORAGE=s3 CS2WP_S3_BUCKET_DEMOS=<demos> CS2WP_S3_BUCKET_GS=<gs> CS2WP_S3_BUCKET_MODELS=<models>
   uv run cs2wp-pipeline catalog-export && uv run cs2wp-pipeline publish-all --skip-raw
   ```
   On the host: `cd /opt/cs2wp && sudo docker compose exec pipeline-worker cs2wp-pipeline catalog-import`.
7. Website:
   ```bash
   cd web && npm ci && npm run build && aws s3 sync dist/ s3://<web bucket> --delete
   aws cloudfront create-invalidation --distribution-id <cloudfront_id> --paths '/*'
   ```
8. Open `web_url`; `curl <web_url>/api/status` should list the maps.

**Day to day**

- Backend deploy: `main` builds `ghcr.io/michaeltgit/cs2wp:latest`; on the host run `sudo /opt/cs2wp/start.sh`
  (pin a version with `CS2WP_IMAGE=ghcr.io/michaeltgit/cs2wp:<sha>`). Website: step 7.
- Demos: add `downloader` to `COMPOSE_PROFILES` in `/opt/cs2wp/.env` and re-run `start.sh`, or
  `aws s3 cp match.rar s3://<demos>/uploads/`. If HLTV blocks AWS, run only the downloader elsewhere,
  pointed at the bucket.
- Commands on the host: `cd /opt/cs2wp && sudo docker compose exec ml-worker cs2wp-ml train --activate`
  (or `pipeline-worker cs2wp-pipeline <command>`). Logs: CloudWatch `/cs2wp/dev/host`.
- Memory: a parse peaks at ~2.3 GB, so workers parse one map at a time (`CS2WP_PARSE_CONCURRENCY`).
- Pause spending: stop the EC2 and RDS instances; `tofu destroy` removes everything.

## Stage 2: API on Fargate

`tofu apply -var-file=env/dev.tfvars -var api_mode=fargate`: two API tasks behind an ALB (1 h idle
timeout for WebSockets), a NAT gateway for image pulls, CloudFront `/api` and `/ws` → ALB. The host keeps
Kafka, workers and the runtime; re-run `start.sh` there to drop its API. Deploy with
`aws ecs update-service --cluster cs2wp-dev --service api --force-new-deployment`.

## Stage 3: harden

| Item | How |
|---|---|
| HTTPS to the origin | domain + ACM certificate, ALB 443 listener, `origin_protocol_policy = "https-only"` |
| Deploys from CI | GitHub OIDC → IAM role; `aws ssm send-command … start.sh`, `aws ecs update-service`, `aws s3 sync` |
| Alarms | CloudWatch on 5xx, host CPU/disk, RDS storage, failed jobs → email |
| Kafka redundancy | 3 Redpanda brokers or Amazon MSK; only `CS2WP_KAFKA_BOOTSTRAP` changes |
| Scaling workers | `pipeline-worker` as an ECS service on Fargate Spot (the job queue already supports many workers) |
| Database resilience | RDS Multi-AZ, 30-day backups, deletion protection |
| No GHCR secret | push the image to ECR from CI |

## Expansion points

The prototype is built so these plug in without reshaping it.

| Feature | Where it plugs in | Needs |
|---|---|---|
| GRID live feed | a producer emitting `RawGSFrame` on `raw-gs` (like `ReplayStreamer` in `pipeline/runtime.py`); inference, WebSocket and website unchanged | GRID access |
| Live-only runtime pieces: shared run per match, live state cache, run lifecycle table, restart checkpoints, event timestamps | `pipeline/runtime.py`, `core/db.py`, `core/contracts.py` | GRID |
| Kalshi order-book recorder | a host service publishing `MarketQuote` on `market-quotes` | Kalshi API key |
| Map-odds service | `MapEvidence` on `map-evidence` instead of computing in scoring | live matches |
| Team strength, learned | a training input in `ml/`, kept only if held-out results improve | results data (GRID) |
| Model at scale | bulk downloader run; training by ~10 match groups instead of one model per match (`ml/train.py`); a temporary large machine | storage, HLTV terms |
| Better features | `core/features.py`, retrain, keep what improves held-out results | more data |
