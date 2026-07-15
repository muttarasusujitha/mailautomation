#!/usr/bin/env python
"""Generate 30-day compact datasets for all remaining domains."""

import json
import os

DATASETS_DIR = "datasets_compact"

# Domain configurations with their day-wise progression
REMAINING_DOMAINS = {
    "data_engineering": {
        "domain": "Data Engineering",
        "name": "Data Engineering",
        "icon": "database",
        "certifications": [
            "AWS Certified Data Analytics - Specialty",
            "Google Cloud Professional Data Engineer",
            "Databricks Certified Data Engineer",
            "Kafka Developer Certification",
            "Apache Spark Developer"
        ],
        "days_progression": [
            ("SQL & Databases", ["Database Design", "SQL Basics", "Indexing", "Query Optimization", "Transactions"], ["PostgreSQL", "MySQL"], "Build complex queries"),
            ("Data Warehousing", ["Schema Design", "ETL", "Fact/Dimension Tables", "Slowly Changing Dimensions"], ["Redshift", "BigQuery"], "Design data warehouse"),
            ("ETL Fundamentals", ["Extract", "Transform", "Load", "Validation", "Error Handling"], ["Apache Airflow", "Talend"], "Build ETL pipeline"),
            ("Python for Data", ["NumPy", "Pandas", "Polars", "Data Cleaning", "Processing"], ["Python", "Jupyter"], "Data processing with pandas"),
            ("Apache Spark", ["RDD", "DataFrames", "SQL", "Streaming", "Optimization"], ["Apache Spark"], "Distributed data processing"),
            ("Kafka & Streaming", ["Topics", "Producers", "Consumers", "Streams", "Real-time"], ["Kafka", "Spark Streaming"], "Build streaming pipeline"),
            ("Data Lakes", ["Architecture", "Delta Lake", "Partition", "Versioning", "Optimization"], ["S3", "Delta Lake"], "Design data lake"),
            ("Cloud Platforms - AWS", ["S3", "Glue", "EMR", "Lambda", "Data Pipeline"], ["AWS"], "AWS data engineering"),
            ("Cloud Platforms - GCP", ["BigQuery", "Dataflow", "Pub/Sub", "Cloud Storage"], ["GCP"], "GCP data engineering"),
            ("Orchestration", ["Airflow DAGs", "Scheduling", "Monitoring", "Error Recovery"], ["Apache Airflow"], "Production orchestration"),
            ("Data Quality", ["Validation", "Testing", "Monitoring", "Profiling", "Alerting"], ["Great Expectations"], "Implement data quality"),
            ("Advanced Spark", ["Tuning", "Partitioning", "Caching", "Optimization"], ["Spark"], "Performance optimization"),
            ("Iceberg & Delta", ["Table Format", "ACID Compliance", "Time Travel", "Schema Evolution"], ["Apache Iceberg"], "Modern table formats"),
            ("dbt (Data Build Tool)", ["Models", "Tests", "Documentation", "Deployment"], ["dbt"], "dbt workflow"),
            ("Monitoring & Logging", ["Pipeline Monitoring", "Error Tracking", "Logging", "Alerting"], ["ELK", "Prometheus"], "Production monitoring"),
        ],
    },
    "machine_learning": {
        "domain": "Machine Learning",
        "name": "Machine Learning",
        "icon": "brain",
        "certifications": [
            "AWS Certified Machine Learning - Specialty",
            "Google Cloud Professional Machine Learning",
            "TensorFlow Developer Certificate",
            "Microsoft Certified: Azure Data Scientist Associate"
        ],
        "days_progression": [
            ("ML Fundamentals", ["Supervised Learning", "Unsupervised Learning", "Reinforcement Learning", "Model Types"], ["Scikit-learn"], "ML basics"),
            ("Data Preprocessing", ["Cleaning", "Normalization", "Feature Scaling", "Handling Missing Values"], ["Pandas", "NumPy"], "Data preparation"),
            ("Feature Engineering", ["Feature Selection", "Feature Creation", "Encoding", "Scaling"], ["Scikit-learn"], "Build features"),
            ("Linear Regression", ["Simple/Multiple Regression", "Regularization", "Evaluation"], ["Scikit-learn"], "Regression models"),
            ("Logistic Regression", ["Classification", "Decision Boundary", "Probability"], ["Scikit-learn"], "Binary classification"),
            ("Decision Trees & Ensemble", ["Decision Trees", "Random Forest", "Gradient Boosting"], ["XGBoost", "LightGBM"], "Ensemble methods"),
            ("SVM & KNN", ["Support Vector Machines", "K-Nearest Neighbors", "Kernel Tricks"], ["Scikit-learn"], "SVM and KNN"),
            ("Clustering", ["K-Means", "Hierarchical", "DBSCAN", "Evaluation"], ["Scikit-learn"], "Unsupervised learning"),
            ("Dimensionality Reduction", ["PCA", "t-SNE", "UMAP", "Feature Selection"], ["Scikit-learn"], "Dimensionality reduction"),
            ("Neural Networks", ["Perceptrons", "Backpropagation", "Activation Functions", "Layers"], ["TensorFlow", "Keras"], "Build neural networks"),
            ("CNN for Images", ["Convolutional Layers", "Pooling", "Architecture"], ["TensorFlow", "PyTorch"], "Image classification"),
            ("RNN & NLP", ["RNN", "LSTM", "Transformers", "Text Processing"], ["TensorFlow", "NLTK"], "Natural language processing"),
            ("Hyperparameter Tuning", ["Grid Search", "Random Search", "Bayesian Optimization"], ["Optuna", "Ray"], "Model optimization"),
            ("Model Evaluation & Metrics", ["Precision", "Recall", "F1", "ROC-AUC", "Cross-validation"], ["Scikit-learn"], "Model evaluation"),
            ("Deployment & MLOps", ["Model Serving", "Containers", "Monitoring", "Retraining"], ["MLflow", "Docker"], "Production models"),
        ],
    },
    "qa_automation": {
        "domain": "Testing & QA",
        "name": "Testing & QA",
        "icon": "checkmark",
        "certifications": [
            "ISTQB Certified Tester",
            "AWS Certified DevOps Engineer",
            "Certified Selenium WebDriver Engineer",
            "API Testing Certification"
        ],
        "days_progression": [
            ("QA Fundamentals", ["Testing Types", "Test Plan", "Test Cases", "Defect Management"], ["TestRail", "Jira"], "QA basics"),
            ("Manual Testing", ["Test Design", "Test Execution", "Bug Reporting", "Regression Testing"], ["TestLink"], "Manual test execution"),
            ("Web Testing", ["Web Elements", "Locators", "Navigation", "Form Testing"], ["Selenium"], "Web app testing"),
            ("Selenium Basics", ["WebDriver", "Locators", "Actions", "Waits"], ["Selenium"], "Selenium fundamentals"),
            ("Selenium Advanced", ["Page Object Model", "Data-Driven Testing", "Framework"], ["Selenium"], "Advanced Selenium"),
            ("API Testing with Postman", ["REST API", "Request/Response", "Assertions", "Collections"], ["Postman"], "API testing"),
            ("API Testing with RestAssured", ["Java REST Client", "BDD", "Assertions"], ["RestAssured", "Cucumber"], "API automation"),
            ("Performance Testing", ["Load Testing", "Stress Testing", "JMeter"], ["JMeter", "Gatling"], "Performance testing"),
            ("Mobile Testing", ["AppiumBasics", "iOS/Android", "Native/Hybrid"], ["Appium"], "Mobile automation"),
            ("CI/CD Integration", ["Jenkins", "GitLab CI", "GitHub Actions"], ["GitHub Actions"], "Testing in CI/CD"),
            ("BDD & Cucumber", ["Gherkin", "Feature Files", "Step Definitions"], ["Cucumber", "Selenium"], "Behavior-driven testing"),
            ("Test Frameworks", ["TestNG", "Junit", "Fixture Management"], ["TestNG"], "Java test frameworks"),
            ("Debugging & Logging", ["Logs Analysis", "Screenshots", "Video Capture"], ["Log4j", "SLF4J"], "Debugging failures"),
            ("Database Testing", ["SQL Queries", "Data Validation", "JDBC"], ["SQL", "JDBC"], "Database test automation"),
            ("Advanced Topics", ["Test Optimization", "Parallel Execution", "Reporting"], ["ExtentReports"], "Advanced testing"),
        ],
    },
    "cybersecurity": {
        "domain": "Cybersecurity",
        "name": "Cybersecurity",
        "icon": "shield",
        "certifications": [
            "CEH - Certified Ethical Hacker",
            "AWS Certified Security - Specialty",
            "CompTIA Security+",
            "CISSP - Certified Information Systems Security Professional"
        ],
        "days_progression": [
            ("Security Fundamentals", ["CIA Triad", "Threats", "Vulnerabilities", "Risk Management"], ["OWASP"], "Security basics"),
            ("Network Security", ["Firewalls", "VPN", "Intrusion Detection", "Network Analysis"], ["Wireshark"], "Network security"),
            ("Cryptography", ["Symmetric Encryption", "Asymmetric Encryption", "Hashing"], ["OpenSSL"], "Cryptographic concepts"),
            ("Access Control", ["Authentication", "Authorization", "RBAC", "Privilege Management"], ["LDAP"], "Access control"),
            ("Web Application Security", ["OWASP Top 10", "SQL Injection", "XSS", "CSRF"], ["Burp Suite"], "Web app security"),
            ("Vulnerability Assessment", ["Scanning", "Reporting", "Remediation", "Validation"], ["Nessus", "OpenVAS"], "Vulnerability scanning"),
            ("Penetration Testing", ["Reconnaissance", "Exploitation", "Post-Exploitation"], ["Metasploit"], "Penetration testing"),
            ("Malware Analysis", ["Static Analysis", "Dynamic Analysis", "Behavior"], ["IDA Pro"], "Malware analysis"),
            ("Incident Response", ["Detection", "Analysis", "Containment", "Recovery"], ["SIEM"], "Incident response"),
            ("Forensics", ["Evidence Collection", "Analysis", "Chain of Custody"], ["EnCase"], "Digital forensics"),
            ("Cloud Security", ["AWS Security", "Azure Security", "IAM"], ["AWS"], "Cloud security"),
            ("Container Security", ["Docker Security", "Kubernetes Security"], ["Trivy", "Falco"], "Container security"),
            ("DevSecOps", ["Security in CI/CD", "SAST/DAST", "Dependency Scanning"], ["SonarQube"], "DevSecOps practices"),
            ("Compliance & Standards", ["ISO 27001", "SOC2", "GDPR", "HIPAA"], ["Compliance"], "Security standards"),
            ("Advanced Topics", ["Zero Trust", "Threat Hunting", "Security Architecture"], ["Advanced"], "Advanced security"),
        ],
    },
    "salesforce": {
        "domain": "Salesforce",
        "name": "Salesforce",
        "icon": "cloud",
        "certifications": [
            "Salesforce Certified Associate",
            "Salesforce Certified Administrator",
            "Salesforce Certified Developer",
            "Salesforce Certified Platform App Builder"
        ],
        "days_progression": [
            ("Salesforce Fundamentals", ["Platform Overview", "Orgs", "Setup", "Navigation"], ["Salesforce"], "Salesforce basics"),
            ("Core Objects & Records", ["Accounts", "Contacts", "Opportunities", "Leads"], ["Salesforce"], "Core objects"),
            ("Customization Basics", ["Custom Fields", "Record Types", "Page Layouts"], ["Salesforce"], "Basic customization"),
            ("Automation - Workflow", ["Workflow Rules", "Actions", "Time-Dependent"], ["Salesforce"], "Workflow automation"),
            ("Automation - Process Builder", ["Process Builder", "Actions", "Logic"], ["Salesforce"], "Process builder"),
            ("Automation - Flow Builder", ["Flows", "Screens", "Actions", "Complex Logic"], ["Salesforce"], "Flow automation"),
            ("Data Management", ["Data Import", "Export", "Duplicate Management"], ["Data Loader"], "Data management"),
            ("Reports & Dashboards", ["Report Types", "Formulas", "Dashboards"], ["Salesforce"], "Reports and dashboards"),
            ("Apex Basics", ["Classes", "Methods", "Variables", "Syntax"], ["Apex"], "Apex programming"),
            ("Apex Advanced", ["Triggers", "Collections", "Exception Handling"], ["Apex"], "Advanced Apex"),
            ("Visualforce Pages", ["VF Syntax", "Components", "Controller"], ["Visualforce"], "Visualforce development"),
            ("Lightning Components", ["LWC", "Components", "Data Binding", "Events"], ["Lightning"], "Lightning development"),
            ("Integration", ["REST API", "SOAP", "Webhooks"], ["Salesforce API"], "Integration basics"),
            ("Data Security", ["Profiles", "Permission Sets", "Sharing Rules"], ["Salesforce"], "Security and access"),
            ("Deployment & Testing", ["Change Sets", "Sandboxes", "Testing", "Metadata"], ["Salesforce"], "Deployment & testing"),
        ],
    },
    "power_bi": {
        "domain": "Power BI",
        "name": "Power BI",
        "icon": "chart",
        "certifications": [
            "Microsoft Certified: Data Analyst Associate",
            "Microsoft Certified: Power BI Data Analyst",
            "Databricks Certified Associate Data Analyst"
        ],
        "days_progression": [
            ("Power BI Fundamentals", ["Workspace", "Apps", "Navigation", "Licensing"], ["Power BI"], "Power BI basics"),
            ("Data Sources & Connections", ["Excel", "SQL", "APIs", "Data Gateway"], ["Power Query"], "Data connections"),
            ("Data Modeling", ["Tables", "Relationships", "Cardinality", "Star Schema"], ["Power BI"], "Data modeling"),
            ("Power Query", ["Queries", "Transformations", "M Language", "Merge/Append"], ["Power Query"], "Power Query editor"),
            ("DAX Fundamentals", ["Syntax", "Functions", "Context"], ["DAX"], "DAX basics"),
            ("DAX Advanced", ["CALCULATE", "FILTER", "SUMX", "Complex Formulas"], ["DAX"], "Advanced DAX"),
            ("Visualizations", ["Charts", "Tables", "Maps", "Custom Visuals"], ["Power BI"], "Creating visualizations"),
            ("Dashboards", ["Dashboard Design", "Interactivity", "Filters", "Sync"], ["Power BI"], "Dashboard creation"),
            ("Reports", ["Report Pages", "Drillthrough", "Bookmarks", "Themes"], ["Power BI"], "Report development"),
            ("Performance Optimization", ["Query Optimization", "Compression", "Aggregations"], ["Power BI"], "Performance tuning"),
            ("Row-Level Security", ["RLS", "Dynamic Security", "Configuration"], ["Power BI"], "Security implementation"),
            ("Advanced Analytics", ["R/Python Visuals", "ML Models", "Forecasting"], ["Power BI"], "Advanced analytics"),
            ("Sharing & Collaboration", ["Sharing Reports", "Apps", "Workspaces"], ["Power BI"], "Sharing and collaboration"),
            ("Deployment", ["Premium Capacity", "Refresh Schedules", "Monitoring"], ["Power BI"], "Deployment strategies"),
            ("Real-World Projects", ["End-to-end Analysis", "Best Practices", "Optimization"], ["Power BI"], "Real-world projects"),
        ],
    },
    "agentic_ai": {
        "domain": "Agentic AI",
        "name": "Agentic AI",
        "icon": "robot",
        "certifications": [
            "AWS Certified ML Specialty",
            "Google Cloud AI Engineer",
            "Azure AI Engineer Associate",
            "LangChain Developer Certification"
        ],
        "days_progression": [
            ("AI Fundamentals", ["AI/ML/DL", "Agents", "Large Language Models"], ["Python"], "AI concepts"),
            ("LLM Basics", ["Transformers", "Tokenization", "Embeddings", "Fine-tuning"], ["HuggingFace"], "Large language models"),
            ("Prompt Engineering", ["Techniques", "Few-shot", "Chain of Thought", "Prompt Optimization"], ["GPT-4", "Claude"], "Prompt design"),
            ("LangChain Fundamentals", ["Chains", "Agents", "Tools", "Memory"], ["LangChain"], "LangChain basics"),
            ("Building Simple Agents", ["ReAct", "Agent Design", "Tool Integration"], ["LangChain"], "Simple agent architecture"),
            ("Complex Agent Workflows", ["Multi-step Reasoning", "Tool Chaining", "Error Recovery"], ["LangChain"], "Advanced agent patterns"),
            ("RAG - Retrieval Augmented Generation", ["Vector Databases", "Embeddings", "Retrieval"], ["Pinecone", "Chroma"], "RAG systems"),
            ("Vector Databases", ["Storage", "Similarity Search", "Indexing", "Scaling"], ["Pinecone", "Weaviate"], "Vector storage"),
            ("OpenAI API", ["API Usage", "Models", "Streaming", "Cost Optimization"], ["OpenAI API"], "OpenAI integration"),
            ("Other LLM Providers", ["Anthropic", "Google", "Cohere", "Open Source Models"], ["Anthropic", "LLama"], "Multiple LLM providers"),
            ("Agent Evaluation & Testing", ["Metrics", "Benchmarks", "Failure Modes"], ["Pytest"], "Agent evaluation"),
            ("Production Deployment", ["Scalability", "Monitoring", "Cost Management"], ["AWS", "Azure"], "Agent deployment"),
            ("Memory Management", ["Conversation History", "State Management", "Summarization"], ["LangChain"], "Agent memory"),
            ("Tool Integration & APIs", ["Custom Tools", "API Integration", "Error Handling"], ["FastAPI"], "Tool development"),
            ("Advanced Agentic Patterns", ["Multi-agent Systems", "Emergent Behavior", "Autonomous Agents"], ["Agentic"], "Advanced patterns"),
        ],
    },
    "azure_ai": {
        "domain": "Azure AI",
        "name": "Azure AI Datasets",
        "icon": "azure",
        "certifications": [
            "Azure AI Engineer Associate",
            "Azure Data Scientist Associate",
            "Azure Solutions Architect Expert",
            "Microsoft Certified: Azure AI Fundamentals"
        ],
        "days_progression": [
            ("Azure Fundamentals", ["Subscriptions", "Resource Groups", "Portal", "CLI"], ["Azure"], "Azure basics"),
            ("Azure AI Services Overview", ["Cognitive Services", "OpenAI Service", "Bot Service"], ["Azure"], "Azure AI overview"),
            ("Azure Cognitive Services", ["Vision", "Speech", "Language", "Search"], ["Azure Cognitive Services"], "Cognitive services"),
            ("Azure OpenAI Service", ["Models", "Deployments", "API", "Playground"], ["Azure OpenAI"], "Azure OpenAI setup"),
            ("Building Chat Applications", ["ChatGPT Integration", "Prompt Engineering", "Conversation Flow"], ["Azure OpenAI"], "Chat applications"),
            ("Azure Machine Learning", ["Workspace", "Compute", "Datasets", "Experiments"], ["Azure ML"], "Azure ML workspace"),
            ("Azure ML - Model Training", ["AutoML", "Designer", "Pipelines", "Training"], ["Azure ML"], "Model training"),
            ("Azure ML - Deployment", ["Endpoints", "Inference", "Container", "Batch"], ["Azure ML"], "Model deployment"),
            ("Azure Databricks", ["Clusters", "Notebooks", "Spark Jobs"], ["Databricks"], "Databricks on Azure"),
            ("Data Processing", ["Data Factory", "Data Lake Storage", "Synapse Analytics"], ["Azure Data Services"], "Data processing"),
            ("Search & Retrieval", ["Azure Cognitive Search", "Vector Search", "Indexing"], ["Cognitive Search"], "Azure search services"),
            ("Computer Vision", ["Image Analysis", "OCR", "Face Recognition"], ["Azure Vision"], "Vision AI"),
            ("Natural Language Processing", ["Text Analysis", "Sentiment", "Entity Recognition"], ["Azure Language"], "Language AI"),
            ("Responsible AI", ["Fairness", "Transparency", "Accountability"], ["Responsible AI"], "Responsible AI practices"),
            ("Production & Governance", ["MLOps", "Monitoring", "Cost Management"], ["Azure"], "Production deployment"),
        ],
    },
    "aws_ai": {
        "domain": "AWS AI",
        "name": "AWS AI Datasets",
        "icon": "aws",
        "certifications": [
            "AWS Certified Machine Learning - Specialty",
            "AWS Certified AI Practitioner",
            "AWS Solutions Architect - Professional",
            "AWS Certified Data Analytics - Specialty"
        ],
        "days_progression": [
            ("AWS Fundamentals", ["Services", "Regions", "IAM", "Console"], ["AWS"], "AWS basics"),
            ("AWS AI Services Overview", ["SageMaker", "Lex", "Polly", "Rekognition"], ["AWS"], "AWS AI overview"),
            ("Amazon SageMaker Basics", ["Notebooks", "Datasets", "Instances"], ["SageMaker"], "SageMaker setup"),
            ("SageMaker Model Development", ["Training", "Hyperparameter Tuning", "Evaluation"], ["SageMaker"], "Model development"),
            ("SageMaker Deployment", ["Endpoints", "Batch Transform", "Auto Scaling"], ["SageMaker"], "Model deployment"),
            ("Amazon Rekognition", ["Image Analysis", "Video Analysis", "Face Detection"], ["Rekognition"], "Computer vision"),
            ("Amazon Textract", ["Document Analysis", "OCR", "Form Recognition"], ["Textract"], "Document processing"),
            ("Amazon Lex", ["Chatbots", "Intents", "Slots", "Integration"], ["Lex"], "Chatbot building"),
            ("Amazon Polly", ["Text-to-Speech", "Neural Voices", "SSML"], ["Polly"], "Text-to-speech"),
            ("Amazon Comprehend", ["NLP", "Sentiment", "Entities", "Key Phrases"], ["Comprehend"], "NLP services"),
            ("Amazon Forecast", ["Time Series", "Predictions", "Accuracy Metrics"], ["Forecast"], "Forecasting"),
            ("Amazon Lookout", ["Anomaly Detection", "Equipment Monitoring"], ["Lookout"], "Anomaly detection"),
            ("Data Preparation", ["Data Pipeline", "ETL", "Feature Engineering"], ["Data Wrangler"], "Data preparation"),
            ("MLOps on AWS", ["CI/CD", "Monitoring", "Automation"], ["AWS MLOps"], "MLOps practices"),
            ("Production Deployment", ["Scalability", "Cost Optimization", "Monitoring"], ["AWS"], "Production workflows"),
        ],
    },
    "prompt_engineering": {
        "domain": "Prompt Engineering",
        "name": "Prompt Engineering",
        "icon": "pencil",
        "certifications": [
            "Prompt Engineering Fundamentals",
            "DeepLearning.AI Prompt Engineering",
            "Anthropic Prompt Engineer Certification"
        ],
        "days_progression": [
            ("Fundamentals of Prompting", ["Language Models", "Tokens", "Probability", "Basic Prompts"], ["GPT-4"], "Prompt basics"),
            ("Prompt Techniques", ["Zero-shot", "Few-shot", "Chain of Thought"], ["ChatGPT"], "Prompting techniques"),
            ("Writing Effective Prompts", ["Clarity", "Specificity", "Context", "Instructions"], ["Claude"], "Effective prompts"),
            ("Chain of Thought Prompting", ["Step-by-step", "Reasoning", "Complex Problems"], ["GPT-4"], "CoT reasoning"),
            ("Role-Based Prompting", ["Personas", "Expert Roles", "Character Consistency"], ["LLMs"], "Persona prompting"),
            ("Temperature & Parameters", ["Sampling", "Top-k", "Top-p", "Frequency Penalty"], ["API Parameters"], "Parameter tuning"),
            ("Function Calling", ["Tool Use", "Structured Output", "API Integration"], ["Function Calling"], "Tool integration"),
            ("Working with Structured Data", ["JSON", "Parsing", "Validation", "Schema"], ["Structured Output"], "Structured prompts"),
            ("Retrieval-Augmented Generation", ["Context Injection", "Document Retrieval", "Dynamic Context"], ["RAG"], "RAG prompting"),
            ("Multi-turn Conversations", ["Context Management", "Memory", "Continuity"], ["Conversation"], "Conversation design"),
            ("Prompt Optimization", ["Iterative Refinement", "Testing", "Evaluation"], ["Prompt Testing"], "Optimization techniques"),
            ("Error Handling & Robustness", ["Fallbacks", "Validation", "Recovery"], ["Error Handling"], "Robust prompts"),
            ("Cost Optimization", ["Token Counting", "Model Selection", "Efficiency"], ["Cost Analysis"], "Cost optimization"),
            ("Creative Prompting", ["Storytelling", "Code Generation", "Content Creation"], ["Creative Uses"], "Creative applications"),
            ("Advanced Patterns", ["Agent Prompts", "Self-improving Prompts", "Meta-prompting"], ["Advanced"], "Advanced prompting"),
        ],
    },
    "cloud_platform": {
        "domain": "Cloud",
        "name": "Cloud",
        "icon": "cloud",
        "certifications": [
            "AWS Solutions Architect - Associate",
            "Google Cloud Associate Cloud Engineer",
            "Azure Fundamentals",
            "Cloud Security Knowledge"
        ],
        "days_progression": [
            ("Cloud Fundamentals", ["IaaS/PaaS/SaaS", "Deployment Models", "Benefits", "Risks"], ["Cloud"], "Cloud basics"),
            ("AWS Fundamentals", ["Services", "EC2", "S3", "VPC"], ["AWS"], "AWS core services"),
            ("AWS Advanced", ["Auto Scaling", "Load Balancers", "RDS", "Lambda"], ["AWS"], "AWS advanced services"),
            ("Google Cloud Fundamentals", ["Compute", "Storage", "Networking"], ["GCP"], "GCP services"),
            ("Google Cloud Advanced", ["BigQuery", "Dataflow", "Cloud Run"], ["GCP"], "GCP advanced services"),
            ("Azure Fundamentals", ["Virtual Machines", "Storage", "Networking"], ["Azure"], "Azure services"),
            ("Azure Advanced", ["App Service", "Functions", "Containers"], ["Azure"], "Azure advanced services"),
            ("Networking in Cloud", ["VPC/Virtual Networks", "Subnets", "Routing", "Security Groups"], ["Cloud"], "Cloud networking"),
            ("Storage Solutions", ["Object Storage", "Block Storage", "File Storage"], ["Cloud Storage"], "Storage options"),
            ("Databases in Cloud", ["SQL/NoSQL", "Managed Services", "Replication"], ["Cloud Databases"], "Database services"),
            ("Container Orchestration", ["Kubernetes", "Container Services", "Cluster Management"], ["K8s"], "Container orchestration"),
            ("Serverless Computing", ["Functions", "Event-driven", "Scaling"], ["Serverless"], "Serverless platforms"),
            ("Infrastructure as Code", ["Terraform", "CloudFormation", "Ansible"], ["IaC Tools"], "Infrastructure automation"),
            ("Cloud Security", ["IAM", "Encryption", "Compliance", "Best Practices"], ["Cloud Security"], "Cloud security"),
            ("Cost Optimization & Governance", ["Cost Analysis", "Resource Optimization", "Governance"], ["Cost Management"], "Cost and governance"),
        ],
    },
    "project_management": {
        "domain": "Project Management",
        "name": "Project Management",
        "icon": "tasks",
        "certifications": [
            "PMP - Project Management Professional",
            "CAPM - Certified Associate in Project Management",
            "Agile Certified Practitioner (ACP)",
            "Scrum Master Certification"
        ],
        "days_progression": [
            ("Project Management Fundamentals", ["Project vs Operations", "Triple Constraint", "Project Lifecycle"], ["Fundamentals"], "PM basics"),
            ("Initiating Projects", ["Charter", "Stakeholders", "Scope", "Objectives"], ["Project Charter"], "Project initiation"),
            ("Planning - Scope", ["Scope Statement", "WBS", "Scope Baseline"], ["WBS"], "Scope planning"),
            ("Planning - Schedule", ["Activity Definition", "Duration Estimation", "Gantt Charts"], ["Gantt"], "Schedule planning"),
            ("Planning - Budget", ["Cost Estimation", "Budget Development", "Cost Baseline"], ["Budget Planning"], "Budget planning"),
            ("Planning - Risk", ["Risk Identification", "Analysis", "Mitigation"], ["Risk Register"], "Risk planning"),
            ("Planning - Quality & Procurement", ["Quality Planning", "Vendor Selection", "Contracts"], ["Quality"], "Quality & procurement"),
            ("Agile Project Management", ["Agile Principles", "Scrum Framework", "Sprints"], ["Agile"], "Agile methodology"),
            ("Kanban & Lean", ["Kanban Board", "Lean Principles", "Continuous Flow"], ["Kanban"], "Kanban approach"),
            ("Execution & Monitoring", ["Work Performance", "Status Reporting", "Change Control"], ["Execution"], "Execution phase"),
            ("Controlling Quality", ["Inspections", "Process Analysis", "Quality Assurance"], ["QA"], "Quality control"),
            ("Stakeholder Management", ["Communication Plans", "Engagement", "Conflict Resolution"], ["Stakeholder Management"], "Stakeholder engagement"),
            ("Team Management", ["Team Building", "Leadership", "Motivation", "Conflict"], ["Team Management"], "Team dynamics"),
            ("Closing Projects", ["Deliverables", "Lessons Learned", "Documentation"], ["Project Closure"], "Project closure"),
            ("Real-World Project Scenarios", ["Case Studies", "Complex Projects", "Leadership Challenges"], ["Case Studies"], "Advanced scenarios"),
        ],
    },
}

