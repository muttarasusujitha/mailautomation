"""Seed ToC Knowledge Base with broad technology datasets.

Run from backend folder:
    python scripts/seed_toc_knowledge_42.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import connect_db, close_db, get_db
from utils.time_utils import utc_now


def topic(name, tools, labs, subtopics=None):
    return {
        "topic": name,
        "subtopics": subtopics or [],
        "tools": tools,
        "lab": labs[0] if labs else f"Hands-on practice for {name}",
    }


def domain(key, name, aliases, foundation, core, advanced, projects, capstone, tools, labs, certs):
    return {
        "key": key,
        "name_key": key,
        "name": name,
        "icon": "book",
        "aliases": aliases,
        "active": True,
        "source": "admin",
        "level_map": {
            "foundation": [topic(item, tools, labs) for item in foundation],
            "core": [topic(item, tools, labs[1:] or labs) for item in core],
            "advanced": [topic(item, tools, labs[2:] or labs) for item in advanced],
            "observability": [],
            "security": [],
            "projects": [topic(item, tools, labs[3:] or labs) for item in projects],
            "revision": [],
            "capstone": [topic(capstone, tools, labs[-1:] or labs)],
        },
        "jira_practice": {
            "daily": ["Create/update training task", "Log lab evidence", "Move cards across sprint board"],
            "weekly": ["Sprint review", "Project demo", "Retrospective"],
        },
        "certifications": certs,
        "updated_at": utc_now(),
    }


DATASETS = [
    domain("javascript", "JavaScript", ["js", "vanilla_js", "es6"],
        ["Variables, data types, operators", "Control flow, loops, functions", "DOM manipulation", "Events and event listeners", "Arrays and objects"],
        ["ES6+ features", "Promises and async/await", "Fetch API and JSON", "Modules import/export", "Error handling"],
        ["Closures and scope", "Prototypes and OOP", "Design patterns", "Web APIs", "Performance optimization"],
        ["Build interactive web app", "API integration project", "DOM-based game or tool"],
        "Full JavaScript single-page application with API integration",
        ["VS Code", "Browser Console", "Chrome DevTools", "Postman", "Node.js"],
        ["Build calculator app", "Fetch and render API data", "Form validation with JS", "Build to-do list with localStorage", "Create interactive quiz app"],
        ["JavaScript Algorithms and Data Structures", "W3Schools JavaScript Certificate"]),
    domain("typescript", "TypeScript", ["ts"],
        ["TypeScript setup and tsconfig", "Types, interfaces, enums", "Functions and type annotations", "Classes and access modifiers", "Type inference"],
        ["Generics", "Union and intersection types", "Type narrowing and guards", "Modules and namespaces", "Decorators"],
        ["Advanced generics", "Utility types", "TypeScript with React", "TypeScript with Node.js", "Strict mode and best practices"],
        ["Type-safe REST API", "React app with TypeScript", "CLI tool with TypeScript"],
        "Full-stack TypeScript application with React and Node",
        ["VS Code", "TypeScript Compiler", "Node.js", "ESLint", "Prettier"],
        ["Convert JS project to TypeScript", "Build typed API service", "Generic data table component", "Type-safe form handler"],
        ["TypeScript Developer Certificate"]),
    domain("c_programming", "C Programming", ["c", "c_language"],
        ["Syntax, variables, data types", "Operators and expressions", "Control flow", "Functions and recursion", "Arrays and strings"],
        ["Pointers and memory", "Structures and unions", "File I/O", "Dynamic memory", "Preprocessor directives"],
        ["Data structures", "Bitwise operations", "Multi-file programs", "Memory management best practices", "System calls"],
        ["Build a file management system", "Implement data structures library", "Student record system"],
        "Mini OS shell or library management system in C",
        ["GCC Compiler", "VS Code", "Code::Blocks", "GDB Debugger", "Valgrind"],
        ["Write pointer-based programs", "Build linked list", "File read/write operations", "Dynamic array implementation"],
        ["C Programming Certificate"]),
    domain("cpp_programming", "C++ Programming", ["cpp", "c_plus_plus", "cplusplus"],
        ["Syntax and data types", "OOP classes and objects", "Inheritance and polymorphism", "Operator overloading", "Templates"],
        ["STL", "File handling", "Exception handling", "Pointers and references", "Memory management"],
        ["Smart pointers", "Move semantics", "Multithreading", "Design patterns in C++", "Modern C++"],
        ["Banking system OOP project", "STL-based inventory system", "Multithreaded file processor"],
        "Full OOP C++ application with STL and file persistence",
        ["G++ Compiler", "VS Code", "CLion", "GDB Debugger", "CMake"],
        ["Implement class hierarchy", "STL container operations", "Exception handling scenarios", "Template-based stack/queue"],
        ["C++ Certified Associate Programmer", "ISO C++ Foundation Certificate"]),
    domain("csharp_programming", "C# Programming", ["csharp", "c_sharp", "dotnet_csharp"],
        ["Syntax, types, variables", "OOP classes and interfaces", "Collections and generics", "Exception handling", "LINQ basics"],
        ["Async/await and tasks", "File I/O and serialization", "Entity Framework Core", "ASP.NET Core basics", "Dependency injection"],
        ["REST API with ASP.NET Core", "JWT authentication", "xUnit testing", "Design patterns", "Blazor basics"],
        ["Build CRUD API with ASP.NET Core", "Console inventory system", "REST API with EF Core"],
        "Full ASP.NET Core Web API with database and authentication",
        ["Visual Studio", ".NET CLI", "NuGet", "Postman", "SQL Server", "SQLite"],
        ["Build class library", "LINQ query operations", "ASP.NET Core API endpoints", "EF Core database operations"],
        ["Microsoft Azure Developer Associate", ".NET Developer Certificate"]),
    domain("go_programming", "Go Programming", ["go", "golang", "go_lang"],
        ["Syntax, variables, types", "Functions and multiple returns", "Arrays, slices, maps", "Structs and methods", "Pointers"],
        ["Interfaces", "Goroutines and channels", "Error handling", "Packages and modules", "File I/O"],
        ["Concurrency patterns", "REST API with Gin/Fiber", "Database with GORM", "Testing in Go", "Docker with Go"],
        ["Build REST API in Go", "CLI tool with Go", "Concurrent data processor"],
        "Production-ready Go REST API with database, auth, and Docker",
        ["Go CLI", "VS Code", "Gin", "Fiber", "GORM", "Postman", "Docker"],
        ["Goroutine and channel exercises", "Build HTTP server", "REST API with Gin", "Unit testing in Go"],
        ["Go Programming Certificate"]),
    domain("swift_programming", "Swift Programming", ["swift", "swift_ios", "apple_swift"],
        ["Variables, constants, data types", "Control flow and functions", "Optionals and unwrapping", "Classes, structs, enums", "Protocols"],
        ["UIKit basics", "SwiftUI fundamentals", "Auto Layout", "Navigation and tab bars", "Data persistence"],
        ["URLSession and Codable", "Combine framework", "Animations", "MVVM architecture", "Push notifications"],
        ["Build iOS weather app", "Notes app with CoreData", "REST API consumer app"],
        "Full iOS app with SwiftUI, networking, and local persistence",
        ["Xcode", "Swift Playgrounds", "Simulator", "CocoaPods", "SPM"],
        ["Build login screen with SwiftUI", "Fetch and display API data", "CoreData CRUD operations", "Navigation stack implementation"],
        ["Apple Developer Academy Certificate", "iOS App Development with Swift"]),
    domain("kotlin_programming", "Kotlin Programming", ["kotlin", "kotlin_android", "android_kotlin"],
        ["Syntax, variables, null safety", "Functions and lambdas", "Classes and inheritance", "Data classes and sealed classes", "Collections"],
        ["Coroutines", "Android basics", "Jetpack Compose", "ViewModel and LiveData", "Room database"],
        ["Retrofit networking", "MVVM architecture", "Dependency injection with Hilt", "JUnit testing", "App publishing"],
        ["Android to-do app", "News reader app with API", "E-commerce product listing app"],
        "Full Android app with Compose, Retrofit, Room, and Hilt",
        ["Android Studio", "Kotlin Compiler", "Gradle", "Retrofit", "Room", "Hilt"],
        ["Build UI with Jetpack Compose", "Fetch API with Retrofit", "Room database operations", "ViewModel with LiveData"],
        ["Associate Android Developer", "Kotlin Developer Certificate"]),
    domain("php", "PHP", ["php_web", "php_backend"],
        ["Syntax, variables, data types", "Control flow and functions", "Arrays and strings", "Forms and user input", "File handling"],
        ["OOP in PHP", "MySQL with PDO/MySQLi", "Sessions and cookies", "REST API basics", "Composer and autoloading"],
        ["Laravel framework", "Authentication and authorization", "MVC pattern", "API development with Laravel", "PHPUnit testing"],
        ["Blog application with Laravel", "REST API backend", "E-commerce cart system"],
        "Full-stack PHP/Laravel web application with auth and database",
        ["VS Code", "XAMPP", "Composer", "Laravel", "Postman", "MySQL"],
        ["CRUD with PHP and MySQL", "Session-based login system", "Laravel routing and controllers", "REST API with Laravel"],
        ["Zend PHP Engineer Certification", "Laravel Developer Certificate"]),
    domain("ruby_programming", "Ruby Programming", ["ruby", "ruby_on_rails", "ror"],
        ["Syntax, variables, data types", "Control flow and methods", "Arrays, hashes, symbols", "OOP classes and modules", "Blocks, procs, lambdas"],
        ["Rails MVC architecture", "ActiveRecord and migrations", "Routing and controllers", "Views and ERB templates", "Forms and validations"],
        ["REST API with Rails", "Authentication", "Background jobs", "RSpec testing", "Deployment"],
        ["Blog app with Rails", "Task management API", "E-commerce store"],
        "Full Rails application with auth, API, background jobs, and deployment",
        ["VS Code", "Ruby CLI", "Rails CLI", "PostgreSQL", "RSpec", "Postman"],
        ["Build ActiveRecord models", "Create REST endpoints", "RSpec unit tests", "Authentication with Devise"],
        ["Ruby Association Certified Programmer"]),
    domain("vuejs", "Vue.js", ["vue", "vue3"],
        ["Vue CLI and Vite setup", "Template syntax and directives", "Data binding", "Events and methods", "Computed properties and watchers"],
        ["Components and props", "Vue Router", "Pinia", "Lifecycle hooks", "API integration with Axios"],
        ["Composition API", "Custom directives", "Slots and scoped slots", "Vitest testing", "SSR with Nuxt.js"],
        ["Product listing SPA", "Dashboard with Pinia", "Nuxt.js blog"],
        "Full Vue 3 application with Router, Pinia, API, and deployment",
        ["VS Code", "Vite", "Vue DevTools", "Pinia", "Axios", "Vitest"],
        ["Component communication", "Vue Router navigation", "Pinia store operations", "API-integrated dashboard"],
        ["Vue.js Developer Certificate"]),
    domain("angular", "Angular", ["angularjs", "ng", "angular_framework"],
        ["Angular CLI setup", "Components and templates", "Directives", "Services and dependency injection", "Modules"],
        ["Angular Router", "Forms", "HTTP Client and interceptors", "RxJS observables", "Pipes"],
        ["NgRx state management", "Lazy loading", "Angular Material", "Jasmine/Karma testing", "Deployment"],
        ["Task manager SPA", "Dashboard with NgRx", "Angular PWA"],
        "Enterprise Angular application with NgRx, routing, auth, and API",
        ["VS Code", "Angular CLI", "RxJS", "NgRx", "Angular Material", "Postman"],
        ["Reactive form with validation", "HTTP service with interceptor", "NgRx store and effects", "Routing with guards"],
        ["Angular Developer Certificate"]),
    domain("nextjs", "Next.js", ["next_js", "next_react"],
        ["Next.js App Router setup", "Pages and layouts", "Client vs server components", "File-based routing", "Static and dynamic rendering"],
        ["Data fetching", "API routes", "Middleware", "Image and font optimization", "Environment variables"],
        ["NextAuth authentication", "ISR and SSG", "Caching strategies", "Prisma database integration", "Vercel deployment"],
        ["Blog with MDX", "Full-stack app with API routes", "E-commerce storefront"],
        "Full-stack Next.js app with auth, database, API, and Vercel deployment",
        ["VS Code", "Next.js CLI", "Vercel", "Prisma", "PostgreSQL", "NextAuth"],
        ["Server component data fetching", "API route with database", "Authentication with NextAuth", "Deploy to Vercel"],
        ["Next.js Developer Certificate"]),
    domain("nodejs", "Node.js", ["node", "node_js"],
        ["Node architecture and event loop", "npm and package.json", "Core modules", "CommonJS vs ES Modules", "Environment variables"],
        ["Express.js framework", "REST API design", "Middleware and routing", "Database integration", "JWT authentication"],
        ["WebSockets", "Streams and buffers", "Worker threads", "Redis caching", "Microservices basics"],
        ["REST API with Express", "Real-time chat with Socket.io", "File upload service"],
        "Production Node.js API with auth, database, caching, and Docker",
        ["VS Code", "Node.js CLI", "npm", "Postman", "MongoDB", "PostgreSQL", "Redis", "Docker"],
        ["Build HTTP server", "CRUD REST API with Express", "JWT authentication system", "WebSocket chat room"],
        ["OpenJS Node.js Application Developer", "Node.js Certificate"]),
]


EXTRA = {
    "flutter": ("Flutter", ["dart", "flutter_dart", "mobile_flutter"], ["Dart basics", "Flutter setup", "Widgets", "Layouts", "Navigation"], ["State management", "Forms", "HTTP requests", "Local storage", "Animations"], ["BLoC", "Firebase", "Push notifications", "Platform channels", "App publishing"], ["Weather app", "Notes app", "E-commerce UI"], "Full Flutter app with state management, Firebase, and deployment", ["Flutter SDK", "Android Studio", "VS Code", "Dart CLI", "Firebase"], ["Build responsive UI", "API data fetching", "Firebase auth integration", "BLoC state management"], ["Flutter Developer Certificate"]),
    "react_native": ("React Native", ["rn", "mobile_react"], ["React Native setup", "Core components", "StyleSheet", "Navigation", "State hooks"], ["FlatList", "Forms", "Axios API", "AsyncStorage", "Redux Toolkit"], ["Camera and media", "Push notifications", "Native modules", "Performance", "App publishing"], ["Task manager app", "News feed app", "Authentication flow app"], "Full React Native app with navigation, API, storage, and deployment", ["VS Code", "Expo CLI", "React Native CLI", "Android Studio", "Xcode", "Redux Toolkit"], ["Navigation stack setup", "Redux state management", "API list with FlatList", "AsyncStorage CRUD"], ["Meta React Native Developer Certificate"]),
    "google_cloud_platform": ("Google Cloud Platform", ["gcp", "google_cloud", "google_cloud_platform"], ["Cloud overview", "GCP infrastructure", "IAM and hierarchy", "Compute Engine", "Cloud Storage"], ["VPC networking", "Cloud SQL and Firestore", "Cloud Run and App Engine", "Cloud Functions", "Monitoring and Logging"], ["GKE", "BigQuery", "Pub/Sub", "Terraform on GCP", "Security best practices"], ["Deploy web app on Cloud Run", "Build serverless pipeline", "BigQuery analytics dashboard"], "End-to-end GCP deployment with VPC, Cloud Run, Cloud SQL, and monitoring", ["GCP Console", "gcloud CLI", "Cloud Shell", "Terraform", "BigQuery", "Cloud Run"], ["Launch Compute Engine VM", "Deploy containerized app", "Configure VPC", "Build Cloud Function trigger", "Set up alerts"], ["Google Associate Cloud Engineer", "Google Professional Cloud Architect", "Google Professional Data Engineer"]),
    "docker": ("Docker", ["containers", "docker_containers"], ["Container vs VM", "Docker setup", "Docker CLI", "Images and containers", "Dockerfile"], ["Custom images", "Volumes and networks", "Docker Compose", "Multi-container apps", "Registries"], ["Multi-stage builds", "Docker with CI/CD", "Docker Swarm", "Security", "Production Docker"], ["Containerize full-stack app", "Compose setup", "CI/CD pipeline with Docker"], "Production multi-container app with Compose, networking, volumes, and CI/CD", ["Docker Desktop", "Docker CLI", "Docker Compose", "Docker Hub", "GitHub Actions"], ["Build custom image", "Compose multi-service setup", "Volume and network configuration", "Push image"], ["Docker Certified Associate"]),
    "kubernetes": ("Kubernetes", ["k8s", "container_orchestration"], ["Architecture", "Pods nodes clusters", "kubectl", "Deployments", "Services"], ["ConfigMaps and Secrets", "Persistent volumes", "Namespaces", "Ingress", "Probes"], ["Helm charts", "HPA", "RBAC", "StatefulSets", "Cloud K8s"], ["Deploy microservices", "Helm chart deployment", "Auto-scaling"], "Production Kubernetes cluster deployment with Helm, RBAC, autoscaling, and monitoring", ["kubectl", "Minikube", "Kind", "Helm", "Docker", "Prometheus", "Grafana"], ["Deploy app", "Configure Ingress", "Create Helm chart", "Configure HPA"], ["CKA", "CKAD"]),
    "terraform": ("Terraform", ["iac", "infrastructure_as_code", "hcl"], ["IaC concepts", "Terraform setup", "HCL syntax", "Terraform CLI", "State management"], ["Modules", "Variables and outputs", "Data sources", "Remote state", "Workspaces"], ["Cloud Terraform", "Dynamic blocks", "Conditionals", "Terragrunt", "CI/CD"], ["Provision VPC and EC2", "Multi-environment infrastructure", "Kubernetes cluster"], "Full cloud infrastructure via Terraform with modules, remote state, and CI/CD", ["Terraform CLI", "VS Code", "AWS CLI", "GCP CLI", "Azure CLI", "GitHub Actions", "Terragrunt"], ["Basic Terraform config", "Reusable module", "Remote state", "Terraform CI/CD"], ["HashiCorp Terraform Associate"]),
    "sql": ("SQL", ["structured_query_language", "database_sql", "rdbms"], ["Database concepts", "Tables rows columns keys", "SELECT WHERE ORDER BY", "INSERT UPDATE DELETE", "Constraints"], ["JOINs", "GROUP BY", "Subqueries and CTEs", "Indexes", "Transactions"], ["Stored procedures", "Triggers and views", "EXPLAIN optimization", "Window functions", "Normalization"], ["E-commerce database design", "Reporting queries", "Migration scripts"], "Full relational database design with normalized schema, stored procedures, and reports", ["MySQL", "PostgreSQL", "MySQL Workbench", "pgAdmin", "DBeaver"], ["Complex JOINs", "Aggregate reporting", "CTE and windows", "Index optimization"], ["Oracle SQL Associate", "Microsoft SQL Server Certificate", "PostgreSQL Associate"]),
    "mongodb": ("MongoDB", ["mongo", "nosql_mongodb"], ["NoSQL vs SQL", "MongoDB setup", "Documents and collections", "CRUD", "Schema design"], ["Indexes", "Aggregation pipeline", "Relationships", "Mongoose ODM", "Schema validation"], ["Replica sets", "Sharding", "Transactions", "Change streams", "Atlas"], ["Product catalog", "User profile system", "Analytics aggregation"], "MongoDB-backed app with Mongoose, aggregation, indexes, and Atlas deployment", ["MongoDB Compass", "mongosh", "Atlas", "Mongoose", "VS Code"], ["CRUD with Compass", "Aggregation pipeline", "Mongoose schema", "Atlas setup"], ["MongoDB Associate Developer", "MongoDB DBA Associate"]),
    "graphql": ("GraphQL", ["graph_ql", "gql"], ["REST vs GraphQL", "SDL", "Queries and mutations", "Types and fields", "Resolvers"], ["Arguments and variables", "Fragments", "Subscriptions", "Apollo Server", "Apollo Client"], ["DataLoader", "Auth", "Federation", "Code-first vs schema-first", "Testing"], ["Blog API", "Real-time dashboard", "Apollo full-stack app"], "Full-stack GraphQL application with Apollo Server, Client, auth, and subscriptions", ["Apollo Studio", "GraphQL Playground", "VS Code", "Postman", "Node.js", "Apollo Server"], ["Queries and mutations", "Resolver chain", "Apollo Client", "Subscriptions"], ["Apollo Graph Developer Associate"]),
    "redis": ("Redis", ["redis_cache", "in_memory_db"], ["In-memory database", "Redis CLI", "Strings lists sets hashes", "TTL", "Pub/Sub"], ["Caching", "Session management", "Rate limiting", "Redis with Node.js", "Sorted sets"], ["Cluster and Sentinel", "Streams", "Lua scripting", "Docker", "Performance tuning"], ["API response caching", "Session store", "Real-time leaderboard"], "Redis backend with caching, sessions, rate limiting, and pub/sub", ["Redis CLI", "Redis Insight", "Node.js", "ioredis", "Docker"], ["Redis CLI CRUD", "API caching", "Session setup", "Pub/Sub messaging"], ["Redis Certified Developer"]),
    "tensorflow": ("TensorFlow", ["tf", "tf2"], ["ML recap", "TensorFlow setup", "Tensors", "Keras basics", "Data preprocessing"], ["Neural networks", "Training and evaluation", "Classification and regression", "CNNs", "Model saving"], ["Transfer learning", "RNNs and LSTMs", "tf.data", "TensorFlow Lite", "TensorFlow Serving"], ["Image classifier", "Sentiment model", "Time series forecasting"], "End-to-end ML pipeline with TensorFlow data prep, training, evaluation, and deployment", ["Python", "TensorFlow", "Keras", "Jupyter", "Colab", "TensorBoard"], ["Train neural network", "CNN image classifier", "Transfer learning", "TF Serving deployment"], ["TensorFlow Developer Certificate"]),
    "pytorch": ("PyTorch", ["torch", "deep_learning_pytorch"], ["Tensors", "Autograd", "Dataset/DataLoader", "nn.Module", "Loss and optimizers"], ["Training loop", "CNN", "Transfer learning", "Evaluation metrics", "GPU training"], ["RNNs LSTMs Transformers", "Custom datasets", "Hugging Face", "TorchServe", "Distributed training"], ["Image classification", "NLP sentiment", "Object detection"], "Deep learning project with custom dataset, training, evaluation, and deployment", ["Python", "PyTorch", "Jupyter", "Colab", "torchvision", "Hugging Face", "CUDA"], ["Tensor operations", "CNN pipeline", "Fine-tune model", "Export inference"], ["PyTorch Developer Certificate", "Deep Learning Specialization"]),
    "langchain": ("LangChain", ["lang_chain", "llm_framework"], ["LLM recap", "LangChain setup", "Chains and prompts", "LLM wrappers", "Output parsers"], ["Memory", "Document loaders", "Embeddings", "RAG", "Agents and tools"], ["LangGraph", "Custom tools", "LangSmith", "Multi-modal chains", "Production deployment"], ["RAG document Q&A", "Customer support chatbot", "Multi-agent research pipeline"], "Production LangChain agentic app with RAG, memory, tools, and LangSmith", ["Python", "LangChain", "OpenAI API", "Anthropic API", "FAISS", "Chroma", "Pinecone", "LangSmith", "FastAPI"], ["Prompt chain", "PDF RAG pipeline", "Agent with tools", "LangSmith trace"], ["LangChain Developer Certificate"]),
    "tableau": ("Tableau", ["tableau_desktop", "data_viz_tableau"], ["Tableau setup", "Data sources", "Dimensions vs measures", "Basic charts", "Filters and sorting"], ["Calculated fields", "Parameters", "Dashboards and stories", "LOD expressions", "Joins and blending"], ["Advanced LOD", "Table calculations", "Tableau Prep", "Server publishing", "Performance"], ["Sales dashboard", "HR analytics", "Customer segmentation"], "Full Tableau dashboard with multiple data sources, LOD, parameters, and publishing", ["Tableau Desktop", "Tableau Prep", "Tableau Public", "Tableau Server", "Excel", "SQL"], ["Sales dashboard", "LOD exercises", "Filters and parameters", "Publish dashboard"], ["Tableau Desktop Specialist", "Tableau Certified Data Analyst"]),
    "apache_spark": ("Apache Spark", ["spark", "pyspark", "spark_big_data"], ["Big data concepts", "Spark architecture", "RDDs", "PySpark setup", "DataFrames"], ["Transformations and actions", "Spark SQL", "Read/write data", "Aggregations", "Joins"], ["Spark Streaming", "MLlib", "Delta Lake", "Optimization", "Databricks/EMR"], ["PySpark ETL", "Log analysis", "Streaming pipeline"], "Spark data pipeline with ingestion, transformation, SQL analysis, and output", ["PySpark", "Jupyter", "Databricks", "HDFS", "S3", "Kafka", "Delta Lake"], ["DataFrame transformations", "Spark SQL", "Join aggregation", "Streaming processing"], ["Databricks Spark Developer"]),
    "snowflake": ("Snowflake", ["snowflake_dw", "cloud_data_warehouse"], ["Cloud data warehouse", "Snowflake architecture", "UI and SQL", "Databases schemas tables", "COPY INTO"], ["Semi-structured data", "Stages and file formats", "Cloning and time travel", "RBAC", "Performance"], ["Streams and tasks", "Dynamic tables", "Snowpipe", "Data sharing", "Snowpark"], ["Warehouse from CSV/JSON", "CDC with streams/tasks", "Reporting layer"], "Snowflake warehouse with ingestion, transformation, CDC, and role-based access", ["Snowflake Console", "SnowSQL", "dbt", "Python Snowpark", "S3", "GCS"], ["Load structured data", "JSON queries", "Time travel cloning", "Stream task pipeline"], ["SnowPro Core", "SnowPro Advanced Data Engineer"]),
    "dbt": ("dbt", ["data_build_tool", "dbt_core", "dbt_cloud"], ["Analytics engineering", "dbt setup", "Models", "Sources and refs", "Running/testing dbt"], ["Tests", "Docs and lineage", "Seeds and snapshots", "Jinja/macros", "Freshness"], ["Incremental models", "Packages", "Custom macros", "Cloud CI/CD", "Warehouse integration"], ["Transform e-commerce data", "Reporting layer", "dbt Snowflake pipeline"], "dbt project with models, tests, docs, incremental loads, and CI/CD", ["dbt CLI", "dbt Cloud", "VS Code", "Snowflake", "BigQuery", "PostgreSQL", "GitHub"], ["Staging and mart models", "dbt tests", "Jinja macro", "Incremental model"], ["dbt Certified Developer"]),
    "apache_kafka": ("Apache Kafka", ["kafka", "event_streaming", "kafka_streams"], ["Event streaming", "Kafka architecture", "Producers and consumers", "Kafka CLI", "Kafka Docker"], ["Consumer groups", "Kafka Connect", "Schema Registry", "Kafka Streams", "DLQ"], ["Streams aggregations", "ksqlDB", "Security", "Kafka with Spark", "Production tuning"], ["Event pipeline", "Order tracking stream", "Log aggregation"], "Kafka streaming pipeline with producers, consumers, streams, and monitoring", ["Apache Kafka", "Docker Compose", "Kafka CLI", "Confluent Platform", "ksqlDB", "Prometheus", "Grafana"], ["Topics produce consume", "Kafka Connect", "Streams word count", "ksqlDB query"], ["Confluent Kafka Developer"]),
    "databricks": ("Databricks", ["azure_databricks", "databricks_lakehouse"], ["Lakehouse architecture", "Workspace setup", "Notebooks and clusters", "PySpark", "Delta Lake"], ["Delta tables", "Auto Loader", "Databricks SQL", "Workflows/jobs", "Unity Catalog"], ["Delta Live Tables", "MLflow", "Feature Store", "dbt integration", "Performance tuning"], ["Medallion pipeline", "MLflow training", "DLT streaming"], "Databricks lakehouse pipeline with DLT, MLflow, Unity Catalog, and dashboards", ["Databricks Workspace", "PySpark", "Delta Lake", "MLflow", "Auto Loader", "Databricks SQL"], ["Delta operations", "Auto Loader", "MLflow tracking", "DLT pipeline"], ["Databricks Data Engineer Associate", "Databricks ML Associate"]),
    "power_automate": ("Power Automate", ["ms_flow", "microsoft_flow", "power_automate_rpa"], ["Overview", "Cloud vs desktop flows", "Triggers and actions", "Connectors", "Templates"], ["Conditions", "Loops", "Variables expressions", "Approvals", "Error handling"], ["Desktop RPA", "HTTP connectors", "Custom connectors", "Child flows", "Dataverse"], ["Onboarding automation", "Approval workflow", "Data sync"], "Business process automation with approvals, notifications, RPA, and custom connectors", ["Power Automate Portal", "Power Automate Desktop", "SharePoint", "Teams", "Dataverse"], ["Email notification flow", "Teams approval", "Desktop UI automation", "HTTP connector"], ["Microsoft PL-500", "Microsoft PL-900"]),
    "sharepoint": ("SharePoint", ["ms_sharepoint", "sharepoint_online"], ["Online overview", "Sites pages libraries lists", "Navigation permissions", "Document management", "SharePoint vs OneDrive"], ["Site collections", "Content types metadata", "Power Automate workflows", "SPFx basics", "Search"], ["SPFx web parts", "REST API", "Power Apps", "Governance", "Migration"], ["Intranet portal", "Document approval", "SPFx web part"], "SharePoint intranet with SPFx, Power Automate workflows, and governance", ["SharePoint Admin Center", "VS Code", "SPFx", "Power Automate", "Power Apps", "REST API"], ["Team site", "List workflow", "SPFx web part", "Permissions governance"], ["Microsoft 365 Fundamentals"]),
    "spring_boot": ("Spring Boot", ["springboot", "spring_framework", "java_spring"], ["Setup structure", "Auto-configuration", "REST controllers", "Dependency injection", "Properties"], ["Spring Data JPA", "Hibernate ORM", "REST API design", "Validation", "Exception handling"], ["Spring Security", "Testing", "Spring Cloud", "Microservices", "Docker"], ["CRUD API", "E-commerce backend", "Eureka microservices"], "Spring Boot microservices app with security, database, Docker, and CI/CD", ["IntelliJ", "VS Code", "Maven", "Gradle", "Spring Initializr", "Postman", "PostgreSQL", "Docker"], ["REST API", "JPA repository", "JWT auth", "Dockerization"], ["Spring Professional Developer", "Oracle Java SE"]),
    "django": ("Django", ["python_django", "django_rest"], ["Setup structure", "MVT architecture", "Models migrations", "Views URL routing", "Templates"], ["Django ORM", "Forms", "DRF", "Auth permissions", "Admin panel"], ["JWT with DRF", "Celery", "Redis caching", "Channels", "Deployment"], ["Blog CRUD", "DRF API", "E-commerce backend"], "Django REST API with auth, tasks, caching, and Docker", ["VS Code", "Django CLI", "DRF", "PostgreSQL", "Redis", "Celery", "Docker"], ["Model migrate", "DRF serializers", "JWT auth", "Celery task"], ["Django Developer Certificate"]),
    "fastapi": ("FastAPI", ["fast_api", "python_fastapi"], ["Setup structure", "Path operations", "Pydantic models", "Query/path params", "Async endpoints"], ["Dependency injection", "SQLAlchemy database", "OAuth2/JWT", "Middleware CORS", "Error handling"], ["Background tasks", "WebSockets", "File uploads", "Docker", "pytest testing"], ["FastAPI PostgreSQL API", "File upload service", "Notification API"], "Production FastAPI app with async DB, JWT, background tasks, and Docker", ["VS Code", "Python", "FastAPI", "Uvicorn", "Pydantic", "SQLAlchemy", "PostgreSQL", "Docker"], ["CRUD endpoints", "JWT auth", "Async DB", "Docker deployment"], ["Python API Development Certificate"]),
    "dotnet": (".NET", ["dot_net", "aspnet", "asp_net_core"], [".NET ecosystem", "C# recap", "ASP.NET Core setup", "MVC", "Razor Pages"], ["Web API", "EF Core", "Dependency injection", "Middleware", "Configuration"], ["SignalR", "gRPC", "Microservices", "Azure deployment", "Blazor"], ["MVC web app", "REST API", "Docker microservice"], ".NET Web API with EF Core, JWT, SignalR, Docker, and Azure", ["Visual Studio", "VS Code", ".NET CLI", "NuGet", "SQL Server", "Azure", "Docker"], ["MVC CRUD", "EF Core API", "JWT auth", "Azure App Service"], ["Microsoft AZ-204", ".NET MAUI Developer Certificate"]),
    "linux_shell_scripting": ("Linux and Shell Scripting", ["linux", "shell", "bash_scripting", "linux_admin", "shell_scripting"], ["Linux overview", "Filesystem hierarchy", "Basic commands", "Permissions", "Text editors"], ["Process management", "Package management", "Bash scripting", "Loops conditionals", "Cron jobs"], ["Advanced scripting", "Networking commands", "SSH", "Monitoring", "Security hardening"], ["Server setup script", "Log analyzer", "Health monitor"], "Linux server setup and automation with shell scripts, cron, SSH, and monitoring", ["Linux", "Bash", "Terminal", "Vi/Vim", "SSH", "Cron"], ["File automation", "Process management", "Bash loops", "SSH setup"], ["LFCS", "CompTIA Linux+", "RHCSA"]),
    "networking_ccna": ("Networking and CCNA", ["networking", "ccna", "cisco_networking", "network_fundamentals"], ["OSI TCP/IP", "IP addressing subnetting", "Devices", "Ethernet LAN", "Cabling"], ["VLANs", "Routing", "NAT/PAT", "ACLs", "DHCP DNS"], ["WAN", "Security basics", "QoS", "IPv6", "Wireless"], ["Enterprise network", "Inter-VLAN routing", "ACL policies"], "Enterprise network design in Packet Tracer with routing, VLANs, ACLs, and security", ["Cisco Packet Tracer", "GNS3", "Wireshark", "PuTTY", "Cisco IOS CLI"], ["Subnet design", "VLAN config", "OSPF routing", "ACL implementation"], ["Cisco CCNA", "CompTIA Network+"]),
    "uiux_design": ("UI/UX Design", ["uiux", "ui_ux", "ux_design", "user_experience", "user_interface"], ["UX vs UI", "Design thinking", "User research", "Information architecture", "Wireframing"], ["Personas journeys", "Prototypes", "Visual design", "Design systems", "Usability testing"], ["Figma advanced", "WCAG", "Responsive design", "Motion basics", "Developer handoff"], ["Mobile redesign", "Web app design system", "Product UX"], "UX project with research, wireframe, prototype, usability test, and Figma handoff", ["Figma", "FigJam", "Maze", "Notion", "Miro"], ["Wireframe app", "Figma prototype", "Usability test", "Design system"], ["Google UX Design Certificate", "IDF Certificate", "NN/g UX Certificate"]),
}

for key, args in EXTRA.items():
    DATASETS.append(domain(key, *args))


async def main():
    await connect_db()
    db = get_db()
    now = utc_now()
    for doc in DATASETS:
        doc["updated_at"] = now
        await db["toc_domain_knowledge"].update_one(
            {"key": doc["key"]},
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
    await close_db()
    print(f"Seeded {len(DATASETS)} ToC knowledge domains")


if __name__ == "__main__":
    asyncio.run(main())
