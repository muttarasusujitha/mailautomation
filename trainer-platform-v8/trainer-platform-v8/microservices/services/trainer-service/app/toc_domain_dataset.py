"""Curriculum knowledge base for the Training TOC Agent.

This is not ML fine-tuning. It is a controlled domain library the agent uses
to build reliable day-wise training plans before any AI wording polish.
"""

import json
import os
import re


COMPACT_DOMAINS = {}
_COMPACT_DATASET_PATH = os.path.join(os.path.dirname(__file__), "datasets_compact")


def _load_compact_domains():
    global COMPACT_DOMAINS
    if COMPACT_DOMAINS:
        return
    if not os.path.isdir(_COMPACT_DATASET_PATH):
        return
    for filename in os.listdir(_COMPACT_DATASET_PATH):
        if not filename.lower().endswith(".json"):
            continue
        path = os.path.join(_COMPACT_DATASET_PATH, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        base_name = filename.rsplit(".", 1)[0]
        file_key = _normalise_key(base_name)
        key = _normalise_key(data.get("domain") or data.get("name") or file_key)
        if key:
            COMPACT_DOMAINS[key] = data
        if file_key and file_key != key:
            trimmed = re.sub(r"_[0-9]+$", "", file_key)
            if trimmed and trimmed not in COMPACT_DOMAINS:
                COMPACT_DOMAINS[trimmed] = data
            if file_key not in COMPACT_DOMAINS:
                COMPACT_DOMAINS[file_key] = data


def _compact_domain_to_standard(domain: dict) -> dict:
    return {
        "name": domain.get("name") or domain.get("domain") or "Training",
        "icon": domain.get("icon") or "book",
        "days": domain.get("days") or [],
        "jira_practice": domain.get("jira_practice") or {},
        "certifications": domain.get("certifications") or [],
    }


def topic(name, subtopics, tools, lab):
    return {"topic": name, "subtopics": subtopics, "tools": tools, "lab": lab}


DOMAINS = {
    "devops": {
        "name": "DevOps",
        "icon": "gear",
        "level_map": {
            "foundation": [
                topic("Linux Basics", ["File system", "Permissions", "Users & Groups", "Package Management", "Process Management"], ["Ubuntu", "Bash"], "Navigate filesystem, manage users, and inspect service logs"),
                topic("Shell Scripting", ["Variables", "Loops", "Conditions", "Functions", "Cron Jobs", "Input/Output"], ["Bash", "Vi/Vim"], "Write backup automation script"),
                topic("Networking Basics", ["OSI Model", "TCP/IP", "DNS", "HTTP/HTTPS", "Ports & Protocols", "SSH"], ["curl", "netstat", "nmap"], "Diagnose network issues and configure SSH"),
                topic("Git & GitHub", ["init/clone/add/commit", "Branching", "Merging", "Rebase", "PRs", "GitHub Flow", "Branch Protection"], ["Git", "GitHub"], "Team PR exercise and merge conflict resolution"),
            ],
            "core": [
                topic("Docker Basics", ["Containers vs VMs", "Images", "Dockerfile", "Multi-stage Builds", "Volumes", "Networking"], ["Docker", "Docker Hub"], "Dockerize a Node.js/Python app"),
                topic("Docker Compose", ["docker-compose.yml", "Services", "Networks", "Volumes", "Environment Variables", "Health Checks"], ["Docker Compose"], "Run a multi-container full-stack app"),
                topic("Jenkins CI/CD", ["Install & Setup", "Freestyle Jobs", "Declarative Pipeline", "Jenkinsfile", "Agents", "Shared Libraries"], ["Jenkins", "Maven", "Nexus"], "Build, test, Docker push pipeline"),
                topic("GitHub Actions", ["Workflows", "Triggers", "Jobs & Steps", "Matrix Builds", "Caching", "Artifacts", "OIDC"], ["GitHub Actions", "YAML"], "CI/CD pipeline with test and deploy stages"),
            ],
            "advanced": [
                topic("Terraform IaC", ["Providers", "Resources", "Variables", "Outputs", "State", "Modules", "Workspaces", "Remote Backend"], ["Terraform", "AWS", "S3"], "Provision VPC + EC2 + RDS with modules"),
                topic("Kubernetes Fundamentals", ["Architecture", "Pods", "Deployments", "Services", "Ingress", "ConfigMaps", "Secrets", "PV/PVC", "RBAC"], ["kubectl", "minikube", "k9s"], "Deploy microservices app with Ingress"),
                topic("Helm Charts", ["Chart Structure", "values.yaml", "Templating", "Install/Upgrade/Rollback", "Helm Repositories"], ["Helm"], "Package app as Helm chart"),
                topic("AWS Core", ["IAM", "EC2", "S3", "VPC", "RDS", "Lambda", "EKS", "ECS", "ALB/NLB", "CloudWatch"], ["AWS CLI", "AWS Console", "Terraform"], "Deploy 3-tier app on AWS with EKS + ALB"),
            ],
            "observability": [
                topic("Prometheus & Grafana", ["Exporters", "Scrape Configs", "PromQL", "Dashboards", "Alerts", "SLI/SLO"], ["Prometheus", "Grafana", "Alertmanager"], "Build SLO dashboard for Kubernetes app"),
                topic("ELK Stack", ["Elasticsearch", "Logstash", "Kibana", "Filebeat", "Log Pipelines", "Visualizations"], ["ELK", "Filebeat"], "Centralized log aggregation for containerized app"),
                topic("Alerting & Tracing", ["Alertmanager Rules", "PagerDuty", "Jaeger", "Zipkin", "Distributed Tracing", "Runbooks"], ["Jaeger", "Alertmanager"], "Configure on-call alert and trace a slow request"),
            ],
            "security": [
                topic("DevSecOps", ["SAST/DAST", "Trivy", "Snyk", "OPA/Gatekeeper", "Secrets Manager", "IAM Policies"], ["Trivy", "Snyk", "AWS Secrets Manager"], "Add security scan stage to CI/CD pipeline"),
            ],
            "capstone": [
                topic("End-to-End DevOps Project", ["Requirements", "Terraform Infra", "Dockerize App", "CI/CD", "K8s Deploy", "Monitoring", "Security Scan", "Demo"], ["All DevOps Tools"], "Live demo with Jira sprint retrospective"),
            ],
        },
        "jira_practice": {
            "daily": ["Update sprint board", "Log time on stories", "Move cards to In Progress/Done", "Add comments with build links"],
            "weekly": ["Sprint planning", "Sprint review", "Retrospective", "Velocity chart review", "Burndown analysis"],
        },
        "certifications": ["AWS Certified DevOps Engineer - Professional", "Certified Kubernetes Administrator (CKA)", "CKAD", "Terraform Associate", "GitHub Actions Certification", "Jenkins Certified Engineer", "Docker Certified Associate"],
    },
    "python": {
        "name": "Python",
        "icon": "python",
        "level_map": {
            "foundation": [
                topic("Python Basics", ["Syntax", "Data Types", "Variables", "Operators", "Input/Output", "Type Casting"], ["Python 3", "VS Code"], "Calculator and number guessing game"),
                topic("Control Flow & Functions", ["if/else", "Loops", "Functions", "Lambda", "Recursion", "Scope"], ["Python 3"], "Pattern programs and recursive algorithms"),
                topic("Data Structures", ["Lists", "Tuples", "Sets", "Dictionaries", "Comprehensions", "Stacks & Queues"], ["Python 3"], "Student grade management system"),
                topic("OOP", ["Classes", "Inheritance", "Polymorphism", "Encapsulation", "Magic Methods"], ["Python 3"], "Bank account and library management OOP project"),
            ],
            "core": [
                topic("File Handling & Exceptions", ["File Read/Write", "CSV/JSON", "Exception Handling", "Custom Exceptions", "Context Managers"], ["Python 3"], "Log file parser with error handling"),
                topic("Modules & Packages", ["Built-in Modules", "pip", "venv", "requirements.txt", "Package Creation"], ["pip", "venv"], "Build a reusable utility package"),
                topic("NumPy & Pandas", ["Arrays", "DataFrames", "Cleaning", "Filtering", "GroupBy", "Merge/Join"], ["NumPy", "Pandas", "Jupyter"], "Analyze sales/weather dataset"),
                topic("REST APIs & Flask", ["HTTP Methods", "Routes", "JSON", "Auth", "Error Handling", "Deployment"], ["Flask", "Postman"], "Build CRUD REST API with Flask"),
            ],
            "advanced": [
                topic("Django", ["MVT", "Models", "Views", "Templates", "ORM", "Admin", "Auth", "DRF"], ["Django", "DRF", "PostgreSQL"], "Blog app with authentication"),
                topic("FastAPI", ["Path Operations", "Pydantic", "Async/Await", "Dependencies", "OAuth2", "OpenAPI"], ["FastAPI", "Uvicorn", "SQLAlchemy"], "Async microservice with JWT auth"),
                topic("Testing & Automation", ["unittest", "pytest", "Fixtures", "Mocking", "Coverage", "Selenium"], ["pytest", "Selenium"], "API test suite and automation script"),
            ],
            "capstone": [topic("Python Capstone Project", ["API Design", "Database", "Authentication", "Testing", "Docker Deployment"], ["FastAPI/Django", "Docker", "PostgreSQL"], "Full-stack Python application deployment")],
        },
        "jira_practice": {"daily": ["Log development tasks", "Update story status", "Add code review links"], "weekly": ["Sprint planning", "Demo session", "Retrospective"]},
        "certifications": ["PCEP", "PCAP", "AWS Certified Developer - Associate"],
    },
    "react": {
        "name": "React.js",
        "icon": "react",
        "level_map": {
            "foundation": [
                topic("HTML5 & CSS3", ["Semantic HTML", "Forms", "Flexbox", "Grid", "Responsive Design"], ["VS Code", "Chrome DevTools"], "Responsive landing page"),
                topic("JavaScript ES6+", ["let/const", "Arrow Functions", "Destructuring", "Promises", "Async/Await", "Fetch API"], ["JavaScript"], "Fetch and display public API data"),
                topic("TypeScript Basics", ["Types", "Interfaces", "Generics", "Enums", "Type Narrowing"], ["TypeScript"], "Convert JS app to TypeScript"),
            ],
            "core": [
                topic("React Fundamentals", ["JSX", "Components", "Props", "State", "Events", "Lists", "Conditional Rendering"], ["React", "Vite"], "Interactive task manager"),
                topic("React Hooks", ["useState", "useEffect", "useRef", "useMemo", "useCallback", "Custom Hooks"], ["React DevTools"], "Data fetching app with custom hooks"),
                topic("React Router & Forms", ["Routes", "Params", "Navigation", "Controlled Forms", "Validation"], ["React Router", "React Hook Form"], "Multi-page app with form validation"),
                topic("State Management", ["Context API", "Redux Toolkit", "Slices", "Thunks", "RTK Query", "Zustand"], ["Redux Toolkit", "Zustand"], "Shopping cart with async API calls"),
            ],
            "advanced": [
                topic("API Integration & Performance", ["Axios", "React Query", "Error Boundaries", "Suspense", "Lazy Loading", "Memoization"], ["Axios", "React Query"], "Dashboard with lazy loading"),
                topic("Styling & UI", ["Tailwind", "CSS Modules", "shadcn/ui", "Framer Motion", "Accessibility"], ["Tailwind", "Framer Motion"], "Animated UI component library"),
                topic("Testing & Deployment", ["Jest", "RTL", "Vitest", "Cypress", "CI/CD", "Vercel"], ["Jest", "Cypress", "Vercel"], "Test suite and Vercel deployment"),
            ],
            "capstone": [topic("React Capstone Project", ["Architecture", "API Integration", "State", "Testing", "Deployment"], ["React", "TypeScript", "Tailwind"], "Full-stack React app with auth + API")],
        },
        "jira_practice": {"daily": ["Track component stories", "Link PRs to tickets", "Update UI task board"], "weekly": ["Sprint review", "Demo", "Retrospective"]},
        "certifications": ["Meta Front-End Developer Certificate", "Google UX Design Certificate"],
    },
    "full_stack": {
        "name": "Full Stack Development",
        "icon": "code",
        "level_map": {
            "foundation": [
                topic("Web Foundations: HTML5", ["HTML document structure", "Semantic HTML", "Forms and validation", "Links and navigation", "Images and multimedia", "Tables and lists", "Accessibility basics", "SEO metadata"], ["VS Code", "Chrome DevTools"], "Build semantic portfolio and registration pages"),
                topic("CSS3 and Responsive UI", ["Selectors and specificity", "Box model", "Flexbox", "CSS Grid", "Responsive design", "Media queries", "Transitions and animations", "CSS variables"], ["CSS3", "Chrome DevTools"], "Create responsive landing page, navbar, cards, and dashboard layout"),
                topic("JavaScript ES6+ Foundations", ["Variables", "Data types", "Control flow", "Functions", "Arrays", "Objects", "DOM manipulation", "Events"], ["JavaScript", "Browser Console"], "Build calculator, form validation, and interactive UI components"),
                topic("Modern JavaScript and APIs", ["Template literals", "Destructuring", "Spread/rest", "Modules", "Promises", "async/await", "Fetch API", "JSON"], ["JavaScript", "Postman"], "Fetch public API data and render searchable/filterable results"),
                topic("Git, GitHub and Agile Workflow", ["Git init/clone/add/commit", "Branching", "Merging", "Pull requests", "Code review", "GitHub Flow", "Issues", "Project board"], ["Git", "GitHub", "Jira"], "Team PR exercise with merge conflict resolution and Jira story tracking"),
            ],
            "core": [
                topic("React Fundamentals", ["React project setup", "Vite", "JSX", "Components", "Props", "State", "Events", "Conditional rendering"], ["React", "Vite"], "Build reusable component library and interactive task manager"),
                topic("React Hooks and Forms", ["useState", "useEffect", "useRef", "useMemo", "Custom hooks", "Controlled forms", "Validation", "React Hook Form"], ["React", "React Hook Form"], "Build validated multi-step form with custom hooks"),
                topic("React Router and Frontend Architecture", ["BrowserRouter", "Routes", "Nested routes", "Route parameters", "Layouts", "Protected routes", "Folder structure", "Reusable services"], ["React Router", "Axios"], "Build multi-page frontend with protected dashboard routes"),
                topic("Frontend State and API Integration", ["Context API", "Redux Toolkit", "Async thunks", "RTK Query/Zustand", "Axios", "Loading states", "Error states", "Pagination"], ["Redux Toolkit", "Zustand", "Axios"], "Build API-backed dashboard with global state and filters"),
                topic("Node.js Fundamentals", ["Node architecture", "Event loop", "npm", "package.json", "Core modules", "fs/path/http", "CommonJS vs ES Modules", "Environment variables"], ["Node.js", "npm"], "Create Node scripts and basic HTTP server"),
                topic("Express.js REST API Development", ["Express setup", "Routing", "Controllers", "Middleware", "Request/response", "Status codes", "Validation", "Error handling"], ["Express.js", "Postman"], "Build CRUD REST API with validation and global error handling"),
                topic("Database Design and SQL", ["DBMS/RDBMS", "Tables", "Constraints", "SELECT/WHERE", "Joins", "Group By", "Indexes", "Transactions"], ["PostgreSQL", "MySQL"], "Design database schema and write CRUD/reporting queries"),
                topic("MongoDB and Mongoose", ["Documents", "Collections", "CRUD", "Mongoose schemas", "Validation", "Relationships", "Aggregation", "Indexes"], ["MongoDB", "Mongoose"], "Build MongoDB-backed product/user module"),
            ],
            "advanced": [
                topic("Authentication and Authorization", ["Password hashing", "JWT", "Sessions", "Refresh tokens", "RBAC", "Protected routes", "CORS", "Security headers"], ["JWT", "bcrypt", "Helmet"], "Implement login, role-based access, and protected frontend/backend routes"),
                topic("Full Stack Integration", ["Frontend-backend integration", "API service layer", "Form submission", "File uploads", "Search/filter/sort", "Error UX", "Optimistic updates", "API documentation"], ["React", "Express", "Postman"], "Connect React UI to Express APIs with complete CRUD workflow"),
                topic("Testing and Debugging", ["Browser DevTools", "Node debugging", "Unit testing", "React Testing Library", "API testing", "Supertest", "Mocking", "Coverage"], ["Vitest/Jest", "React Testing Library", "Supertest"], "Create frontend and backend test suite for critical flows"),
                topic("Performance and Optimization", ["React memoization", "Lazy loading", "Code splitting", "Debouncing", "Caching", "Pagination", "Database query optimization", "Bundle analysis"], ["React", "Vite", "DB tools"], "Optimize dashboard performance and API query latency"),
                topic("Deployment and DevOps Basics", ["Production build", "Environment variables", "Dockerfile", "Docker Compose", "Nginx basics", "CI/CD overview", "Cloud deployment", "Monitoring basics"], ["Docker", "GitHub Actions", "Vercel/Render/AWS"], "Dockerize full-stack app and deploy frontend/backend with CI/CD"),
                topic("Next.js Full Stack Patterns", ["App Router", "Layouts", "Server components", "Client components", "API routes", "Data fetching", "Authentication", "SEO metadata"], ["Next.js", "React"], "Build Next.js feature module with routing, API route, and SEO metadata"),
                topic("Real-Time and Advanced Backend", ["WebSockets", "Socket.IO", "Background jobs", "File uploads", "Email integration", "Rate limiting", "Logging", "API versioning"], ["Socket.IO", "Multer", "Winston"], "Add live notifications/file upload and production logging"),
            ],
            "projects": [
                topic("Mini Project: Task Management App", ["Requirements", "UI wireframe", "React components", "REST API", "Database schema", "Authentication", "Testing", "Demo"], ["React", "Express", "PostgreSQL/MongoDB"], "Build task manager with auth, CRUD, filters, and deployment checklist"),
                topic("Mini Project: E-Commerce Workflow", ["Product catalog", "Cart", "Checkout flow", "Orders", "Admin panel", "API integration", "Validation", "Reports"], ["React", "Node.js", "Database"], "Build e-commerce catalog, cart, order API, and admin dashboard"),
            ],
            "capstone": [
                topic("Full Stack Capstone Project", ["Requirement analysis", "Architecture design", "Database modeling", "React frontend", "Node/Express backend", "Authentication", "Testing", "Docker deployment", "Demo", "Code review"], ["React", "Node.js", "Express", "Database", "Docker", "GitHub Actions"], "Build and present production-style full-stack application with documentation"),
            ],
        },
        "jira_practice": {
            "daily": ["Create/update feature stories", "Link commits and PRs to tickets", "Move cards across sprint board", "Add build/demo links"],
            "weekly": ["Sprint planning", "Sprint review", "Code review checkpoint", "Retrospective"],
        },
        "certifications": ["Meta Front-End Developer Certificate", "MongoDB Developer Certification", "AWS Certified Developer Associate", "Microsoft Azure Developer Associate"],
    },
}

DOMAINS.update({
    "data_engineering": {
        "name": "Data Engineering",
        "icon": "data",
        "level_map": {
            "foundation": [
                topic("SQL Fundamentals", ["DDL/DML", "Joins", "Subqueries", "Views", "Indexes", "Window Functions"], ["PostgreSQL", "MySQL"], "Complex queries on e-commerce dataset"),
                topic("Python for Data", ["NumPy", "Pandas", "Data Cleaning", "CSV/JSON/Parquet", "Data Profiling"], ["Python", "Pandas", "Jupyter"], "ETL pipeline with Pandas"),
                topic("ETL Concepts", ["ETL vs ELT", "Transformations", "Data Quality", "Lineage", "Metadata"], ["Python", "PostgreSQL"], "Design and implement ETL for transactional DB"),
            ],
            "core": [
                topic("Data Warehousing", ["OLAP vs OLTP", "Star Schema", "Fact/Dimension", "SCD", "Partitioning"], ["Snowflake", "BigQuery", "Redshift"], "Design warehouse schema and load data"),
                topic("Apache Spark & PySpark", ["RDDs", "DataFrames", "Spark SQL", "Joins", "Optimization", "UDFs"], ["PySpark", "Databricks"], "Process large dataset with PySpark"),
                topic("Kafka Streaming", ["Topics", "Producers", "Consumers", "Partitions", "Kafka Connect"], ["Kafka", "Confluent"], "Real-time event streaming pipeline"),
                topic("Apache Airflow", ["DAGs", "Operators", "Sensors", "XCom", "Scheduling"], ["Airflow"], "Schedule daily ETL DAG with alerting"),
            ],
            "advanced": [
                topic("Cloud Data Platforms", ["AWS Glue", "Redshift", "S3 Data Lake", "Athena", "Databricks"], ["AWS", "Databricks"], "Cloud data pipeline on AWS"),
                topic("Lakehouse", ["Delta Lake", "Iceberg", "Bronze/Silver/Gold", "Governance"], ["Delta Lake", "Databricks"], "Build lakehouse with Delta Lake"),
                topic("dbt & Data Quality", ["Models", "Tests", "Docs", "Sources", "Snapshots", "Great Expectations"], ["dbt", "Great Expectations"], "Transform and test data models"),
            ],
            "capstone": [topic("Data Engineering Capstone", ["Ingestion", "Processing", "Storage", "Orchestration", "Monitoring"], ["All Data Tools"], "End-to-end data platform")],
        },
        "jira_practice": {"daily": ["Log pipeline tasks", "Update data story status", "Add test results"], "weekly": ["Pipeline demo", "Data quality review"]},
        "certifications": ["AWS Data Engineer Associate", "Databricks Data Engineer Associate", "Snowflake SnowPro Core"],
    },
    "machine_learning": {
        "name": "Machine Learning",
        "icon": "ml",
        "level_map": {
            "foundation": [
                topic("Math for ML", ["Linear Algebra", "Statistics", "Probability", "Matrix Operations"], ["NumPy", "SciPy"], "Matrix operations and statistical analysis"),
                topic("Python for ML", ["NumPy", "Pandas", "Matplotlib", "EDA", "Feature Engineering"], ["Jupyter", "Pandas"], "EDA on Titanic/Iris dataset"),
            ],
            "core": [
                topic("Supervised Learning", ["Regression", "Classification", "Trees", "Random Forest", "SVM", "XGBoost"], ["Scikit-learn"], "House price and churn prediction"),
                topic("Unsupervised Learning", ["K-Means", "DBSCAN", "PCA", "Anomaly Detection"], ["Scikit-learn"], "Customer segmentation"),
                topic("Model Evaluation", ["Cross Validation", "Confusion Matrix", "ROC/AUC", "RMSE", "GridSearchCV"], ["Scikit-learn", "MLflow"], "Compare and evaluate models"),
                topic("Feature Engineering", ["Encoding", "Scaling", "Imputation", "Pipelines"], ["Scikit-learn"], "Preprocessing pipeline"),
            ],
            "advanced": [
                topic("NLP", ["Text Preprocessing", "TF-IDF", "Embeddings", "BERT", "NER"], ["spaCy", "HuggingFace"], "Sentiment/news classifier"),
                topic("Deep Learning", ["Neural Networks", "CNNs", "RNNs", "Transfer Learning"], ["TensorFlow", "PyTorch"], "Image classification"),
                topic("MLOps", ["MLflow", "Model Registry", "FastAPI Serving", "Docker", "Monitoring"], ["MLflow", "FastAPI", "Docker"], "Deploy ML model API"),
            ],
            "capstone": [topic("ML Capstone Project", ["Problem Definition", "EDA", "Modeling", "Evaluation", "Deployment"], ["All ML Tools"], "End-to-end ML solution")],
        },
        "jira_practice": {"daily": ["Log experiment results", "Update model story"], "weekly": ["Model review", "Stakeholder demo"]},
        "certifications": ["Google Professional ML Engineer", "AWS ML Specialty", "TensorFlow Developer"],
    },
    "testing": {
        "name": "Testing & QA",
        "icon": "test",
        "level_map": {
            "foundation": [
                topic("Testing Fundamentals", ["SDLC", "STLC", "Test Cases", "Bug Life Cycle"], ["Jira", "TestRail"], "Write test cases for login module"),
                topic("Manual Testing", ["Functional", "Regression", "Smoke", "UAT", "BVA", "Equivalence"], ["Jira", "Zephyr"], "Manual test execution for e-commerce app"),
            ],
            "core": [
                topic("Selenium WebDriver", ["Locators", "Waits", "Forms", "Screenshots", "TestNG/JUnit"], ["Selenium", "Java/Python"], "Automate login and checkout flow"),
                topic("API Testing", ["REST", "Postman", "Assertions", "Newman", "Mock Servers"], ["Postman", "Newman"], "CRUD API test suite"),
                topic("Cypress / Playwright", ["Selectors", "Assertions", "Network Mocking", "CI"], ["Cypress", "Playwright"], "E2E suite for React app"),
            ],
            "advanced": [
                topic("Performance Testing", ["Load", "Stress", "JMeter", "Reports"], ["JMeter", "K6"], "Load test API with concurrent users"),
                topic("Automation Frameworks", ["POM", "Data-Driven", "Hybrid", "Allure", "CI"], ["Selenium", "Maven", "Allure"], "POM automation framework"),
                topic("Security Testing", ["SAST", "DAST", "OWASP ZAP", "Dependency Scanning"], ["SonarQube", "OWASP ZAP"], "Add scans to CI/CD pipeline"),
            ],
            "capstone": [topic("QA Capstone Project", ["Strategy", "Manual", "Automation", "API", "Performance", "CI"], ["All QA Tools"], "Complete test suite for full-stack app")],
        },
        "jira_practice": {"daily": ["Log defects", "Update test status", "Link defects"], "weekly": ["Defect triage", "Sprint sign-off"]},
        "certifications": ["ISTQB Foundation", "Selenium Certification", "Postman API Testing"],
    },
    "cybersecurity": {
        "name": "Cybersecurity",
        "icon": "security",
        "level_map": {
            "foundation": [
                topic("Networking Basics", ["OSI", "TCP/IP", "DNS", "Firewalls", "VPNs"], ["Wireshark", "nmap"], "Network traffic analysis"),
                topic("Linux Security", ["Users", "Permissions", "SSH Hardening", "Firewall", "Logging"], ["Ubuntu", "iptables"], "Harden Linux server"),
                topic("IAM & Access Control", ["RBAC", "MFA", "PAM", "AWS IAM", "Zero Trust"], ["AWS IAM", "Okta"], "Least privilege IAM policies"),
            ],
            "core": [
                topic("Vulnerability Assessment", ["CVE/CVSS", "Nessus", "OpenVAS", "Patch Management"], ["Nessus", "OpenVAS"], "Scan and generate VA report"),
                topic("Penetration Testing", ["Recon", "Scanning", "Exploitation", "Burp", "OWASP Top 10"], ["Kali", "Metasploit", "Burp"], "OWASP WebGoat exercises"),
                topic("SIEM & SOC", ["Log Management", "SIEM", "Alerts", "SOC Tiers", "Playbooks"], ["Splunk", "ELK", "Wazuh"], "Create detection rules"),
            ],
            "advanced": [
                topic("Cloud Security", ["Security Hub", "GuardDuty", "CloudTrail", "Config", "KMS"], ["AWS Security Hub"], "Configure AWS security posture"),
                topic("DevSecOps", ["SAST", "DAST", "Trivy", "Secret Scanning", "OPA"], ["Trivy", "Snyk", "SonarQube"], "Integrate scans in CI/CD"),
                topic("Incident Response", ["IR Lifecycle", "Threat Hunting", "Forensics", "Post-Incident Review"], ["Volatility", "Autopsy"], "Analyze compromised system"),
            ],
            "capstone": [topic("Security Capstone Project", ["Threat Modeling", "VA", "Pen Test", "SIEM", "Cloud Review"], ["All Security Tools"], "Full security assessment")],
        },
        "jira_practice": {"daily": ["Log findings", "Update vulnerability tickets"], "weekly": ["Security review", "Risk register update"]},
        "certifications": ["Security+", "CEH", "OSCP", "AWS Security Specialty", "CISSP"],
    },
    "power_bi": {
        "name": "Power BI",
        "icon": "bi",
        "level_map": {
            "foundation": [
                topic("Power BI Basics", ["Desktop", "Data Sources", "Import vs DirectQuery", "Visuals", "Filters"], ["Power BI Desktop"], "Build basic sales report"),
                topic("Power Query", ["M Basics", "Transformations", "Merge", "Append", "Custom Columns"], ["Power Query"], "Clean messy sales dataset"),
            ],
            "core": [
                topic("Data Modeling", ["Star Schema", "Relationships", "Cardinality", "Role-Playing Dimensions"], ["Power BI Model View"], "Retail star schema"),
                topic("DAX Fundamentals", ["Measures", "CALCULATE", "FILTER", "Time Intelligence", "RANKX"], ["DAX Studio"], "20 DAX measures"),
                topic("Reports & Dashboards", ["Design", "Bookmarks", "Drillthrough", "Tooltips", "Themes"], ["Power BI Desktop"], "Executive dashboard"),
            ],
            "advanced": [
                topic("Power BI Service", ["Workspaces", "Apps", "RLS", "Gateway", "Refresh", "Pipelines"], ["Power BI Service"], "Publish and secure report"),
                topic("Advanced Integration", ["Python/R", "Azure Synapse", "Paginated Reports", "REST API"], ["Azure", "Power Automate"], "Integrate with Azure warehouse"),
            ],
            "capstone": [topic("Power BI Capstone", ["Connect", "Transform", "Model", "DAX", "Dashboard", "RLS"], ["Power BI"], "End-to-end BI solution")],
        },
        "jira_practice": {"daily": ["Log report tasks", "Update dashboard stories"], "weekly": ["Stakeholder review", "Report sign-off"]},
        "certifications": ["Microsoft PL-300", "DP-900", "DP-500"],
    },
    "salesforce": {
        "name": "Salesforce",
        "icon": "cloud",
        "level_map": {
            "foundation": [
                topic("Salesforce Admin Basics", ["Org Setup", "Users", "Profiles", "Objects", "Fields", "Security"], ["Salesforce Trailhead"], "Configure CRM org"),
                topic("Data Management", ["Data Loader", "Relationships", "Formula Fields", "Validation Rules"], ["Data Loader", "Workbench"], "Import and validate records"),
            ],
            "core": [
                topic("Automation Tools", ["Flows", "Approval Processes", "Assignment Rules"], ["Flow Builder"], "Lead assignment flow"),
                topic("Reports & Dashboards", ["Report Types", "Filters", "Dashboards", "Subscriptions"], ["Salesforce Reports"], "Sales dashboard"),
                topic("Apex Development", ["Classes", "SOQL", "DML", "Triggers", "Governor Limits"], ["VS Code", "SFDX"], "Trigger and batch class"),
            ],
            "advanced": [
                topic("Lightning Web Components", ["Templates", "JS Controller", "Wire", "Events"], ["LWC", "Salesforce CLI"], "Account dashboard LWC"),
                topic("Integration", ["REST/SOAP", "Connected Apps", "OAuth", "Platform Events"], ["Postman", "MuleSoft"], "External REST API integration"),
            ],
            "capstone": [topic("Salesforce Capstone", ["Data Model", "Flows", "Apex", "LWC", "Integration"], ["Salesforce Stack"], "End-to-end CRM solution")],
        },
        "jira_practice": {"daily": ["Log org tasks", "Update user stories"], "weekly": ["Admin/dev demo", "Retrospective"]},
        "certifications": ["Salesforce Administrator", "Platform Developer I", "Platform App Builder"],
    },
    "java": {
        "name": "Java",
        "icon": "java",
        "level_map": {
            "foundation": [
                topic("Core Java Basics", ["Syntax", "Data Types", "Control Flow", "Arrays", "Methods"], ["JDK", "IntelliJ"], "Basic algorithms"),
                topic("OOP in Java", ["Classes", "Inheritance", "Polymorphism", "Interfaces"], ["Java"], "Banking system OOP"),
                topic("Collections & Generics", ["List", "Set", "Map", "Queue", "Comparator"], ["Java Collections"], "Student management system"),
            ],
            "core": [
                topic("Multithreading", ["Thread Lifecycle", "Executor", "CompletableFuture"], ["Java Concurrency"], "Transaction processor"),
                topic("JDBC & Databases", ["CRUD", "PreparedStatement", "Transactions"], ["JDBC", "MySQL"], "Student portal with JDBC"),
                topic("Spring Boot", ["REST Controllers", "Profiles", "Exception Handling"], ["Spring Boot", "Maven"], "Product API"),
                topic("Spring Data JPA", ["Entities", "Repositories", "Relationships", "Pagination"], ["Hibernate", "PostgreSQL"], "E-commerce backend"),
            ],
            "advanced": [
                topic("Spring Security & JWT", ["Auth", "JWT", "OAuth2", "RBAC"], ["Spring Security"], "Secure REST API"),
                topic("Microservices", ["Eureka", "Gateway", "Feign", "Resilience4j"], ["Spring Cloud"], "3-service system"),
                topic("Testing & DevOps", ["JUnit", "Mockito", "Docker", "CI/CD"], ["JUnit", "Docker"], "Test suite and pipeline"),
            ],
            "capstone": [topic("Java Capstone Project", ["Microservices", "Security", "Testing", "Docker"], ["Spring Boot", "Docker"], "Production-grade app")],
        },
        "jira_practice": {"daily": ["Log dev tasks", "Link commits"], "weekly": ["Code review", "Demo"]},
        "certifications": ["Oracle Java SE", "Spring Professional", "AWS Developer Associate"],
    },
    "project_management": {
        "name": "Project Management",
        "icon": "pm",
        "level_map": {
            "foundation": [
                topic("Agile & Scrum", ["Manifesto", "Roles", "Ceremonies", "Artifacts", "DoD"], ["Jira", "Confluence"], "Scrum team backlog"),
                topic("Jira Administration", ["Boards", "Workflows", "Fields", "Screens", "Permissions"], ["Jira"], "Configure Jira project"),
            ],
            "core": [
                topic("Backlog & Sprint Management", ["Epics", "Stories", "Tasks", "Story Points", "Planning"], ["Jira"], "2-week sprint simulation"),
                topic("Jira Reporting", ["Burndown", "Velocity", "CFD", "Dashboards"], ["Jira Reports"], "Team performance dashboard"),
                topic("Confluence Documentation", ["Spaces", "Templates", "Runbooks", "ADRs"], ["Confluence"], "Project wiki"),
            ],
            "advanced": [
                topic("Jira Automation", ["Rules", "Triggers", "Conditions", "Smart Values"], ["Jira Automation"], "Auto-transition tickets"),
                topic("Release & Roadmap", ["Versions", "Roadmaps", "Dependencies", "Risk Tracking"], ["Advanced Roadmaps"], "3-month roadmap"),
                topic("Kanban & Scaled Agile", ["WIP", "Flow Metrics", "SAFe", "PI Planning"], ["Jira", "Miro"], "Kanban board with CFD"),
            ],
            "capstone": [topic("PM Capstone", ["Charter", "Backlog", "Sprint", "Risk", "Reports"], ["Jira", "Confluence"], "Full project lifecycle")],
        },
        "jira_practice": {"daily": ["Daily standup", "Board updates", "Impediments"], "weekly": ["Sprint ceremonies", "Metrics review"]},
        "certifications": ["PMI-ACP", "PSM I", "SAFe Agilist", "Atlassian Jira Administrator"],
    },
    "agentic_ai": {
        "name": "Agentic AI",
        "icon": "agent",
        "level_map": {
            "foundation": [
                topic("Agentic AI Fundamentals", ["AI agents", "Agentic workflows", "LLM role in agents", "Reasoning loops", "Planning", "Actions", "Observations", "Human-in-the-loop"], ["Python", "LLM APIs"], "Design simple task-solving agent workflow"),
                topic("Prompting, Tool Calling and Structured Outputs", ["System prompts", "Role prompting", "Few-shot prompting", "Function calling", "Tool schemas", "Structured JSON outputs", "Validation", "Retry handling"], ["OpenAI/Gemini APIs", "JSON Schema"], "Build tool-calling assistant with validated output"),
                topic("RAG Foundations for Agents", ["Embeddings", "Chunking", "Vector databases", "Similarity search", "Hybrid search", "Reranking", "Context injection", "Grounded answers"], ["FAISS", "ChromaDB", "Pinecone"], "Build document question-answering RAG agent"),
            ],
            "core": [
                topic("LangChain Agents", ["Chains", "Tools", "Agents", "Agent executor", "Memory", "Retrievers", "Prompt templates", "Callbacks", "Error handling"], ["LangChain", "Python"], "Create LangChain research assistant"),
                topic("LlamaIndex Agents", ["Data connectors", "Indexes", "Query engines", "Tools", "Agent workflows", "RAG pipelines", "Document agents"], ["LlamaIndex", "Vector DB"], "Create document analysis agent"),
                topic("CrewAI Multi-Agent Collaboration", ["Agents", "Tasks", "Crews", "Roles", "Process flow", "Delegation", "Sequential workflows", "Collaborative outputs"], ["CrewAI"], "Build multi-agent research team"),
                topic("AutoGen Conversational Agents", ["Assistant agents", "User proxy agents", "Group chat", "Tool execution", "Code execution", "Conversation orchestration"], ["AutoGen", "Python"], "Build coding assistant with execution workflow"),
                topic("Agent Roles and Responsibilities", ["Orchestrator agent", "Router agent", "Tool-use agent", "Memory agent", "Critic/evaluator agent", "Guardrail/safety agent", "RAG retrieval agent", "SQL/data agent", "Browser research agent", "Code execution agent"], ["LangGraph", "LangChain", "Python"], "Design role-based multi-agent workflow"),
            ],
            "advanced": [
                topic("Advanced Agent Patterns", ["Planner-executor pattern", "Supervisor-worker pattern", "ReAct", "Reflexion", "Self-Ask", "Tree of Thoughts", "Debate pattern", "Swarm/collaborative agents", "Evaluator-optimizer loop", "Multi-agent RAG"], ["LangGraph", "CrewAI", "AutoGen"], "Implement supervisor-worker and evaluator loops"),
                topic("Production Agent Architecture", ["FastAPI backend", "PostgreSQL", "Redis memory", "Vector store", "Queue workers", "Background jobs", "Auth", "Rate limiting", "Cost tracking"], ["FastAPI", "PostgreSQL", "Redis"], "Build production-ready agent API"),
                topic("Browser, Code and Workflow Automation Agents", ["Browser automation", "Playwright tools", "Code execution tools", "File tools", "Email tools", "CRM tools", "WhatsApp automation", "Workflow orchestration"], ["Playwright", "FastAPI", "Celery"], "Create workflow automation agent"),
                topic("Agent Evaluation, Guardrails and Security", ["Task success metrics", "Hallucination checks", "Tool-call validation", "Guardrails", "Prompt injection defense", "Data leakage prevention", "Audit logs", "Responsible AI"], ["Ragas", "Guardrails", "OpenTelemetry"], "Evaluate and secure agent workflow"),
                topic("Deployment and Observability for Agents", ["Docker", "Kubernetes", "CI/CD", "Monitoring", "Tracing", "LLM latency", "Token usage", "Logs", "Alerts", "Feedback loops"], ["Docker", "Kubernetes", "Grafana"], "Deploy and monitor agent platform"),
            ],
            "capstone": [
                topic("Agentic AI Capstone Project", ["Problem statement", "Agent architecture", "RAG knowledge base", "Tool calling", "Multi-agent workflow", "Evaluation", "Guardrails", "Deployment", "Demo"], ["Python", "LangChain/LlamaIndex", "FastAPI", "Vector DB", "Docker"], "Build enterprise Agentic AI assistant"),
            ],
        },
        "jira_practice": {
            "daily": ["Create agent workflow story", "Update tool integration task", "Log evaluation results", "Track guardrail issues"],
            "weekly": ["Sprint review", "Agent demo", "Architecture review", "Retrospective"],
        },
        "certifications": ["Generative AI Engineer", "AI Engineer Associate", "Cloud AI Certification"],
    },
    "azure_ai_datasets": {
        "name": "Azure AI Datasets & GenAI Data Services",
        "icon": "azure",
        "level_map": {
            "foundation": [
                topic("Azure Machine Learning Datasets", ["Dataset creation", "Dataset registration", "Dataset versioning", "Tabular datasets", "File datasets", "Data labeling", "Dataset monitoring"], ["Azure Machine Learning"], "Create, register, version, and monitor Azure ML datasets"),
                topic("Azure Open Datasets", ["Weather data", "Transportation data", "Census data", "Earth observation data", "COVID-19 data", "Satellite data", "Public research datasets"], ["Azure Open Datasets"], "Explore and consume public Azure Open Datasets"),
                topic("Azure Blob Storage for AI Data", ["Uploading datasets", "Data organization", "Containers", "Access management", "SAS tokens", "Lifecycle management"], ["Azure Blob Storage"], "Upload and organize AI training documents and files"),
            ],
            "core": [
                topic("Azure Data Lake Storage Gen2", ["Structured data", "Semi-structured data", "Unstructured data", "Data ingestion", "Data governance", "Access control", "Hierarchical namespace"], ["Azure Data Lake Storage Gen2"], "Build governed data lake folder structure for AI projects"),
                topic("Azure SQL Database for AI/ML", ["Relational datasets", "Data import", "Querying data", "Data warehousing basics", "Feature tables", "SQL for analytics"], ["Azure SQL Database"], "Prepare relational dataset for ML and agent queries"),
                topic("Azure Data Factory Pipelines", ["Data pipelines", "ETL processes", "Data transformation", "Data migration", "Scheduling", "Monitoring pipeline runs"], ["Azure Data Factory"], "Create ETL pipeline from storage to analytics layer"),
                topic("Azure AI Data Labeling", ["Image labeling", "Text labeling", "Object detection labels", "Classification labels", "Quality review", "Label export"], ["Azure Machine Learning Data Labeling"], "Create labeling workflow for image/text dataset"),
            ],
            "advanced": [
                topic("Azure AI Search for RAG", ["Index creation", "Document ingestion", "Search datasets", "Vector search", "Hybrid search", "Semantic ranking", "Chunk metadata"], ["Azure AI Search", "Azure OpenAI"], "Build Azure AI Search vector index for RAG"),
                topic("Azure Databricks for AI Data Engineering", ["Data engineering", "Data preparation", "Feature engineering", "Large dataset processing", "Delta Lake", "Notebooks", "ML workflows"], ["Azure Databricks", "Delta Lake"], "Process and engineer features using Databricks"),
                topic("Azure Synapse Analytics", ["Data warehousing", "Big data analytics", "Data integration", "Reporting datasets", "SQL pools", "Spark pools"], ["Azure Synapse Analytics"], "Create analytics-ready dataset for BI and ML"),
                topic("Datasets for AI Agents and GenAI", ["Customer support data", "FAQ data", "Product catalog data", "Knowledge base documents", "PDF collections", "Company documents", "Policies and procedures", "Technical documentation"], ["Azure Blob Storage", "Azure AI Search"], "Prepare enterprise knowledge base for agentic RAG"),
                topic("Fine-Tuning, NLP and Computer Vision Datasets", ["Instruction datasets", "Conversation datasets", "Q&A datasets", "Domain-specific datasets", "Sentiment analysis", "NER", "OCR datasets", "Medical images"], ["Azure Machine Learning", "Azure OpenAI"], "Design dataset strategy for fine-tuning, NLP, and CV projects"),
            ],
            "capstone": [
                topic("Azure GenAI Dataset Capstone", ["Dataset ingestion", "Blob/Data Lake storage", "Data Factory pipeline", "AI Search vector index", "Azure OpenAI RAG", "Monitoring", "Security", "Demo"], ["Azure Blob Storage", "Azure Data Factory", "Azure AI Search", "Azure OpenAI"], "Build end-to-end Azure dataset pipeline for GenAI agent"),
            ],
        },
        "jira_practice": {
            "daily": ["Create dataset ingestion story", "Update data pipeline task", "Log data quality findings", "Track AI Search indexing progress"],
            "weekly": ["Dataset review", "RAG demo", "Pipeline review", "Retrospective"],
        },
        "certifications": ["Microsoft Azure AI Engineer Associate", "Azure Data Scientist Associate", "Azure Data Engineer Associate"],
    },
    "aws_ai_datasets": {
        "name": "AWS AI Datasets & GenAI Data Services",
        "icon": "aws",
        "level_map": {
            "foundation": [
                topic("Amazon S3 Dataset Storage", ["Buckets", "Objects", "Folder structure", "Versioning", "Lifecycle policies", "Upload datasets", "Download datasets", "Data organization", "Access control"], ["Amazon S3"], "Create S3 dataset bucket with versioning, folders, and access policies"),
                topic("AWS Open Data and Data Exchange", ["Climate data", "Satellite data", "Genomics data", "COVID-19 data", "Geospatial data", "Research datasets", "Open Data Registry", "Dataset discovery", "Third-party datasets"], ["AWS Open Data", "AWS Data Exchange"], "Discover and analyze public/third-party AWS datasets"),
                topic("Relational and NoSQL Datasets on AWS", ["Amazon RDS", "MySQL", "PostgreSQL", "SQL Server", "MariaDB", "Amazon DynamoDB", "JSON data", "Document datasets", "Key-value datasets"], ["Amazon RDS", "Amazon DynamoDB"], "Prepare relational and NoSQL datasets for AI/ML applications"),
            ],
            "core": [
                topic("Amazon SageMaker Datasets", ["Data import", "Data cleaning", "Data labeling", "Feature engineering", "Dataset versioning", "Data quality monitoring", "Data lineage"], ["Amazon SageMaker"], "Prepare, label, version, and monitor SageMaker datasets"),
                topic("AWS Glue Data Integration", ["ETL pipelines", "Data Catalog", "Crawlers", "Schema discovery", "Data cleaning", "Data enrichment", "Data validation"], ["AWS Glue"], "Build Glue crawler and ETL pipeline for AI dataset preparation"),
                topic("AWS Lake Formation Data Lakes", ["Data ingestion", "Data governance", "Data security", "Dataset cataloging", "Permissions", "Data lake structure"], ["AWS Lake Formation", "Amazon S3"], "Create governed AWS data lake for GenAI datasets"),
                topic("Athena and Redshift Analytics Datasets", ["SQL on S3", "Serverless analytics", "Dataset exploration", "Structured data", "Analytics datasets", "Data mart creation", "Reporting datasets"], ["Amazon Athena", "Amazon Redshift"], "Query S3 datasets with Athena and build reporting dataset in Redshift"),
            ],
            "advanced": [
                topic("Datasets for AI, ML and GenAI Projects", ["Customer support data", "FAQs", "Knowledge base articles", "Product descriptions", "Technical documentation", "PDFs", "Word documents", "Company policies", "Research papers", "Manuals", "Wikis"], ["Amazon S3", "AWS Glue"], "Prepare enterprise knowledge datasets for RAG and AI agents"),
                topic("Computer Vision, Audio and Time Series Datasets", ["Image classification", "Object detection", "OCR data", "Medical images", "Speech recognition", "Voice assistants", "Call center recordings", "Sales forecasting", "IoT sensor data", "Financial data"], ["SageMaker", "S3"], "Organize multimodal datasets for ML workloads"),
                topic("AWS Vector Search and RAG Services", ["Amazon OpenSearch Service", "Vector search", "Hybrid search", "Semantic search", "Amazon Bedrock embeddings", "Open-source embeddings", "RAG pipeline", "Retrieval layer"], ["Amazon OpenSearch Service", "Amazon Bedrock"], "Build OpenSearch vector index and RAG retrieval pipeline"),
                topic("AWS AI Agent Dataset Architecture", ["Data sources", "PDFs", "CSV files", "Databases", "APIs", "Websites", "Storage layer", "Processing layer", "Embedding layer", "Vector storage", "Agent layer", "Deployment layer"], ["S3", "Glue", "Bedrock", "OpenSearch", "LangChain", "LangGraph"], "Design full AWS AI agent dataset architecture"),
                topic("AWS Agent Deployment and Monitoring", ["SageMaker deployment", "ECS", "EKS", "Lambda", "CloudWatch monitoring", "Production AI agents", "Cost tracking", "Security review"], ["SageMaker", "ECS", "EKS", "Lambda", "CloudWatch"], "Deploy and monitor production-grade AWS AI agent"),
            ],
            "capstone": [
                topic("AWS GenAI Dataset Capstone", ["Dataset ingestion", "S3 data lake", "Glue catalog and ETL", "Bedrock embeddings", "OpenSearch vector engine", "RAG pipeline", "LangGraph agent", "ECS/EKS deployment", "CloudWatch monitoring"], ["S3", "Glue", "Bedrock", "OpenSearch", "LangGraph", "ECS/EKS"], "Build end-to-end AWS dataset pipeline for production AI agent"),
            ],
        },
        "jira_practice": {
            "daily": ["Create S3 dataset story", "Update Glue pipeline task", "Log data quality findings", "Track OpenSearch indexing progress"],
            "weekly": ["Dataset review", "RAG demo", "AWS pipeline review", "Retrospective"],
        },
        "certifications": ["AWS Certified AI Practitioner", "AWS Certified Machine Learning Engineer", "AWS Certified Data Engineer Associate", "AWS Certified Solutions Architect"],
    },
    "prompt_engineering": {
        "name": "Prompt Engineering",
        "icon": "prompt",
        "level_map": {
            "foundation": [
                topic("Prompt Engineering Fundamentals", ["What is prompt engineering", "Importance of prompt engineering", "How LLMs process prompts", "Prompt lifecycle", "Prompt design principles", "Tokens", "Context window", "Temperature", "Top-K", "Top-P", "Hallucinations"], ["LLM APIs"], "Design and test basic prompts across model settings"),
                topic("Prompt Structure and Templates", ["Role", "Task", "Context", "Constraints", "Output format", "Static prompts", "Dynamic prompts", "Reusable templates", "Modular prompts"], ["Prompt templates", "Markdown", "JSON"], "Create reusable prompt templates for business and technical tasks"),
                topic("Basic Prompting Techniques", ["Zero-shot prompting", "Use cases", "Best practices", "One-shot prompting", "Example-based learning", "Few-shot prompting", "Example selection", "Pattern learning", "Performance optimization"], ["LLM Playground"], "Compare zero-shot, one-shot, and few-shot prompts"),
            ],
            "core": [
                topic("Intermediate Prompting Techniques", ["Chain of Thought", "Step-by-step reasoning", "Structured thinking", "Self-consistency", "Multiple reasoning paths", "Generated knowledge prompting", "Role prompting", "Expert personas", "Domain-specific roles"], ["LLM APIs"], "Build reasoning prompts for complex problem solving"),
                topic("Advanced Prompting Techniques", ["ReAct", "Reasoning steps", "Action execution", "Tool usage", "Tree of Thoughts", "Graph of Thoughts", "Reflection prompting", "Self-correction", "Recursive prompting", "Iterative refinement"], ["LangChain", "LangGraph"], "Implement ReAct and reflection prompt workflows"),
                topic("Context Engineering", ["Context windows", "Context compression", "Context summarization", "Long context handling", "Chunking", "Context retrieval", "Memory management"], ["Vector DB", "LLM APIs"], "Design long-context prompt strategy with summarization and retrieval"),
                topic("Prompt Chaining and Workflows", ["Sequential prompting", "Multi-step workflows", "Pipeline design", "Task decomposition", "Workflow automation", "Multi-prompt systems", "Agent collaboration", "Decision pipelines"], ["LangChain", "LangGraph"], "Build prompt chain for end-to-end workflow automation"),
            ],
            "advanced": [
                topic("Structured Outputs and Schema Validation", ["JSON output", "XML output", "YAML output", "CSV output", "Markdown output", "Pydantic models", "Structured responses", "Output constraints", "Schema validation"], ["Pydantic", "JSON Schema"], "Create schema-validated structured output prompts"),
                topic("Prompt Engineering for RAG", ["Query construction", "Context injection", "Answer generation", "Query rewriting", "Multi-query retrieval", "Hybrid search prompts", "Grounded responses"], ["RAG", "Vector DB"], "Build RAG prompt template with query rewriting and citations"),
                topic("Prompt Engineering for AI Agents", ["Agent instructions", "Agent goals", "Agent constraints", "Function calling", "API calls", "Tool selection", "Agent communication", "Role assignment", "Collaboration prompts"], ["LangGraph", "CrewAI", "AutoGen"], "Design prompts for tool-calling and multi-agent systems"),
                topic("Domain-Specific Prompting", ["Content generation", "Blog writing", "Copywriting", "Coding prompts", "Code review", "Debugging", "SQL generation", "Data summarization", "Requirement gathering", "Documentation", "Email automation"], ["LLM APIs"], "Create domain prompt library for coding, data, and business use cases"),
                topic("Prompt Optimization and Security", ["Prompt refinement", "Token optimization", "Latency reduction", "Prompt compression", "Cost optimization", "Hallucination reduction", "Response validation", "Prompt injection", "Jailbreaks", "Input validation", "Output filtering"], ["Prompt eval tools", "Guardrails"], "Optimize and secure prompts against injection and hallucination"),
                topic("Prompt Evaluation and Enterprise Governance", ["Accuracy", "Relevance", "Consistency", "Completeness", "A/B testing", "Benchmarking", "Human evaluation", "Prompt repositories", "Version control", "Prompt analytics", "Cost tracking", "Quality monitoring"], ["Prompt registry", "Evaluation tools"], "Build prompt evaluation and versioning workflow"),
            ],
            "capstone": [
                topic("Prompt Engineering Capstone Project", ["Chatbot prompt design", "FAQ assistant", "Content generator", "SQL query generator", "Document summarizer", "Customer support assistant", "AI research agent", "Multi-agent system", "RAG knowledge assistant", "Autonomous workflow agent"], ["LLM APIs", "LangChain", "LangGraph", "Vector DB"], "Build production-ready prompt system with evaluation and security"),
            ],
        },
        "jira_practice": {
            "daily": ["Create prompt experiment story", "Update prompt test cases", "Log evaluation scores", "Track prompt security findings"],
            "weekly": ["Prompt review", "A/B testing review", "Quality demo", "Retrospective"],
        },
        "certifications": ["Generative AI Engineer", "Prompt Engineering Certification", "AI Engineer Associate"],
    },
})


ALIASES = {
    "devops": "devops",
    "dev_ops": "devops",
    "ci_cd": "devops",
    "cicd": "devops",
    "python": "python",
    "react": "react",
    "reactjs": "react",
    "react_js": "react",
    "frontend": "react",
    "front_end": "react",
    "full_stack": "full_stack",
    "fullstack": "full_stack",
    "full_stack_development": "full_stack",
    "full_stack_development_training": "full_stack",
    "fullstack_development": "full_stack",
    "full_stack_developer": "full_stack",
    "mern": "full_stack",
    "mern_stack": "full_stack",
    "mean": "full_stack",
    "mean_stack": "full_stack",
    "web_development": "full_stack",
    "web_dev": "full_stack",
    "data_engineering": "data_engineering",
    "de": "data_engineering",
    "machine_learning": "machine_learning",
    "ml": "machine_learning",
    "ai_ml": "machine_learning",
    "agentic_ai": "agentic_ai",
    "agentic": "agentic_ai",
    "ai_agents": "agentic_ai",
    "ai_agent": "agentic_ai",
    "agents": "agentic_ai",
    "azure_ai": "azure_ai_datasets",
    "azure_datasets": "azure_ai_datasets",
    "azure_genai": "azure_ai_datasets",
    "azure_ai_datasets": "azure_ai_datasets",
    "azure_openai_data": "azure_ai_datasets",
    "aws_ai": "aws_ai_datasets",
    "aws_datasets": "aws_ai_datasets",
    "aws_genai": "aws_ai_datasets",
    "aws_ai_datasets": "aws_ai_datasets",
    "aws_bedrock_data": "aws_ai_datasets",
    "prompt_engineering": "prompt_engineering",
    "prompt": "prompt_engineering",
    "prompts": "prompt_engineering",
    "prompting": "prompt_engineering",
    "testing": "testing",
    "qa": "testing",
    "cybersecurity": "cybersecurity",
    "cyber": "cybersecurity",
    "security": "cybersecurity",
    "power_bi": "power_bi",
    "powerbi": "power_bi",
    "salesforce": "salesforce",
    "sfdc": "salesforce",
    "java": "java",
    "project_management": "project_management",
    "pm": "project_management",
    "agile": "project_management",
    "jira": "project_management",
}


def _normalise_key(name: str) -> str:
    text = str(name or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _key_tokens(value: str) -> set:
    stopwords = {
        "and", "or", "plus", "with", "for", "training", "course", "program",
        "technology", "technologies", "basic", "basics", "advanced",
    }
    return {token for token in _normalise_key(value).split("_") if token and token not in stopwords}


def _best_fuzzy_domain_key(normalised: str):
    requested_tokens = _key_tokens(normalised)
    if not requested_tokens:
        return None
    best_key = None
    best_score = 0
    for key, domain in DOMAINS.items():
        candidates = {key, _normalise_key(domain.get("name"))}
        candidates.update(alias for alias, alias_key in ALIASES.items() if alias_key == key)
        for candidate in candidates:
            candidate_tokens = _key_tokens(candidate)
            if not candidate_tokens:
                continue
            phrase_match = candidate in normalised or normalised in candidate
            overlap = len(requested_tokens & candidate_tokens)
            if not phrase_match and overlap <= 0:
                continue
            score = overlap * 10
            if phrase_match:
                score += 25
            if candidate == key:
                score += 3
            if score > best_score:
                best_score = score
                best_key = key
    return best_key if best_score >= 10 else None


def _compact_key_alternatives(key: str) -> list:
    candidates = [key]
    for suffix in ("_datasets", "_data", "_genai", "_30"):
        if key.endswith(suffix):
            candidates.append(key[: -len(suffix)])
    if key.endswith("_qa"):
        candidates.append(key[: -len("_qa")])
    return candidates


def get_domain(name: str):
    _load_compact_domains()
    normalised = _normalise_key(name)
    key = ALIASES.get(normalised, normalised)
    for candidate in _compact_key_alternatives(key):
        if candidate in COMPACT_DOMAINS:
            return _compact_domain_to_standard(COMPACT_DOMAINS[candidate])
    if key not in DOMAINS:
        if "full_stack" in normalised or "fullstack" in normalised or "mern" in normalised or "mean_stack" in normalised:
            key = "full_stack"
        elif "prompt" in normalised:
            key = "prompt_engineering"
        elif "agentic" in normalised or "ai_agent" in normalised or "langchain" in normalised or "langgraph" in normalised:
            key = "agentic_ai"
        elif "azure" in normalised and ("data" in normalised or "dataset" in normalised or "genai" in normalised):
            key = "azure_ai_datasets"
        elif "aws" in normalised and ("data" in normalised or "dataset" in normalised or "genai" in normalised or "bedrock" in normalised):
            key = "aws_ai_datasets"
        else:
            key = _best_fuzzy_domain_key(normalised) or key
    for candidate in _compact_key_alternatives(key):
        if candidate in COMPACT_DOMAINS:
            return _compact_domain_to_standard(COMPACT_DOMAINS[candidate])
    return DOMAINS.get(key)


def list_domains():
    _load_compact_domains()
    domains = []
    seen = set()
    for key, value in COMPACT_DOMAINS.items():
        root_key = re.sub(r"_[0-9]+$", "", key)
        if root_key in seen:
            continue
        seen.add(root_key)
        domains.append({"key": root_key, "name": value.get("name") or root_key, "icon": value.get("icon", "book")})
    for key, value in DOMAINS.items():
        if key in seen:
            continue
        seen.add(key)
        domains.append({"key": key, "name": value.get("name"), "icon": value.get("icon")})
    return domains
