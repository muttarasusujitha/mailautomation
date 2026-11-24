db.email_logs.find(
  {
    mail_type: {
      $in: [
        "mail2",
        "trainer_commercials_to_client",
        "commercial_negotiation",
        "mail3",
      ],
    },
  },
  {
    _id: 0,
    email_id: 1,
    requirement_id: 1,
    trainer_id: 1,
    recipient: 1,
    to_email: 1,
    mail_type: 1,
    status: 1,
    error_message: 1,
    created_at: 1,
    subject: 1,
  },
).sort({ created_at: -1 }).limit(30).forEach(printjson);
