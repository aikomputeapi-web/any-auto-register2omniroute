#!/bin/sh
set -eu

APP_DIR="/app"
RUNTIME_DIR="${APP_RUNTIME_DIR:-/runtime}"
APP_LOG="${RUNTIME_DIR}/logs/app.log"

mkdir -p "${RUNTIME_DIR}" "${RUNTIME_DIR}/logs" "${RUNTIME_DIR}/smstome_used"
touch \
  "${RUNTIME_DIR}/account_manager.db" \
  "${RUNTIME_DIR}/smstome_all_numbers.txt" \
  "${RUNTIME_DIR}/smstome_uk_deep_numbers.txt" \
  "${RUNTIME_DIR}/logs/solver.log" \
  "${APP_LOG}"

ln -sfn "${RUNTIME_DIR}/account_manager.db" "${APP_DIR}/account_manager.db"
ln -sfn "${RUNTIME_DIR}/smstome_used" "${APP_DIR}/smstome_used"
ln -sfn "${RUNTIME_DIR}/smstome_all_numbers.txt" "${APP_DIR}/smstome_all_numbers.txt"
ln -sfn "${RUNTIME_DIR}/smstome_uk_deep_numbers.txt" "${APP_DIR}/smstome_uk_deep_numbers.txt"
ln -sfn "${RUNTIME_DIR}/logs/solver.log" "${APP_DIR}/services/turnstile_solver/solver.log"

echo "[entrypoint] Starting backend under Xvfb so Docker can handle both headed and headless browser tasks"

# The FastAPI app must NOT write directly to the container stdout pipe:
# some browser/solver startup output (camoufox/playwright banners) can
# trigger a BrokenPipe/I/O error that kills the process on cold boot when
# stdout is a pipe. Redirect app output to a logfile, then stream the
# logfile to stdout so `docker logs` still shows it, with signal
# forwarding.
xvfb-run -a --server-args="-screen 0 1920x1080x24" \
  python -u main.py >> "${APP_LOG}" 2>&1 &
APP_PID=$!

cleanup() {
  kill -TERM "${APP_PID}" 2>/dev/null || true
}
trap cleanup INT TERM

tail -n +1 -f "${APP_LOG}" --pid="${APP_PID}" 2>/dev/null &
TAIL_PID=$!

set +e
wait "${APP_PID}"
APP_EXIT=$?
set -e
kill "${TAIL_PID}" 2>/dev/null || true
exit "${APP_EXIT}"