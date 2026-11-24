"""Explainable provider service mapping for hands-on training topics.

This maps explicit service names in a ToC to the cost engine's resource
families. It proposes lab resources; it never provisions cloud resources.
"""
import re

from shared.lab_cost_inputs import SERVICE_METER_REQUIREMENTS
from shared.lab_curriculum import lab_units, unit_text


# Provider docs used for the crosswalk. The cost model intentionally supports
# only its current VM, managed Kubernetes, managed database, and object-storage
# families. Other billable services must receive their own metered cost model.
SERVICE_CATALOG = {
    "aws": (
        ("Amazon EC2", (r"\bec2\b", r"\belastic compute cloud\b"), "vm", True),
        ("Amazon EKS", (r"\beks\b", r"\belastic kubernetes service\b"), "k8s", True),
        ("Amazon RDS", (r"\brds\b", r"\brelational database service\b"), "database", True),
        ("Amazon Aurora", (r"\bamazon aurora\b", r"\baurora serverless\b", r"\baurora\b"), None, False),
        ("Amazon S3", (r"\bs3\b", r"\bsimple storage service\b"), "storage", True),
        ("Amazon EBS", (r"\bebs\b", r"\belastic block store\b"), "disk", True),
        ("Amazon EFS", (r"\befs\b", r"\belastic file system\b"), None, False),
        ("Elastic Load Balancing (ALB/NLB)", (r"\balb\b", r"\bapplication load balancer\b", r"\bnlb\b", r"\bnetwork load balancer\b"), None, False),
        ("AWS NAT Gateway", (r"\bnat gateway\b",), None, False),
        ("Amazon Route 53", (r"\broute\s*53\b",), None, False),
        ("Amazon CloudFront", (r"\bcloudfront\b",), None, False),
        ("Amazon EventBridge", (r"\beventbridge\b",), None, False),
        ("Amazon Kinesis", (r"\bkinesis\b",), None, False),
        ("Amazon S3 Glacier", (r"\bs3 glacier\b", r"\bglacier storage\b"), None, False),
        ("AWS Systems Manager", (r"\bsystems manager\b", r"\bssm\b"), None, False),
        ("AWS Lambda", (r"\blambda\b",), None, False),
        ("Amazon API Gateway", (r"\bapi gateway\b",), None, False),
        ("AWS Step Functions", (r"\bstep functions\b",), None, False),
        ("Amazon DynamoDB", (r"\bdynamodb\b",), None, False),
        ("Amazon ECS/Fargate", (r"\bfargate\b", r"\becs\b", r"\belastic container service\b"), None, False),
        ("Amazon ECR", (r"\becr\b", r"\belastic container registry\b"), None, False),
        ("Amazon CloudWatch", (r"\bcloudwatch\b",), None, False),
        ("AWS CloudTrail", (r"\bcloudtrail\b",), None, False),
        ("AWS Secrets Manager", (r"\bsecrets manager\b",), None, False),
        ("AWS Key Management Service (KMS)", (r"\bkms\b", r"\bkey management service\b"), None, False),
        ("Amazon SageMaker", (r"\bsagemaker\b",), None, False),
        ("Amazon Bedrock", (r"\bbedrock\b",), None, False),
        ("Amazon Redshift", (r"\bredshift\b",), None, False),
        ("AWS Glue", (r"\bglue\b",), None, False),
        ("AWS CodeBuild/CodePipeline", (r"\bcodebuild\b", r"\bcodepipeline\b", r"\baws ci/cd\b"), None, False),
        ("Amazon SQS/SNS", (r"\bsqs\b", r"\bsns\b", r"\bsimple queue service\b", r"\bsimple notification service\b"), None, False),
        ("Amazon VPC", (r"\bvpc\b", r"\bvirtual private cloud\b"), None, True),
        ("AWS IAM", (r"\biam\b", r"\bidentity and access management\b"), None, True),
        ("AWS CodeBuild/CodePipeline", (r"\bcodebuild\b", r"\bcodepipeline\b"), None, False),
    ),
    "azure": (
        ("Azure Virtual Machines", (r"\bazure vm\b", r"\bazure virtual machine(?:s)?\b", r"\bvirtual machines?\b", r"\bvms?\b"), "vm", True),
        ("Azure Kubernetes Service (AKS)", (r"\baks\b", r"\bazure kubernetes service\b"), "k8s", True),
        ("Azure SQL", (r"\bazure sql\b", r"\bazure sql database\b"), "database", True),
        ("Azure Blob Storage", (r"\bblob storage\b", r"\bazure blob\b"), "storage", True),
        ("Azure Managed Disks", (r"\bmanaged disks?\b", r"\bazure disks?\b"), "disk", True),
        ("Azure Database for PostgreSQL/MySQL", (r"\bazure database for postgresql\b", r"\bazure database for mysql\b", r"azure database for postgresql", r"azure database for mysql"), None, False),
        ("Azure Files", (r"\bazure files\b",), None, False),
        ("Azure Load Balancer", (r"\bazure load balancer\b",), None, False),
        ("Azure DNS", (r"\bazure dns\b",), None, False),
        ("Azure Front Door", (r"\bfront door\b",), None, False),
        ("Azure Application Gateway", (r"\bapplication gateway\b",), None, False),
        ("Azure NAT Gateway", (r"\bnat gateway\b",), None, False),
        ("Azure Functions", (r"\bazure functions?\b",), None, False),
        ("Azure API Management", (r"\bapi management\b", r"\bapim\b"), None, False),
        ("Azure Cosmos DB", (r"\bcosmos db\b",), None, False),
        ("Azure Container Registry", (r"\bacr\b", r"\bcontainer registry\b"), None, False),
        ("Azure Container Apps", (r"\bcontainer apps?\b",), None, False),
        ("Azure App Service", (r"\bazure app service\b", r"\bapp service plan\b"), None, False),
        ("Azure Key Vault", (r"\bkey vault\b",), None, False),
        ("Azure Event Hubs", (r"\bevent hubs?\b",), None, False),
        ("Azure Service Bus", (r"\bservice bus\b",), None, False),
        ("Azure Event Grid", (r"\bevent grid\b",), None, False),
        ("Azure Logic Apps", (r"\blogic apps?\b",), None, False),
        ("Azure Monitor", (r"\bazure monitor\b",), None, False),
        ("Azure Data Factory", (r"\bdata factory\b",), None, False),
        ("Azure Databricks", (r"\bazure databricks\b", r"\bdatabricks\b"), None, False),
        ("Azure Machine Learning", (r"\bazure machine learning\b",), None, False),
        ("Azure OpenAI Service", (r"\bazure openai\b",), None, False),
        ("Azure Virtual Network", (r"\bvnet\b", r"\bvirtual network\b"), None, True),
        ("Azure role-based access control", (r"\bazure rbac\b", r"\brole-based access control\b"), None, True),
        ("Azure DevOps Pipelines", (r"\bazure devops\b", r"\bazure pipelines\b"), None, False),
    ),
    "gcp": (
        ("Google Compute Engine", (r"\bcompute engine\b", r"\bgce\b"), "vm", True),
        ("Google Kubernetes Engine (GKE)", (r"\bgke\b", r"\bgoogle kubernetes engine\b"), "k8s", True),
        ("Google Cloud SQL", (r"\bcloud sql\b",), "database", True),
        ("Google Cloud Storage", (r"\bcloud storage\b", r"\bgcs\b"), "storage", True),
        ("Google Persistent Disk", (r"\bpersistent disk\b",), "disk", True),
        ("Google Cloud Load Balancing", (r"\bcloud load balancing\b", r"\bgoogle load balancer\b"), None, False),
        ("Google Cloud NAT", (r"\bcloud nat\b",), None, False),
        ("Google Cloud Functions", (r"\bcloud functions\b",), None, False),
        ("Google Cloud Run", (r"\bcloud run\b",), None, False),
        ("Google BigQuery", (r"\bbigquery\b",), None, False),
        ("Google Cloud KMS", (r"\bcloud kms\b",), None, False),
        ("Google Cloud Logging", (r"\bcloud logging\b",), None, False),
        ("Google Cloud DNS", (r"\bcloud dns\b",), None, False),
        ("Google Pub/Sub", (r"\bpub\s*/?\s*sub\b",), None, False),
        ("Google Artifact Registry", (r"\bartifact registry\b",), None, False),
        ("Google Cloud Build", (r"\bcloud build\b",), None, False),
        ("Google IAM", (r"\bgoogle cloud iam\b", r"\bgcp iam\b"), None, True),
    ),
}


