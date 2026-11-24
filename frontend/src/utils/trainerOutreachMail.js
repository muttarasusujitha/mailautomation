// The first-contact mail to a trainer, built from the page's mail fields.
// The text is the LinkedIn Pipeline's Mail 1 (buildMail in LinkedInPipeline.jsx); keep the two the same.

function clean(value, fallback = '') {
  return String(value ?? '').trim() || fallback
}

export function trainerName(lead) {
  return clean(lead?.name || lead?.trainer_name || lead?.headline, 'Trainer')
}

export function firstContactMail({ lead, mailContext = {}, foundOn = 'LinkedIn trainer profile' }) {
  const domain = clean(mailContext.domain || lead?.domain, 'your domain')
  const requirementBlock =
    `Domain: ${domain}\n` +
    (clean(mailContext.duration) ? `Duration: ${clean(mailContext.duration)}\n` : '') +
    (clean(mailContext.mode) ? `Mode: ${clean(mailContext.mode)}\n` : '') +
    (clean(mailContext.participants) ? `Participants: ${clean(mailContext.participants)}\n` : '') +
    (clean(mailContext.requirement_note) ? `\nRequirement note:\n${clean(mailContext.requirement_note)}\n` : '')
  return {
    subject: `Training Opportunity - ${domain}`,
    body:
      `Dear ${trainerName(lead)},\n\n` +
      `We found your ${foundOn} while searching for ${domain} expertise.\n\n` +
      `We have a training requirement that may match your profile:\n${requirementBlock}\n` +
      'Please confirm your interest, availability, commercials, and a brief trainer profile/TOC if relevant.' +
      '\n\nRegards,\nRecruitment Team\nClahan Technologies',
  }
}
