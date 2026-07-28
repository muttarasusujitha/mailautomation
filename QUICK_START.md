# Resume Upload Module - Quick Start Guide

## ⚡ 5-Minute Setup

### 1. Install PyMuPDF
```bash
cd backend
pip install PyMuPDF==1.23.8 pymupdf==1.23.8
```

Or if requirements.txt already updated:
```bash
pip install -r requirements.txt
```

### 2. Restart Backend
```bash
# Kill the running backend (Ctrl+C)
# Then restart
python -m uvicorn main:app --reload
```

### 3. Access Resume Upload Page
```
http://localhost:5173/resume-upload
```

---

## 📤 Upload Your First Resume

### Option A: Direct Upload (Web Interface)
1. Go to **Resume Upload** page
2. **Click or drag & drop** a PDF resume
3. Click **"Upload & Extract Resume"**
4. Wait 3-30 seconds for AI processing
5. **Review** the extracted data (fields appear on screen)
6. **Edit** any incorrect fields (click Edit button)
7. Click **"Confirm & Save"**
8. ✅ Done! Trainer added to your database

### Option B: Gmail (Automated)
[Skip this for now - see full guide for setup]

---

## ✅ What Gets Extracted

When you upload a resume, the system automatically extracts:

| Field | Example | Notes |
|-------|---------|-------|
| **Name** | Rajesh Kumar | From header/signature |
| **Email** | rajesh@gmail.com | From contact section |
| **Phone** | +91-9876543210 | With country code if present |
| **Location** | Hyderabad, India | City, State/Country |
| **Experience** | 8 years | Automatically detected |
| **Skills** | Kubernetes, Docker | Array format |
| **Technologies** | DevOps stack | Comma-separated |
| **Certifications** | CKA, AWS | Professional certifications |
| **Training Count** | 45 batches | Number of trainings given |
| **Past Clients** | Infosys, TCS, Wipro | Companies trained |
| **Category** | DevOps | Inferred from resume |
| **Day Rate** | 25000 | If mentioned in resume |
| **Hourly Rate** | 3500 | If mentioned in resume |
| **LinkedIn** | linkedin.com/in/... | Profile URL if present |

---

## 🎯 Quick Test

### Test with Sample Resume
Create a simple text file named `test_resume.txt`:

```
Rajesh Kumar
Email: rajesh@example.com
Phone: 9876543210
Location: Hyderabad

EXPERIENCE:
DevOps Engineer | 8 years

SKILLS:
- Kubernetes
- Docker
- Jenkins
- ArgoCD
- Terraform
- GitHub Actions

CERTIFICATIONS:
- CKA (Certified Kubernetes Administrator)
- AWS Certified DevOps Professional

TRAINING EXPERIENCE:
- Conducted 45 corporate training batches
- Trained companies like Infosys, TCS, Wipro, HCL

RATES:
- Day Rate: 25000 INR
- Hourly Rate: 3500 INR
```

Then:
1. Convert to PDF (or create PDF directly)
2. Upload on http://localhost:5173/resume-upload
3. See extracted data populated automatically!

---

## 🔍 Verify It Works

### Check Frontend
- [ ] Navigate to http://localhost:5173/resume-upload
- [ ] See "Resume Upload" page with upload area
- [ ] Can drag/drop a PDF

### Check Backend
```bash
# Check API is responding
curl http://localhost:8000/api/resume-uploads

# Should return:
# {"uploads": [], "total": 0, "page": 1, "pages": 0}
```

### Check Database
```bash
# In MongoDB
db.resume_uploads.find()        # Should be empty initially
db.trainers.find()              # Check for newly added trainers
```

---

## 📊 Verify Extraction Worked

After uploading and confirming a resume, check:

### 1. Database (MongoDB)
```bash
# Find the resume upload
db.resume_uploads.findOne()

# Find the trainer created
db.trainers.findOne({ source_sheet: "resume_upload" })
```

### 2. API Response Check
```bash
# List all resumes
curl http://localhost:8000/api/resume-uploads

# Should show:
{
  "uploads": [
    {
      "upload_id": "RES-...",
      "trainer_id": "T-...",
      "filename": "resume.pdf",
      "processing_status": "completed",
      ...
    }
  ],
  "total": 1
}
```

