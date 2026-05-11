# 🎓 TrainerSync — AI Trainer Matching Platform

Full-stack trainer matching platform with LangGraph AI agents, FastAPI backend, React frontend, Gmail automation, and MongoDB.

## 📁 Project Structure

```
trainer-platform/
├── frontend/          # React + Tailwind (Vite)
├── backend/           # FastAPI + LangGraph
└── README.md
```

## ⚡ Quick Start

### 1. Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # Fill in your credentials
uvicorn main:app --reload --port 8000
```

### 2. Frontend
```bash
cd frontend
npm install
npm run dev                     # Runs on http://localhost:5173
```

## 🔑 Environment Variables (backend/.env)
```
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=trainersync
GMAIL_USER=your@gmail.com
GMAIL_APP_PASSWORD=your_app_password
OPENAI_API_KEY=your_openai_key     # Optional: for AI ranking
SECRET_KEY=your_secret_key
```

## 🚀 Features
- Upload trainer Excel database (.xlsx)
- AI-powered trainer matching & scoring
- Automated Gmail outreach emails
- Reply monitoring & sentiment detection
- Auto follow-up scheduler
- Real-time dashboard analytics
