# Email Templates Reference

Complete list of all email templates used in TrainerSync platform workflow.

---

## 1. **mail2** - Client Details Request
**Sent To:** Client  
**Trigger:** Initial requirement received  
**Purpose:** Ask for missing training details
```
Dear [Client],

Thank you for sharing your [Domain] training requirement.

To help us identify and recommend the most suitable trainers, 
kindly provide the following details:

* Training duration
* Preferred training dates
* Daily training timings
* Participant count
* Location
* Audience level (Beginner / Intermediate / Advanced)

Meanwhile, we will begin an initial trainer search based on the [Domain] 
domain and the information currently available. Once we receive the above 
details, we will refine the shortlist and share the most relevant trainer 
profiles for your review.

We look forward to your response.

Regards,
Recruitment Team,
Clahan Technologies
```

---

## 2. **mail2_followup** - Client Details Reminder (Trainer Focused)
**Sent To:** Trainer/Client  
**Trigger:** Follow-up when details not received  
**Purpose:** Request missing trainer qualifications
```
Dear [Recipient],

Thank you for confirming your interest.

To proceed further, kindly share the above requested details:

* Total years of experience
* Number of trainings conducted previously
* Relevant certifications
* Preferred training mode (Online / Offline)
* Availability for Full-Day or Half-Day sessions
* Expected commercial charges per day/session
* Current location
* Availability for the mentioned dates

Once we receive these details, we can move ahead with the next step.

Regards,
TrainerSync Team
```

---

## 3. **mail3** - Interview Slot Booking
**Sent To:** Client/Trainer  
**Trigger:** After trainer selection  
**Purpose:** Confirm interview time slots
```
Dear [Recipient],

Thank you for sharing your details.

We would like to book an interview slot with you. Based on your availability, 
please confirm one of the following slots:

• [Slot 1]
• [Slot 2]
• [Slot 3]

Kindly confirm your preferred slot at the earliest.

Regards,
TrainerSync Team
```

---

## 4. **mail4** - Interview Schedule Confirmation
**Sent To:** Trainer  
**Trigger:** Interview time finalized  
**Purpose:** Confirm interview details
```
Dear [Trainer],

Your interview has been scheduled. Please find the details below:

Date & Time: [Date & Time]
Platform: [Platform]
Meeting Link: [Meeting Link]

Please join on time. Let us know if you need any assistance.

Regards,
TrainerSync Team
```

---

## 5. **mail_budget_confirm** - Client Budget Approval ✅
**Sent To:** Client  
**Trigger:** Trainer charges identified  
**Purpose:** Confirm budget with client
```
Dear [Client],

We have identified a suitable trainer for your [Domain] training.

Budget Details:
Total Training Cost: INR [Budget]

This includes the trainer's fees, food, accommodation, and travel charges.

Please confirm if you are comfortable with this budget. If yes, we will 
proceed with the trainer. If not, we will search for another trainer 
within your budget.

We look forward to your confirmation.

Regards,
Recruitment Team,
Clahan Technologies
```

---

## 6. **mail_trainer_budget_negotiate** - Trainer Salary Offer ✅
**Sent To:** Trainer  
**Trigger:** Client budget fixed, need trainer confirmation  
**Purpose:** Negotiate trainer charges
```
Dear [Trainer],

The client has confirmed their training budget is INR [Budget].

Your charges would be: INR [Trainer Amount]

This includes food, accommodation, and all travel charges we will provide 
to you.

Can you proceed with this rate? Please confirm.

Regards,
Clahan Technologies
```

---

## 7. **mail_trainer_decline** - Trainer Rejection ✅
**Sent To:** Trainer  
**Trigger:** Trainer asks for more charges  
**Purpose:** Decline trainer and explain budget constraint
```
Dear [Trainer],

Thank you for your response. However, the client's budget is fixed at 
INR [Budget]. We cannot accommodate the additional charges you've requested.

Please note that Clahan Technologies provides food, accommodation, and travel 
charges as complete hospitality to trainers.

We will search for another suitable trainer for this opportunity and get back 
to you in case of future requirements where your charges align with the 
client's budget.

Best Regards,
Clahan Technologies
```

---

## 8. **mail3_slot_followup** - Trainer Slot Details Request
**Sent To:** Trainer  
**Trigger:** Incomplete slot information  
**Purpose:** Request clear interview slot details
```
Dear [Trainer],

Thank you for sharing the slot. Could you please provide the exact interview 
date and time, including whether it is AM or PM?

Also, please share 3 available slots with the corresponding dates so that we 
can schedule the interview accordingly.

Thanks.
```

---

## 9. **mail5_ok** - Trainer Selected
**Sent To:** Trainer  
**Trigger:** Trainer approved for project  
**Purpose:** Congratulate and request ToC
```
Dear [Trainer],

Congratulations! We are pleased to inform you that you have been selected 
for the [Domain] training requirement.

To proceed further, kindly share the following:

* Table of Contents (ToC) / Course Agenda for the training
* Any prerequisite materials or tools required

We look forward to working with you!

Regards,
TrainerSync Team
```

---

## 10. **mail5_no** - Trainer Rejected
**Sent To:** Trainer  
**Trigger:** Another trainer selected  
**Purpose:** Polite rejection
```
Dear [Trainer],

Thank you for your time and interest in the [Domain] training requirement.

After careful consideration, we regret to inform you that we have decided to 
proceed with another trainer at this time.

We will keep your profile on record and reach out for future opportunities.

Thank you once again for your cooperation.

Regards,
TrainerSync Team
```

---

## 11. **mail6_toc** - Table of Contents Request
**Sent To:** Trainer  
**Trigger:** Before training starts  
**Purpose:** Collect course materials
```
Dear [Trainer],

Congratulations again on being selected for the [Domain] training!

To initiate the onboarding process, kindly share the following at the earliest:

* Detailed Table of Contents (ToC) / Course Agenda
* Day-wise session breakdown
* Tools, software, or prerequisites required by participants
* Estimated preparation time needed

Please revert at the earliest so we can coordinate with the client on schedule.

Regards,
TrainerSync Team
```

---

## 12. **mail7_confirm** - Final Confirmation
**Sent To:** Trainer  
**Trigger:** All details confirmed  
**Purpose:** Final confirmation before training
```
Dear [Trainer],

We are pleased to confirm your engagement for the [Domain] training. 
Please find the final details below:

Training Date: [Training Date]
Venue / Platform: [Venue / Platform]

Action Items Before Training:
* Ensure all materials and slides are ready
* Share soft copies of training content with us 2 days prior
* Confirm your availability 24 hours before the training

For any questions or additional information, please contact:

Contact Name: [Contact Name]
```

---

## Workflow Integration Map

```
Client Requirement
    ↓
mail2 (Ask for details)
    ↓
Client Provides Details
    ↓
mail_budget_confirm (Confirm budget with client)
    ↓
Trainer Identified
    ↓
mail_trainer_budget_negotiate (Offer charges to trainer)
    ↓
├─ YES: mail5_ok (Trainer selected)
└─ NO/Extra: mail_trainer_decline (Reject trainer)
    ↓
mail3 (Book interview slots)
    ↓
mail4 (Confirm interview schedule)
    ↓
mail5_ok (Congratulate trainer)
    ↓
mail6_toc (Request course materials)
    ↓
mail7_confirm (Final confirmation)
```

---

**Last Updated:** 2026-06-20  
**Location:** [backend/routes/api.py](backend/routes/api.py#L8532-L8750)
