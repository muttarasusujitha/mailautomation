# What clients asked for (build order for level courses)

Source: the exported client mailbox (`hostinger_conversations.md`, 2,254 conversations, September 2025 to October 2026). Only aggregate counts are kept here: no names, emails or companies.

How it was counted:
- Inbound messages only, from outside the company. Mail from Microsoft, Slack, Hostinger, newsletters and other vendors' sales pitches is skipped.
- A message counts as a request when it reads like one ("training requirement", "trainer required", "TOC", "duration", "participants", and so on). 654 request threads from 105 client companies matched.
- Quoted replies and email signatures are cut off first, so a technology in a job title or a footer is not counted.
- Each technology is counted once per thread. "Client companies" is the number of different sender domains that asked for it.
- Technologies are matched against every course name and alias, every name in `categories.json`, plus extra market terms such as exam codes (AZ-104, AI-102) and SAP modules.
- `*` marks broad words. "Cloud" and "testing" also appear in ordinary sentences, so their counts are too high.

"Old dataset only" means the technology has an older `datasets_compact` course but no Beginner/Intermediate/Advanced course yet.

| Rank | Technology | Request threads | Client companies | Course today |
|---|---|---|---|---|
| 1 | Cloud * | 85 | 23 | Old dataset only |
| 2 | SAP | 82 | 21 | Old dataset only |
| 3 | Generative AI | 64 | 26 | Old dataset only |
| 4 | DevOps | 52 | 25 | Old dataset only |
| 5 | AWS | 46 | 17 | Level course ✅ |
| 6 | Azure | 46 | 21 | Level course ✅ |
| 7 | Soft Skills | 43 | 18 | No course |
| 8 | Testing & QA * | 42 | 12 | Old dataset only |
| 9 | Java | 38 | 11 | Level course ✅ |
| 10 | Python | 35 | 11 | Level course ✅ |
| 11 | Agentic AI | 32 | 11 | Old dataset only |
| 12 | Data Engineering | 28 | 13 | Old dataset only |
| 13 | GCP | 26 | 9 | Level course ✅ |
| 14 | Git | 25 | 5 | Level course ✅ |
| 15 | Full Stack | 23 | 10 | Old dataset only |
| 16 | Prompt Engineering | 23 | 6 | Old dataset only |
| 17 | SQL | 23 | 8 | Level course ✅ |
| 18 | Cybersecurity | 21 | 12 | Old dataset only |
| 19 | Microsoft Copilot | 20 | 6 | No course |
| 20 | Machine Learning | 19 | 8 | Old dataset only |
| 21 | .NET / C# | 18 | 9 | No course |
| 22 | Project Management | 18 | 13 | Old dataset only |
| 23 | RAG | 18 | 6 | Old dataset only |
| 24 | React | 18 | 7 | Old dataset only |
| 25 | Salesforce | 18 | 8 | Old dataset only |
| 26 | Docker | 17 | 7 | Level course ✅ |
| 27 | Advanced Excel | 16 | 10 | No course |
| 28 | Agile / Scrum | 16 | 6 | Old dataset only |
| 29 | Power BI | 16 | 11 | Old dataset only |
| 30 | Spring Boot | 16 | 7 | Old dataset only |
| 31 | Data Analytics | 14 | 7 | Old dataset only |
| 32 | Kubernetes | 13 | 5 | Level course ✅ |
| 33 | Data Science | 12 | 7 | Old dataset only |
| 34 | Databricks | 12 | 7 | Old dataset only |
| 35 | SAP S/4HANA | 12 | 3 | Old dataset only |
| 36 | Jenkins | 11 | 4 | Level course ✅ |
| 37 | LangChain | 11 | 4 | Old dataset only |
| 38 | MCP | 11 | 4 | Old dataset only |
| 39 | PostgreSQL | 11 | 4 | No course |
| 40 | ServiceNow | 11 | 5 | Old dataset only |
| 41 | Linux | 10 | 5 | No course |
| 42 | Mainframe / COBOL | 10 | 4 | No course |
| 43 | SAFe | 10 | 4 | No course |
| 44 | Terraform | 10 | 4 | Level course ✅ |
| 45 | IAM | 9 | 4 | Old dataset only |
| 46 | Observability | 9 | 4 | Old dataset only |
| 47 | Oracle Fusion | 9 | 3 | No course |
| 48 | SAP BTP | 9 | 5 | Old dataset only |
| 49 | SRE | 9 | 5 | Old dataset only |
| 50 | Apache Spark | 8 | 4 | No course |
| 51 | CCNA / Cisco | 8 | 5 | No course |
| 52 | DSA & Algorithms | 8 | 5 | Old dataset only |
| 53 | Cloud Security | 7 | 5 | Old dataset only |
| 54 | Product Management | 7 | 3 | Old dataset only |
| 55 | Prometheus / Grafana | 7 | 5 | No course |
| 56 | SQL Server | 7 | 4 | No course |
| 57 | Angular | 6 | 5 | No course |
| 58 | Ansible | 6 | 5 | Level course ✅ |
| 59 | ETL/ELT | 6 | 3 | Old dataset only |
| 60 | ITIL | 6 | 4 | No course |
| 61 | MLOps | 6 | 4 | Old dataset only |
| 62 | MySQL | 6 | 3 | No course |
| 63 | SAP ABAP | 6 | 5 | Old dataset only |
| 64 | SAP FICO | 6 | 4 | Old dataset only |
| 65 | SAP HCM / SuccessFactors | 6 | 4 | No course |
| 66 | Tableau | 6 | 6 | No course |
| 67 | Apache Airflow | 5 | 4 | No course |
| 68 | Apache Kafka | 5 | 4 | No course |
| 69 | Azure DevOps | 5 | 4 | Old dataset only |
| 70 | GRC | 5 | 4 | No course |
| 71 | Informatica | 5 | 3 | No course |
| 72 | LangGraph | 5 | 4 | Old dataset only |
| 73 | MERN Stack | 5 | 3 | Old dataset only |
| 74 | SharePoint | 5 | 3 | No course |
| 75 | VMware | 5 | 3 | No course |

