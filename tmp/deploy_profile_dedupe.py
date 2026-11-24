from pathlib import Path
p=Path('/app/app/routes/linkedin_leads.py')
s=p.read_text()
block="                # Regional hosts, tracking parameters, case and profile subpages\n                # all identify the same LinkedIn profile.\n                from urllib.parse import urlsplit, unquote\n                profile_path = unquote(urlsplit(source_url).path)\n                if lead.get('source') == 'linkedin' and profile_path.lower().startswith('/in/'):\n                    slug = profile_path.split('/')[2]\n                    pattern = r'^https?://(?:[a-z0-9-]+\\.)?linkedin\\.com/in/' + re.escape(slug) + r'(?:[/?#]|$)'\n                    dedupe_terms.extend({field: {'$regex': pattern, '$options': 'i'}}\n                                        for field in ('source_url', 'linkedin_url'))\n\n"
needle='                exists = await db["trainer_profile_leads"].find_one('
if block not in s: s=s.replace(needle,block+needle,1)
s=s.replace('                    {"_id": 1},\n                )\n                if exists:', '                    {"_id": 0},\n                )\n                if exists:\n                    all_results[-1].update(exists)',1)
p.write_text(s)
