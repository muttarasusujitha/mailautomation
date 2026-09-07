# Fresh lab pricing

Every request to the document service's `/api/v1/documents/excel/toc/lab-cost`
fetches public USD retail rates before producing a workbook. Submitted numeric
rates and verification timestamps cannot certify a quote. No network price
cache is used across requests.

AWS uses the public regional bulk CSV API (no credentials). Azure uses the
Retail Prices API (no credentials). Current supported regions are Mumbai and
Central India respectively. GCP is explicitly blocked pending its connector.

## One-time architecture configuration

Supply `assumptions.pricing_selections` to the document endpoint, or
`pricing_selections` to the trainer `/api/v1/toc/generate-lab-cost` endpoint.
Alternatively maintain a `lab_pricing_catalogs` Mongo document with `provider`,
normalized `region` (`Mumbai` or `Central India`), and `selections`.

Selection keys: VM, VM Light, VM Heavy, Kubernetes control plane, Kubernetes
worker, Disk, Storage, Egress, Build runner, Managed database, Monitoring.
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

## Output and limitations

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