## Build order from this demand

Gaps first, ordered by how many client companies asked:

1. **AI:** Generative AI (26 companies), Agentic AI (11), RAG Pipelines (6), Microsoft Copilot (6), Prompt Engineering (6).
2. **SAP:** SAP (21 companies) split into the modules clients name: S/4HANA, BTP, ABAP, FICO, SuccessFactors, Fiori.
3. **DevOps programme** (25 companies). Waiting on the decision about replacing the client-tuned 10-day DevOps order.
4. **Data and analytics:** Data Engineering (13), Power BI (11), Advanced Excel (10), Machine Learning (8), Data Analytics (7), Databricks (7), Data Science (7).
5. **Management:** Project Management (13), Agile/Scrum (6), SAFe (4), ITIL (4).
6. **Security and testing:** Cybersecurity (12), Testing & QA (12), Cloud Security (5).
7. **Web and enterprise apps:** Full Stack (10), .NET/C# (9), Salesforce (8), React (7), Spring Boot (7), ServiceNow (5), Angular (5).
8. **Infrastructure:** Linux (5), CCNA (5), PostgreSQL (4), Mainframe/COBOL (4), Oracle Database, SQL Server, VMware.
9. **Soft Skills** (18 companies). Not a technology, but clients ask for it often.

Technologies clients asked for that were not listed anywhere before were added to `categories.json` as planned. They include Generative AI, SAP BTP, SAP ABAP, SAP Fiori, SAP SuccessFactors, SAP SD, SAP BW/4HANA, COBOL and Mainframe, Informatica, GRC, Palo Alto, Manual Testing and ISTQB, VMware, Nutanix, Windows Server, Microsoft 365 administration and Soft Skills.
