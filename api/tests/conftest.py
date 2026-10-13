import os
import tempfile

# isolate every test run: local storage + SQLite under a throwaway folder, in-process bus
os.environ["CS2WP_DATA"] = tempfile.mkdtemp(prefix="cs2wp-test-")
os.environ.setdefault("CS2WP_STORAGE", "local")
os.environ["CS2WP_BUS"] = "inprocess"
os.environ.pop("CS2WP_DATABASE_URL", None)
os.environ["CS2WP_EMBEDDED_WORKERS"] = "0"
