cd /root/german-bot && \
find . -type f \( -name "*.py" -o -name "*.md" -o -name "*.txt" -o -name ".env*" \) \
  -not -path "./venv/*" \
  -not -path "./__pycache__/*" \
  -not -path "./.git/*" \
  -not -path "./audio_cache/*" \
  -not -path "./backups/*" \
  -not -name "*.db" \
  -not -name "all_project_files.txt" \
  -not -name ".env" \
  -not -name "*.csv" \
  -not -name "*.mp3" \
  -not -name "*.pyc" \
  | sort | while read f; do
    echo ""; echo "========== FILE: $f =========="; echo "";
    cat "$f";
  done > /root/german-bot/all_project_files.txt
