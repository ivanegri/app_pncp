import re

with open('app/routes.py', 'r') as f:
    content = f.read()

# 1. Remove Postgres models imports
content = re.sub(r'from \.models import Base, db, User', r'from .models import User', content)
content = re.sub(r'from \.models import db', r'', content)
content = re.sub(r'from sqlalchemy import.*', r'', content)

# 2. In /search, it branches: if is_full_access: bq else: postgres
# We'll just assume everyone has access and use BQ only, removing the Postgres block.
content = re.sub(r"is_full_access = current_user.tier == 'full' or current_user.role == 'admin'\s+if is_full_access:\s+# BigQuery Search\s+(.*?)\s+else:\s+# Postgres Search\s+Itens = Base.*?results = \[\{.*?\]", 
                 r"\1", content, flags=re.DOTALL)

# 3. /search atas has no is_full_access toggle. It just queries BQ.
# 4. /search orgaos has Postgres only?? Wait, let's check lines 120-136.
