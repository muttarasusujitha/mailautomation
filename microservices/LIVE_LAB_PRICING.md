# Fresh lab pricing

Every request to the document service's `/api/v1/documents/excel/toc/lab-cost`
fetches public USD retail rates before producing a workbook. Submitted numeric
rates and verification timestamps cannot certify a quote. No network price
cache is used across requests.

AWS uses the public regional bulk CSV API (no credentials). Azure uses the
Retail Prices API (no credentials). The GCP public Catalog API is supported
when its API key and exact catalog SKU selections are configured. Supported
regions are AWS Mumbai, Azure Central India, and GCP Mumbai.

## One-time architecture configuration

Supply `assumptions.pricing_selections` to the document endpoint, or
`pricing_selections` to the trainer `/api/v1/toc/generate-lab-cost` endpoint.
Alternatively maintain a `lab_pricing_catalogs` Mongo document with `provider`,
normalized `region` (`Mumbai` or `Central India`), and `selections`.

To find current selectors before saving a catalog, use the trainer's read-only
`GET /api/v1/toc/lab-cost/pricing-catalog/discover` endpoint. Pass
`cloud_provider`, `cloud_region`, and a `search` phrase. AWS also requires the
exact `service_code` (for example `AWSLambda`); Azure requires its exact
`service_name` (for example `Virtual Machines`); GCP requires `service_id` and
the configured catalog API key. Optional `unit` and `limit` narrow the results.
Discovery returns candidates only: compare the product, region, billing unit,
and experiment before selecting one. Save the exact selector with the trainer's
`PUT /api/v1/toc/lab-cost/pricing-catalog` endpoint, which validates the live
rate. It never saves guessed usage quantities.

Selection keys: VM, VM Light, VM Heavy, Kubernetes control plane, Kubernetes
worker, Disk, Storage, Egress, Build runner, Managed database, Monitoring,
plus explicitly configured additional service meters.
All editable rate rows must be mapped so changing workbook quantities cannot
activate an unchecked template price.

Each AWS selection needs `service` and either `sku` plus `rate_code`, or a
non-empty `attributes` object matching provider fields such as `Instance Type`,
`Operating System`, `Tenancy`, and `Volume Type`. Attribute selectors express
the lab architecture while the system resolves the current SKU/dimension each
time. Each Azure selection needs an exact `meter_id`. These are
architecture/billing choices; do not fill them with invented IDs. Rates are
subsequently fetched automatically each time. Source URLs:

- https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-the-aws-price-list-bulk-api-fetching-price-list-files-manually.html
- https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices

For GCP, set `GCP_BILLING_CATALOG_API_KEY` in both the trainer-service and
document-service runtime environments. The trainer verifies selectors when an
admin saves a catalog; the document service fetches rates when it generates a
quote. Configure every required rate-card row with its exact
`service_id` and `sku_id`. The service sends the key in the
`X-goog-api-key` header. Save the catalog through the trainer
`PUT /api/v1/toc/lab-cost/pricing-catalog` route; that route verifies each SKU
against the live public catalog before accepting it. GCP SKUs with ambiguous
tiers or unsupported unit conversions are rejected.

Google's setup instructions require enabling Cloud Billing Catalog API and an
API key: https://cloud.google.com/billing/docs/how-to/get-pricing-information-with-the-cloud-billing-catalog-api

To configure a service meter, first identify the actual products used by the
hands-on task. Add one selection per required meter with `unit_key`, the
provider's exact product/SKU selector, and `covers_services` naming the exact
service. Save the complete selector catalog with the trainer
`PUT /api/v1/toc/lab-cost/pricing-catalog` endpoint. Catalog validation checks
live rates without assuming any usage. For each quote, provide measured or
otherwise explicitly supplied quantities in `additional_resource_usage`; the
service does not fill these from generic defaults. It checks the documented
required meter components for
Lambda, DynamoDB, API Gateway, Step Functions, EventBridge, Secrets Manager,
KMS, load balancing, Route 53, ECR, CloudWatch, CloudTrail, NAT, CloudFront,
and Fargate, plus the other metered products listed in
`shared/lab_cost_inputs.py`. It fetches those rates live and adds the quantities
to the workbook; omitted selectors or quantities block the quote.

## Output and limitations

### Currently verified service-meter coverage (Mumbai / Central India)

The shared AWS Mumbai catalog has live-validated selectors for Lambda
invocations and GB-seconds, Step Functions state transitions, Secrets Manager
secret-months and API requests, and ALB hours and capacity-unit hours, in
addition to the core EC2, EKS, EBS and S3 rows. The Lambda GB-second selector
uses AWS's documented default x86-64 architecture and is restricted to the
catalog's first published price tier; estimates at or above that tier boundary
are rejected. Supply positive quantities for both Lambda meters in
`additional_resource_usage` for every Lambda quote. Choose a separate selector
if the lab explicitly uses ARM.

These selectors cover only their named meters; they do not make every AWS/Azure
service in `master_topic_banks.json` priceable. For example, the AWS Serverless
Computing topic also includes API Gateway and event triggers. API Gateway
requires the lab to specify REST versus HTTP API, and EventBridge billing is
payload-size based, so neither may be represented by a guessed request/event
count. Database topics need separate compute, storage, backup and request
formulas. Such topics remain blocked until their complete meter model and
explicit quantities are supplied. The Azure baseline catalog contains core VM,
AKS and Blob rows; it does not cover all Azure services in the bank.

`Live Price Check` contains SKU, meter/dimension, unit, region, current USD rate,
source, checked time, previous rate, percentage change, and review flag. The
document service stores full inputs, TOC, rates, changes, expiry, and the output
SHA-256 in `lab_cost_rate_snapshots`. Response headers carry the authoritative
quote ID, expiry and pricing status. Trainer audit records reference that ID.

Missing/ambiguous mappings and unsupported tiers/units return 422. Provider
outages return 503. No workbook is issued for these errors. The change threshold
is a workbook review flag, not an email alert or an approval workflow.

Public retail rates exclude private account discounts. FX, taxes, resource
quantities and retention hours remain supplied assumptions. The existing
workbook cannot represent tiered prices or multi-component services (for example
database storage plus compute) as a single unit rate: these fail verification
or require additional resource rows/formulas. Excel must recalculate formulas
on opening. Historic files remain unchanged; expiry does not prevent opening
or manually forwarding an old workbook.