def services_for_day(text, provider, *, allow_provider_generic=True):
    """Return explicitly named services, their billable families, and gaps."""
    provider = str(provider or "").strip().lower()
    if provider not in SERVICE_CATALOG:
        return []
    text = str(text or "").lower()
    matches = []
    for name, patterns, family, modelled in SERVICE_CATALOG[provider]:
        # "VM" and "virtual machine" are generic lab terms. Treat them as
        # Azure only when Azure is the selected provider; while scanning other
        # providers for explicit mismatches, require Azure-qualified wording.
        if (name == "Azure Virtual Machines" and not allow_provider_generic
                and not re.search(r"\bazure\b", text, re.IGNORECASE)):
            continue
        if name == "Amazon API Gateway" and not re.search(
                r"\b(aws|amazon|lambda|eventbridge|step functions|aws sam)\b",
                text, re.IGNORECASE):
            continue
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            matches.append({
                "name": name,
                "resource_family": family,
                "cost_modelled": modelled,
                "direct_hourly_charge": family is not None,
            })
    return matches


def architecture_summary(toc, provider, kubernetes_tier="free"):
    """Build a deterministic per-day service plan and identify cost gaps."""
    days = []
    missing_prices = []
    for index, day in enumerate(toc.get("days") or [], 1):
        units = lab_units(day)
        full_text = " ".join(unit_text(unit) for unit in units)
        services = services_for_day(full_text, provider)
        day_name = str(day.get("focus_area") or day.get("title") or day.get("topic") or f"Day {index}")
        names = [item["name"] for item in services]
        service_names = set(names)
        if str(provider).lower() == "aws":
            extra_patterns = (
                ("Elastic Load Balancing (ALB/NLB)", r"\b(load balancer|load-balanced|alb|nlb)\b"),
                ("Amazon DynamoDB", r"\bdynamodb\b"),
                ("Amazon Aurora", r"\b(aurora)\b"),
                ("Amazon ECS/Fargate", r"\b(ecs|fargate|elastic container service)\b"),
                ("Amazon ECR", r"\b(ecr|elastic container registry)\b"),
                ("Amazon CloudWatch", r"\bcloudwatch\b"),
                ("AWS Secrets Manager", r"\bsecrets manager\b"),
                ("AWS Key Management Service (KMS)", r"\b(kms|key management service)\b"),
                ("AWS CloudTrail", r"\bcloudtrail\b"),
                ("AWS NAT Gateway", r"\bnat gateway\b"),
                ("Amazon Route 53", r"\b(route 53|dns)\b"),
                ("Amazon CloudFront", r"\b(cloudfront|cdn)\b"),
                ("Amazon S3 Glacier", r"\b(glacier|archive storage)\b"),
                ("Amazon EFS", r"\b(efs|elastic file system)\b"),
                ("Amazon Kinesis", r"\bkinesis\b"),
                ("AWS Systems Manager", r"\b(systems manager|ssm)\b"),
                ("Amazon SageMaker", r"\bsagemaker\b"),
                ("Amazon Bedrock", r"\bbedrock\b"),
                ("AWS Glue", r"\bglue\b"),
                ("AWS CodeBuild/CodePipeline", r"\b(codebuild|codepipeline)\b"),
                ("Amazon SQS/SNS", r"\b(sqs|sns|simple queue service|simple notification service)\b"),
            )
            service_names.update(name for name, pattern in extra_patterns
                                 if re.search(pattern, full_text, re.IGNORECASE))
        elif str(provider).lower() == "azure":
            extra_patterns = (
                ("Azure Database for PostgreSQL/MySQL", r"\bazure database for (postgresql|mysql)\b"),
                ("Azure Load Balancer", r"\bazure load balancer\b"),
                ("Azure DNS", r"\bazure dns\b"),
                ("Azure API Management", r"\b(api management|apim)\b"),
                ("Azure Files", r"\b(azure files|file share)\b"),
                ("Azure Front Door", r"\b(front door|cdn)\b"),
                ("Azure NAT Gateway", r"\bnat gateway\b"),
                ("Azure Functions", r"\b(azure functions|functions app)\b"),
                ("Azure Cosmos DB", r"\b(cosmos db|cosmosdb)\b"),
                ("Azure Container Registry", r"\b(acr|container registry)\b"),
                ("Azure Container Apps", r"\bcontainer apps?\b"),
                ("Azure App Service", r"\b(app service|web app)\b"),
                ("Azure Key Vault", r"\b(key vault|keyvault)\b"),
                ("Azure Event Hubs", r"\bevent hubs?\b"),
                ("Azure Service Bus", r"\bservice bus\b"),
                ("Azure Event Grid", r"\bevent grid\b"),
                ("Azure Logic Apps", r"\blogic apps?\b"),
                ("Azure Monitor", r"\b(azure monitor|log analytics)\b"),
                ("Azure Data Factory", r"\bdata factory\b"),
                ("Azure Databricks", r"\bdatabricks\b"),
                ("Azure Machine Learning", r"\b(azure machine learning|azure ml)\b"),
                ("Azure OpenAI Service", r"\bazure openai\b"),
                ("Azure DevOps Pipelines", r"\b(azure devops|azure pipelines)\b"),
            )
            service_names.update(name for name, pattern in extra_patterns
                                 if re.search(pattern, full_text, re.IGNORECASE))
        elif str(provider).lower() == "gcp":
            extra_patterns = (
                ("Google Cloud Load Balancing", r"\b(load balancer|load balancing|ingress)\b"),
                ("Google Cloud DNS", r"\b(dns|route 53)\b"),
                ("Google Cloud Run", r"\b(cloud run|serverless container)\b"),
                ("Google BigQuery", r"\bbigquery\b"),
                ("Google Cloud NAT", r"\bcloud nat\b"),
                ("Google Cloud Functions", r"\b(cloud functions|cloud function)"),
                ("Google Cloud KMS", r"\bcloud kms\b"),
                ("Google Cloud Logging", r"\b(cloud logging|logging)\b"),
                ("Google Pub/Sub", r"\b(pub\s*/?\s*sub|pubsub)\b"),
                ("Google Artifact Registry", r"\bartifact registry\b"),
                ("Google Cloud Build", r"\bcloud build\b"),
            )
            service_names.update(name for name, pattern in extra_patterns
                                 if re.search(pattern, full_text, re.IGNORECASE))
        billable_policy_services = sorted(service_names & set(SERVICE_METER_REQUIREMENTS))
        plan = []
        families = {item["resource_family"] for item in services if item["resource_family"]}
        if "vm" in families:
            plan.append("one learner VM per participant")
        if "k8s" in families:
            cluster = "one shared managed cluster per course"
            if str(provider).lower() == "aws":
                cluster += " (EKS control plane plus worker nodes)"
            elif str(provider).lower() == "gcp":
                cluster += " (GKE control plane plus worker nodes)"
            else:
                tier = str(kubernetes_tier or "free").strip().title()
                cluster += f" (AKS {tier} control-plane tier plus billed worker VMs)"
            plan.append(cluster)
        if "database" in families:
            plan.append("one shared database instance")
        if "storage" in families:
            plan.append("shared object storage by configured GB")
        if "disk" in families:
            plan.append("attached block storage")
        unpriced = [item["name"] for item in services if not item["cost_modelled"]]
        explicit_products = billable_policy_services
        unpriced.extend(name for name in billable_policy_services if name not in unpriced)
        missing_prices.extend(unpriced)
        other_providers = [name for name in SERVICE_CATALOG if name != str(provider).lower()]
        other_services = [item for other_provider in other_providers
                          for item in services_for_day(
                              full_text, other_provider, allow_provider_generic=False)]
        explicit_other_cloud = [item["name"] for item in other_services if item["resource_family"]]
        if explicit_other_cloud:
            missing_prices.extend(f"provider mismatch: {name} requires its matching cloud provider" for name in explicit_other_cloud)
        generic_kubernetes = bool(re.search(r"\b(kubernetes|k8s)\b", full_text, re.IGNORECASE))
        local_cluster_tool = bool(re.search(r"\b(minikube|kind cluster)\b", full_text, re.IGNORECASE))
        explicit_managed_cluster = any(name in {"Amazon EKS", "Azure Kubernetes Service (AKS)",
                                                "Google Kubernetes Engine (GKE)"}
                                       for name in names + [item["name"] for item in other_services])
        if generic_kubernetes and not explicit_managed_cluster:
            if local_cluster_tool:
                plan.append("local Minikube/Kind cluster on learner machines; no managed-cluster charge")
                names.append("Minikube/Kind (local Kubernetes)")
            else:
                plan.append("local Kubernetes cluster on learner machines; no managed-cluster charge")
        # Carry the source lab's actual tools and task through the architecture
        # result so trainers can review the tool-to-experiment mapping.
        tools = []
        experiments = []
        for unit in units:
            unit_tools = unit.get("tools") or []
            if isinstance(unit_tools, str):
                unit_tools = [unit_tools]
            tools.extend(str(tool).strip() for tool in unit_tools if str(tool).strip())
            experiment = unit.get("lab_task") or unit.get("lab")
            if experiment and str(experiment).strip():
                experiments.append(str(experiment).strip())
        tools = list(dict.fromkeys(tools))
        broad_cloud_plan = bool(re.search(r"\b(all cloud tools|multi-cloud|multicloud|cloud capstone)\b", full_text, re.IGNORECASE))
        if broad_cloud_plan and not explicit_managed_cluster and not families:
            missing_prices.append("cloud capstone: specify provider, named services, and resource quantities")
            unpriced.append("cloud capstone: specify provider, named services, and resource quantities")
        if not names and not plan and not unpriced:
            continue
        detail = ", ".join(list(dict.fromkeys(names + explicit_products)))
        if plan:
            detail = (detail + " -> " if detail else "") + "; ".join(plan)
        if unpriced:
            detail += "; pricing model required for " + ", ".join(unpriced)
        days.append({"day": index, "topic": day_name, "services": names, "tools": tools,
                     "experiment": "; ".join(experiments), "plan": detail,
                     "unpriced_services": unpriced})
    return {"provider": str(provider or "").lower(), "days": days,
            "unpriced_services": sorted(set(missing_prices))}
