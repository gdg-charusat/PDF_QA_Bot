"""
DEMO: Cross-User Data Leakage — BUG vs FIX
============================================
STEP 1: Reproduces the old vulnerable code (no ownership check).
STEP 2: Runs the fixed code (session bound to user_id, attack blocked).
"""

import sys, uuid, time, types
from unittest.mock import MagicMock

for mod in [
    "torch", "transformers", "langchain_community", "langchain_text_splitters",
    "langchain_core", "langchain_community.document_loaders",
    "langchain_community.vectorstores", "langchain_community.embeddings",
    "langchain_core.documents", "slowapi", "slowapi.util", "slowapi.errors",
    "dotenv", "uvicorn",
]:
    sys.modules.setdefault(mod, MagicMock())

SEP  = "=" * 70
DASH = "-" * 70

class FakeVectorStore:
    def __init__(self, owner, content):
        self.owner   = owner
        self.content = content
    def similarity_search(self, query, k=4):
        Doc = types.SimpleNamespace
        return [Doc(page_content=self.content)]

ALICE_SECRET = (
    "CONFIDENTIAL -- Patient: Alice Smith\n"
    "Diagnosis: Stage-2 hypertension. Prescribed lisinopril 10mg.\n"
    "SSN: 123-45-6789. Account balance: $84,320."
)

# ──────────────────────────────────────────────────────────────────────────────
# STEP 1 — VULNERABLE (before fix)
# ──────────────────────────────────────────────────────────────────────────────
print(SEP)
print("  STEP 1 — VULNERABLE CODE (before fix)")
print(SEP)

sessions_bug = {}

def bug_upload(owner_name, content):
    sid = str(uuid.uuid4())
    sessions_bug[sid] = {          # NO user_id stored
        "vectorstores": [FakeVectorStore(owner_name, content)],
        "last_accessed": time.time(),
    }
    return sid

def bug_ask(session_ids, question):
    docs = []
    for sid in session_ids:
        session = sessions_bug.get(sid)   # NO ownership check
        if session:
            for vs in session["vectorstores"]:
                docs.extend(vs.similarity_search(question))
    if not docs:
        return "No relevant context found."
    return "[MODEL ANSWER]:\n" + "\n".join(d.page_content for d in docs)

alice_sid = bug_upload("Alice", ALICE_SECRET)
bob_sid   = bug_upload("Bob",   "Bob's Q4 revenue report: $1M.")

print(f"\n  Alice session_id : {alice_sid}")
print(f"  Bob   session_id : {bob_sid}")
print(f"\n  Bob attacks: POST /ask  session_ids=[alice_sid]  (no auth token needed)")
print(DASH)
response = bug_ask([alice_sid], "What is the diagnosis and SSN?")
print("  SERVER RESPONSE (VULNERABLE):")
print(response)
print(DASH)
print("\n  [!] BUG: Bob received Alice's CONFIDENTIAL data with zero auth.\n")

# ──────────────────────────────────────────────────────────────────────────────
# STEP 2 — FIXED (after fix)
# ──────────────────────────────────────────────────────────────────────────────
print(SEP)
print("  STEP 2 — FIXED CODE (after fix)")
print(SEP)

sessions_fix = {}

class User:
    def __init__(self, uid, name, role="user"):
        self.id   = uid
        self.name = name
        self.role = role

ALICE = User(1, "Alice")
BOB   = User(2, "Bob")

def fix_upload(user, content):
    sid = str(uuid.uuid4())
    sessions_fix[sid] = {
        "vectorstores": [FakeVectorStore(user.name, content)],
        "last_accessed": time.time(),
        "user_id": user.id,          # FIX: ownership stored
    }
    return sid

class HTTP403(Exception):
    pass

def fix_ask(session_ids, question, current_user):
    docs = []
    for sid in session_ids:
        session = sessions_fix.get(sid)
        if session:
            # ── OWNERSHIP CHECK (the fix) ──────────────────────────────────
            if session["user_id"] != current_user.id and current_user.role != "admin":
                raise HTTP403(
                    f"403 Forbidden: session '{sid}' belongs to "
                    f"user_id={session['user_id']}, not user_id={current_user.id}."
                )
            # ──────────────────────────────────────────────────────────────
            session["last_accessed"] = time.time()
            for vs in session["vectorstores"]:
                docs.extend(vs.similarity_search(question))
    if not docs:
        return "No relevant context found."
    return "[MODEL ANSWER]:\n" + "\n".join(d.page_content for d in docs)

alice_sid2 = fix_upload(ALICE, ALICE_SECRET)
bob_sid2   = fix_upload(BOB,   "Bob's Q4 revenue report: $1M.")

print(f"\n  Alice session_id : {alice_sid2}")
print(f"  Bob   session_id : {bob_sid2}")

# Attack attempt
print(f"\n  Bob attacks: POST /ask  session_ids=[alice_sid]  (Bob's JWT, Alice's sid)")
print(DASH)
try:
    fix_ask([alice_sid2], "What is the diagnosis and SSN?", BOB)
    print("  ERROR: Should not reach here!")
except HTTP403 as e:
    print(f"  SERVER RESPONSE (FIXED):")
    print(f"  {e}")
print(DASH)
print("\n  [OK] FIXED: Bob's attack is BLOCKED. Alice's data is protected.\n")

# Bob accesses his own session (must still work)
print("  Bob accesses his OWN session (should succeed) ...")
print(DASH)
own = fix_ask([bob_sid2], "What is the revenue?", BOB)
print(f"  SERVER RESPONSE (Bob's own data):")
print(own)
print(DASH)
print("\n  [OK] Bob can still access his own documents normally.\n")

# ──────────────────────────────────────────────────────────────────────────────
print(SEP)
print("  CHANGES MADE IN rag-service/main.py")
print(SEP)
print("""
  /upload    +  current_user = Depends(AuthMiddleware.get_current_user)
               session["user_id"] = current_user.id   # <<< NEW

  /ask       +  current_user = Depends(AuthMiddleware.get_current_user)
               if session["user_id"] != current_user.id
                   and current_user.role != UserRole.ADMIN:
                   raise HTTP 403 Forbidden              # <<< NEW

  /summarize  — same ownership check as /ask             # <<< NEW
  /compare    — same ownership check as /ask             # <<< NEW
""")
print(SEP)
