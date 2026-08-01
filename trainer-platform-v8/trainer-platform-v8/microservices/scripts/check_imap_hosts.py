from pymongo import MongoClient
client = MongoClient('mongodb://mongo:27017')
db = client.get_database('trainersync')
results = list(db['admin_settings'].find({}, {'_id':1,'emailCfg.imapHost':1,'imapHost':1}))
if not results:
    print('NO_ADMIN_SETTINGS')
else:
    for r in results:
        _id = r.get('_id') or r.get('settings_id')
        imap = None
        if 'emailCfg' in r and isinstance(r['emailCfg'], dict):
            imap = r['emailCfg'].get('imapHost')
        imap_top = r.get('imapHost')
        print('DOC', _id, 'imapHost_emailCfg=', imap or '', 'imapHost_top=', imap_top or '')
