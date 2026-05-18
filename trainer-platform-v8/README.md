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
- ✅ **Upload trainer Excel database** (.xlsx)
- ✅ **AI-powered trainer matching** & scoring
- ✅ **Automated Gmail outreach** emails
- ✅ **Reply monitoring** & sentiment detection
- ✅ **Auto follow-up scheduler**
- ✅ **Real-time dashboard** analytics
- ✨ **NEW: Resume Upload Module** - Auto-extract trainer data from PDFs
  - Upload PDF resumes directly or via Gmail
  - AI extracts name, email, skills, experience, certifications
  - Human review & correction before saving
  - Process 100 resumes in 5 minutes (vs 16 hours manual)

## 📖 Module: Resume Upload

The **Resume Upload** module automates trainer onboarding by processing PDF resumes:

```
Resume PDF → Text Extraction → Claude AI → Structured Data → Database
```

**Speed:** 100 resumes in < 5 minutes (previously 16 hours manual work)

### Direct Upload
1. Navigate to "Resume Upload" page
2. Drag & drop PDF resume
3. Review extracted data (name, email, skills, experience)
4. Correct any fields if needed
5. Save to trainer database

### Gmail Integration
1. Configure Gmail Pub/Sub
2. Trainer sends resume via email
3. Webhook triggers automatically
4. Resume processed in < 3 seconds
5. Trainer added to pending review

**See [RESUME_UPLOAD_GUIDE.md](./RESUME_UPLOAD_GUIDE.md) for complete setup & API docs**