def generate_dataset(domain_key, config):
    """Generate a complete 30-day dataset from configuration."""
    dataset = {
        "domain": config["domain"],
        "name": config["name"],
        "icon": config["icon"],
        "program_title": f"{config['name']} Advanced Mastery",
        "level": "Advanced",
        "mode": "Online",
        "trainer_name": f"{config['name']} Expert",
        "certifications": config["certifications"],
        "days": []
    }
    
    # Create 30 days by cycling through and repeating topics
    days_progression = config["days_progression"]
    jira_activities = [
        "Update sprint board",
        "Log time on stories",
        "Move cards to In Progress/Done",
        "Add comments with build links",
        "Sprint planning; review progress for {topic}",
    ]
    
    for day_num in range(1, 31):
        # Select topic from progression (cycle if needed)
        topic_index = min((day_num - 1) // 2, len(days_progression) - 1)
        topic_data = days_progression[topic_index]
        topic_name = topic_data[0]
        subtopics = list(topic_data[1])
        tools = list(topic_data[2])
        lab_task = topic_data[3]
        
        # Determine jira focus
        if day_num % 5 == 0:
            jira_focus = f"Sprint planning; review progress for {topic_name}"
        elif day_num == 30:
            jira_focus = "Final sprint review, retrospective, release notes, and stakeholder demo"
        else:
            jira_focus = jira_activities[(day_num - 1) % (len(jira_activities) - 1)]
        
        day_entry = {
            "day": day_num,
            "topic": topic_name if day_num < 30 else f"Capstone Project - Part {1 if day_num < 29 else 2} + Certification Roadmap",
            "subtopics": subtopics,
            "tools": tools,
            "jira_focus": jira_focus,
            "lab_task": lab_task if day_num < 30 else f"Final project implementation, demo, retrospective, and certification roadmap review"
        }
        
        dataset["days"].append(day_entry)
    
    return dataset

def main():
    """Generate all remaining domain datasets."""
    os.makedirs(DATASETS_DIR, exist_ok=True)
    
    for domain_key, config in REMAINING_DOMAINS.items():
        filename = config["domain"].lower().replace(" ", "_") + "_30.json"
        filepath = os.path.join(DATASETS_DIR, filename)
        
        dataset = generate_dataset(domain_key, config)
        
        with open(filepath, "w") as f:
            json.dump(dataset, f, indent=2)
        
        print(f"✅ Generated: {filename}")
    
    print(f"\n✅ All {len(REMAINING_DOMAINS)} datasets generated successfully!")

if __name__ == "__main__":
    main()
