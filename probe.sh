#!/usr/bin/env bash
# probe.sh - collect local facts you need for a skill's "On this machine" section.
# Read-only. Prints markdown-ready bullets. Works in MSYS/Git-Bash on Windows.
set -u

have() { command -v "$1" >/dev/null 2>&1; }
ver() { "$@" 2>&1 | head -1; }

echo "## On this machine"
echo
echo "### platform"
if have uname; then
  echo "- os: $(uname -s) $(uname -r) / $(uname -m)"
fi
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*) echo "- shell: MSYS-like bash on Windows (paths: /c/Users/... ; drive form C:/Users/...)" ;;
esac
echo "- home: $HOME"
echo "- cwd: $(pwd)"
echo

echo "### interpreters"
for c in python python3 py node npm pnpm bun deno git tar curl 7z ffmpeg ffprobe pdftotext
  do
  if have "$c"; then
    p=$(command -v "$c")
    warn=""
    # never EXECUTE a Store-stub alias: launching it opens the Microsoft Store page
    case "$p" in
      *WindowsApps*)
        warn="   <-- Microsoft Store stub, NOT a real interpreter (not executed)"
        v="not run" ;;
    esac
    if [ -z "${v:-}" ]; then
      case "$c" in
        python|python3) v=$(ver "$c" --version) ;;
        py)             v=$(ver py -3 --version) ;;
        *)              v=$(ver "$c" --version) ;;
      esac
    fi
    echo "- ${c}: ${p}  (${v})${warn}"
    unset v
  else
    echo "- ${c}: [ABSENT]"
  fi
done
echo

echo "### python packages worth knowing about"
PY=""
for c in python python3; do
  if have "$c"; then
    if "$c" -c "import sys;raise SystemExit(0 if sys.version_info>=(3,8) else 1)" 2>/dev/null; then PY="$c"; break; fi
  fi
done
if [ -n "$PY" ]; then
  "$PY" - <<'EOF' 2>/dev/null
import importlib.util as u
mods = ["pypdf","pdfminer","docx","pptx","openpyxl","lxml","PIL","requests",
        "fitz","pandas","numpy","bs4","yaml","ebooklib","markitdown","docling"]
print("- present: " + ", ".join(m for m in mods if u.find_spec(m)))
print("- absent : " + ", ".join(m for m in mods if not u.find_spec(m)))
EOF
else
  echo "- no usable python interpreter found"
fi
echo

echo "### credential env vars (names + length only, values never printed)"
env | grep -Ei '^(GH_TOKEN|GITHUB_TOKEN|[A-Z_]*API_KEY|[A-Z_]*TOKEN|[A-Z_]*SECRET|[A-Z_]*KEY)=' \
  | sed -E 's/=.*/=<set>/' | sort | sed 's/^/- /'
echo "- (if this list is empty, no key-style env vars are exported in this shell)"
echo

echo "### skill libraries"
for d in "$HOME/.agents/skills" "$HOME/.dsh/skills"; do
  if [ -d "$d" ]; then
    n=$(find "$d" -maxdepth 1 -mindepth 1 -type d | wc -l | tr -d ' ')
    echo "- ${d}: ${n} entries"
  else
    echo "- ${d}: [ABSENT]"
  fi
done
echo "- isolated venvs found:"
found=0
for v in "$HOME/.venvs"/*/. "$HOME"/.venv*/. ; do
  [ -x "${v}Scripts/python.exe" ] && { echo "    - ${v}"; found=1; }
  [ -x "${v}bin/python" ] && { echo "    - ${v}"; found=1; }
done
[ "$found" = 0 ] && echo "    - none"
echo

echo "### notes"
echo "- pip default index is slow/blocked on this host; use: -i https://pypi.tuna.tsinghua.edu.cn/simple"
echo "- prefer a per-skill venv inside the skill folder; never install into the system interpreter"