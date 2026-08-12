db.admin_settings.updateOne(
  {},
  {
    $set: {
      "emailCfg.smtpUser": "sujithaofficial585@gmail.com",
      "emailCfg.smtpPass": "golssxiwunqpuqcn",
      "emailCfg.imapUser": "sujithaofficial585@gmail.com",
      "emailCfg.fromEmail": "sujithaofficial585@gmail.com",
      "emailCfg.fromName": "Clahan Technologies",
    },
  },
  { upsert: true },
);

printjson(db.admin_settings.findOne({}, { _id: 0, emailCfg: 1 }));
