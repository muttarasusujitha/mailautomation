from pathlib import Path
import openpyxl

src = Path(r"C:\Users\sujit\Downloads\Lab_Cost_Estimator_No_Internal_Pricing.xlsx")
out = Path(r"C:\Users\sujit\Desktop\mail\outputs\Lab_Cost_Estimator_India_Mumbai_Updated.xlsx")
out.parent.mkdir(parents=True, exist_ok=True)

wb = openpyxl.load_workbook(src)
assumptions = wb["Assumptions"]
mapping = wb["TOC Mapping"]
breakdown = wb["Resource Cost Breakdown"]
client = wb["Client Estimate"]

# Make the regional assumption explicit and preserve the workbook's existing style.
assumptions["B5"] = "AWS"
assumptions["B6"] = "Mumbai"
assumptions["C6"] = "Mumbai / Central India / GCP Mumbai"
assumptions["D6"] = "India region used for the estimate; verify the provider's current regional price"
assumptions["A1"] = "Lab Cost Model – India/Mumbai Cloud Estimate"

# Basic Python is local/free unless the TOC explicitly asks for cloud resources.
mapping["C4"] = 0
mapping["D4"] = "Local / Free"
mapping["A10"] = (
    "Python fundamentals are local/free unless AWS, Azure, GCP, VM, cloud, or another cloud service is explicitly mentioned. "
    "Only named cloud resources are included in the estimate."
)

# Make VM quantity formula-driven from the TOC mapping (Docker + CI/CD in this template).
breakdown["B4"] = "=SUM('TOC Mapping'!$C$4:$C$8)"
breakdown["G4"] = "Mapped VM quantity × INR hourly rate × runtime hours"
breakdown["H4"] = "=B4*D4*F4"

# Keep Kubernetes costs explicit: control plane plus worker nodes.
breakdown["G5"] = "Cluster count × INR control-plane rate × runtime hours"
breakdown["G6"] = "Worker nodes × INR worker rate × runtime hours"

# Clarify the client-facing calculation and source assumptions.
client["A17"] = (
    "Estimate notes\nIndia/Mumbai estimate. Basic Python topics are treated as local/free unless cloud is explicitly requested. "
    "VM and Kubernetes resources use runtime hours; storage uses GB-month prorated by days; egress uses GB; "
    "build runners use build minutes. Rates are editable assumptions and must be verified before a final quote."
)

for ws in (assumptions, mapping, breakdown, client):
    ws.sheet_view.showGridLines = False

wb.save(out)
print(out)