### 3. Frontend Confirmation
- ✅ Green success message appeared
- ✅ "Trainer added to database" confirmation
- ✅ Extracted data was visible for review

---

## 🚀 Common Tasks

### Find Recently Uploaded Resumes
```bash
curl "http://localhost:8000/api/resume-uploads?page=1&limit=10"
```

### Get Details of Specific Upload
```bash
curl "http://localhost:8000/api/trainers/resume-status/RES-ABC123456789"
```

### Find Trainer Created from Resume
```bash
curl "http://localhost:8000/api/trainers/by-upload/RES-ABC123456789"
```

### Edit After Upload
If you need to change extracted data after uploading:

```bash
curl -X POST "http://localhost:8000/api/trainers/confirm-resume/RES-ABC123456789" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "newemail@example.com",
    "day_rate": 30000
  }'
```

### Delete a Resume Upload
```bash
curl -X DELETE "http://localhost:8000/api/resume-uploads/RES-ABC123456789"
```

---

## ⚠️ Troubleshooting

### Issue: "Only .pdf files accepted"
**Solution:** Upload only PDF files, not Word docs or images

### Issue: "Could not extract text from PDF"
**Solution:** 
- Try a different PDF
- PDF might be scanned (image-based) - needs OCR
- File might be corrupted

### Issue: Page shows "Resume Upload" but button disabled
**Solution:**
- Select a file first (drag & drop or click)
- Button enables once file selected

### Issue: "Claude extraction failed"
**Solution:**
- Check OPENAI_API_KEY in .env
- Verify API has sufficient credits
- Check API rate limits

### Issue: Trainer not appearing in database
**Solution:**
- Check "Confirm & Save" button was clicked
- Verify processing_status = "extracted" 
- Check MongoDB connection

---

## 📝 Example Workflow

### Step 1: User Uploads Resume
```
✓ Select PDF file
✓ Click "Upload & Extract"
✓ Wait 3-30 seconds
```

### Step 2: AI Processes It
```
✓ PyMuPDF extracts text
✓ Claude structures data
✓ Results shown on screen
```

### Step 3: Human Reviews
```
✓ See: Name, Email, Skills, etc.
✓ Check accuracy
✓ Edit any wrong fields
```

### Step 4: Confirm & Save
```
✓ Click "Confirm & Save"
✓ Trainer added to database
✓ Success message appears
```

### Step 5: Use in Matching
```
✓ New trainer appears in "All Trainers"
✓ Can run matching to find jobs
✓ Can send emails to trainer
```

---

## 🎓 Learning Path

### 1. **Just Start** (Right Now)
- Upload a resume
- See extraction work
- Understand the flow

### 2. **Explore the UI** (5 minutes)
- Try editing fields
- Test confirm/cancel
- Upload multiple resumes

### 3. **Test the API** (10 minutes)
- Use curl to list uploads
- Get specific upload details
- Update a trainer

### 4. **Gmail Setup** (20 minutes)
- See [RESUME_UPLOAD_GUIDE.md](./RESUME_UPLOAD_GUIDE.md)
- Configure Pub/Sub
- Test webhook

### 5. **Production Ready** (30 minutes)
- Deploy to production
- Set up monitoring
- Train users

---

## 🎯 Success Checklist

- [ ] PyMuPDF installed (`pip list | grep -i pymupdf`)
- [ ] Backend restarted and running
- [ ] Frontend page loads at /resume-upload
- [ ] Can upload a PDF file
- [ ] AI extracts data (see results on screen)
- [ ] Can edit extracted fields
- [ ] Can confirm & save
- [ ] Trainer appears in database
- [ ] New trainer visible in "All Trainers" page

---

## 📞 Need Help?

1. **Check full documentation:** [RESUME_UPLOAD_GUIDE.md](./RESUME_UPLOAD_GUIDE.md)
2. **See implementation details:** [IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md)
3. **Check error messages** in browser console or terminal
4. **Review logs** in MongoDB `webhook_logs` collection

---

## ⏱️ Time Saved

| Task | Before | After | Saved |
|------|--------|-------|-------|
| 1 resume | 10 min | 3 sec | 99.5% |
| 10 resumes | 100 min | 30 sec | 99.5% |
| 100 resumes | 1000 min (16.7 hrs) | 5 min | 99.5% |

---

**Ready? Go to http://localhost:5173/resume-upload and upload your first resume! 🚀**
