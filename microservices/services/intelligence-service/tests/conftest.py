import os

# Route tests must not send real search engine requests. Finder tests call
# find_trainers directly with fake engines, or enable it explicitly.
os.environ.setdefault('TRAINER_FINDER_ENABLED', 'false')
