import os
import subprocess
import sys


def test_database_password_fills_placeholder_url_encoded(tmp_path):
    env = dict(os.environ, CS2WP_DATA=str(tmp_path),
               CS2WP_DATABASE_URL="postgresql+psycopg://cs2wp:{password}@db:5432/cs2wp",
               CS2WP_DATABASE_PASSWORD="a$b/c@d")
    out = subprocess.run([sys.executable, "-c", "from cs2wp_core import config; print(config.DATABASE_URL)"],
                         env=env, capture_output=True, text=True, check=True).stdout.strip()
    assert out == "postgresql+psycopg://cs2wp:a%24b%2Fc%40d@db:5432/cs2wp"
