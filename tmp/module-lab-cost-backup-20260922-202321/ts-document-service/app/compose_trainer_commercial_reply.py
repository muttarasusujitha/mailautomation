def compose_trainer_commercial_reply(
    trainer_data: dict,
    client_name: str = "Valued Client",
    requirement: dict = None,
    signature: str = None
) -> dict:
    """
    Compose a reply email with trainer's commercial details for the client.
    This sends trainer budget, rates, and availability back to the client.
    """
    
    trainer_name = trainer_data.get("display_name") or trainer_data.get("name", "Trainer")
    email = trainer_data.get("email", "")
    phone = trainer_data.get("phone", "")
    location = trainer_data.get("location", "")
    experience = trainer_data.get("experience_years", "")
    day_rate = trainer_data.get("day_rate", "")
    hourly_rate = trainer_data.get("hourly_rate", "")
    availability = trainer_data.get("availability", "Flexible")
    certifications = trainer_data.get("certifications", [])
    skills = trainer_data.get("skills", [])
    
    if isinstance(certifications, str):
        certifications = [c.strip() for c in certifications.split(",")]
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",")]
    
    tech_list = ", ".join(skills[:5]) if skills else "Enterprise Training"
    
    # Build commercial details section
    commercial_section = ""
    if day_rate:
        commercial_section += f"\n- **Day Rate:** {day_rate}"
    if hourly_rate:
        commercial_section += f"\n- **Hourly Rate:** {hourly_rate}"
    if availability:
        commercial_section += f"\n- **Availability:** {availability}"
    
    # Build certifications section
    cert_section = ""
    if certifications:
        certs_text = ", ".join(certifications[:3])
        cert_section = f"\n\n**Certifications:** {certs_text}"
    
    # Determine technology mentioned
    technology = requirement.get("technology_needed", "training") if requirement else "training"
    
    subject = f"Trainer Profile - {trainer_name} | {tech_list} | Commercial Details"
    
    body = f"""Dear {client_name},

Thank you for your training requirement. We are pleased to present a trainer profile matching your needs:

**Trainer Profile:**
**Name:** {trainer_name}
**Location:** {location}
**Experience:** {experience}+ years
**Skills:** {tech_list}
**Email:** {email}
**Phone:** {phone}

**Commercial Details:**
{commercial_section}

{cert_section}

This trainer is ready to engage for your {technology} training requirement. They can be available as per your schedule and have successfully delivered training to similar organizations.

Please let us know if you would like to proceed with this trainer profile or need any additional information.

Best Regards,
Recruitment Team,
Clahan Technologies
"""
    
    return {
        "subject": subject,
        "body": body,
        "has_commercial_details": bool(commercial_section),
        "trainer_name": trainer_name,
        "trainer_email": email,
        "day_rate": day_rate,
        "hourly_rate": hourly_rate
    }


# Example usage
if __name__ == "__main__":
    trainer_data = {
        "display_name": "Karan Verma",
        "email": "karan.verma@example.com",
        "phone": "+91-9876543210",
        "location": "Bengaluru",
        "experience_years": 8,
        "day_rate": "₹18,000",
        "hourly_rate": "₹2,500",
        "availability": "Flexible - Full-day & Half-day sessions",
        "certifications": ["AWS Certified Cloud Practitioner", "Oracle Certified Java Programmer"],
        "skills": "DevOps, Cloud, Docker, Kubernetes, CI/CD"
    }
    
    reply = compose_trainer_commercial_reply(
        trainer_data,
        client_name="Calhan Technologies",
        requirement={"technology_needed": "DevOps & Cloud Training"}
    )
    
    print("Subject:", reply["subject"])
    print("\nBody:\n", reply["body"])
