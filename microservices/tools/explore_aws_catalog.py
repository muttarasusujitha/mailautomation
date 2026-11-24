"""Temporary read-only inspection of public AWS pricing catalog fields."""
from itertools import islice
from shared.live_lab_pricing import _aws_catalog

for service in ("AmazonEKS", "AmazonS3", "AmazonRDS", "AmazonCloudWatch", "AWSCodeBuild"):
    print("SERVICE", service)
    rows = [row for row, _ in islice(_aws_catalog(service, "ap-south-1"), 100000)]
    print("rows", len(rows))
    selected = [
        (row.get("Product Family"), row.get("Unit"), row.get("PricePerUnit"),
         row.get("PriceDescription"), row.get("usageType"), row.get("operation"))
        for row in rows
        if row.get("TermType") == "OnDemand" and row.get("Unit") in {"Hrs", "GB-Mo", "GB", "minutes"}
    ]
    for item in selected[:15]:
        print(item)
