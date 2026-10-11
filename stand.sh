#!/usr/bin/env bash
# Run one stand demo at a time: starting one stops the others, and the local
# LLM only runs while a chat game needs it, so the GPU and memory stay free.
#
#   ./stand.sh                       menu
#   ./stand.sh mirror|jailbreak|cloak|turing
#   ./stand.sh stop                  stop everything this script started
#   ./stand.sh status
#   ./stand.sh logs <demo|llm>       follow a log
#   ./stand.sh firewall [close]      let other PCs reach Human or Bot (WSL; asks for admin)
#
# The chat games need an LLM. By default this starts llama.cpp's llama-server
# locally (set LLAMA_SERVER and LLM_GGUF in .env if they aren't found). To use
# another server instead, like the Mac on the day: STAND_LLM=external, with
# LLM_URL set in .env.
#
# Other settings (environment or .env): STAND_OPEN=0 to not open the browser,
# CLOAK_CPU=1 to run the cloak on the CPU like a plain laptop would.

set -uo pipefail
cd "$(dirname "$0")"
RUN=.run
mkdir -p "$RUN"

if [ -f .env ]; then set -a; . ./.env; set +a; fi

DEMOS=(mirror jailbreak cloak turing)
declare -A NAME=([mirror]="AI Mirror" [jailbreak]="Jailbreak the Guardian" [cloak]="Invisibility Cloak" [turing]="Human or Bot?")
declare -A PORT=([mirror]=8765 [jailbreak]=8766 [turing]=8767 [cloak]=8768)
declare -A NEEDS_LLM=([jailbreak]=1 [turing]=1)

LLM_PORT=${LLM_PORT:-11435}
LLAMA_SERVER=${LLAMA_SERVER:-$(command -v llama-server || true)}
LLM_GGUF=${LLM_GGUF:-$(ls "$HOME"/.cache/huggingface/hub/models--unsloth--Qwen3.5-9B-GGUF/snapshots/*/Qwen3.5-9B-Q4_K_S.gguf 2>/dev/null | head -1)}
STAND_LLM=${STAND_LLM:-local}

bold=$'\e[1m'; dim=$'\e[2m'; green=$'\e[32m'; red=$'\e[31m'; yellow=$'\e[33m'; reset=$'\e[0m'

# ---------------------------------------------------------------- processes

pid_of() { cat "$RUN/$1.pid" 2>/dev/null; }
running() { local p; p=$(pid_of "$1") && [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
port_of() { cat "$RUN/$1.port" 2>/dev/null || echo "${PORT[$1]:-$LLM_PORT}"; }
port_busy() { ss -ltnH "sport = :$1" 2>/dev/null | grep -q .; }

free_port() {  # the demo's usual port, or the next free one if something else holds it
    local p=$1
    while port_busy "$p"; do p=$((p + 100)); done
    echo "$p"
}

start_bg() {  # name, command... -> runs in its own process group, logs to .run/<name>.log
    local name=$1; shift
    setsid nohup "$@" >"$RUN/$name.log" 2>&1 </dev/null &
    echo $! >"$RUN/$name.pid"
}

stop() {
    local name=$1 p
    running "$name" || { rm -f "$RUN/$name.pid" "$RUN/$name.port"; return 0; }
    p=$(pid_of "$name")
    kill -TERM -- "-$p" 2>/dev/null
    for _ in $(seq 20); do kill -0 "$p" 2>/dev/null || break; sleep 0.25; done
    kill -KILL -- "-$p" 2>/dev/null
    rm -f "$RUN/$name.pid" "$RUN/$name.port"
    echo "  ${dim}stopped ${NAME[$name]:-LLM server}${reset}"
}

wait_ready() {  # name, url, seconds
    local name=$1 url=$2 limit=$3 t=0
    printf "  waiting for %s " "${NAME[$name]:-LLM server}"
    until curl -sf -o /dev/null -m 2 "$url"; do
        if ! running "$name"; then
            echo "${red}failed${reset}"; echo "  last lines of $RUN/$name.log:"; tail -n 15 "$RUN/$name.log" | sed 's/^/    /'
            return 1
        fi
        if [ "$t" -ge "$limit" ]; then echo "${red}timed out${reset} (see $RUN/$name.log)"; return 1; fi
        printf "."; sleep 2; t=$((t + 2))
    done
    echo " ${green}ready${reset}"
}

open_url() {
    [ "${STAND_OPEN:-1}" = 0 ] && return
    local ok=1
    if command -v wslview >/dev/null; then wslview "$1" >/dev/null 2>&1 || ok=0
    elif command -v cmd.exe >/dev/null; then (cd /mnt/c 2>/dev/null; cmd.exe /c start "" "$1" >/dev/null 2>&1) || ok=0
    elif command -v xdg-open >/dev/null; then xdg-open "$1" >/dev/null 2>&1 || ok=0
    elif command -v open >/dev/null; then open "$1" || ok=0
    else ok=0
    fi
    if [ "$ok" = 0 ]; then
        echo "  ${yellow}couldn't open the browser from here: open the link above yourself${reset}"
        if [ -d /proc/sys/fs/binfmt_misc ] && [ ! -e /proc/sys/fs/binfmt_misc/WSLInterop ] && [ ! -e /proc/sys/fs/binfmt_misc/WSLInterop-late ]; then
            echo "  ${dim}(WSL can't start Windows programs right now. Fix: sudo sh -c 'echo :WSLInterop:M::MZ::/init:PF > /proc/sys/fs/binfmt_misc/register')${reset}"
        fi
    fi
}

lan_ip() {  # this machine's address on the local network (WSL mirrored mode shares the PC's)
    ip route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit }}'
}

firewall() {  # open (or close) the Human or Bot port in the Windows and Hyper-V firewalls
    command -v powershell.exe >/dev/null || { echo "  only needed on Windows/WSL"; return 1; }
    local dir=/mnt/c/Users/Public ports="${PORT[turing]}" flag=""
    [ "${1:-}" = close ] && flag="-Remove"
    cp tools/open-ports.ps1 "$dir/ai-stand-open-ports.ps1"
    printf '& "$PSScriptRoot\\ai-stand-open-ports.ps1" -Ports %s %s\nRead-Host "Done. Press Enter to close"\n' "$ports" "$flag" >"$dir/ai-stand-firewall.ps1"
    echo "  ${bold}Approve the Windows admin prompt${reset} (it only touches port $ports)…"
    (cd /mnt/c && powershell.exe -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File C:\Users\Public\ai-stand-firewall.ps1'") \
        || { echo "  ${red}cancelled or failed${reset}"; return 1; }
    local n
    n=$(cd /mnt/c && powershell.exe -NoProfile -Command "(Get-NetFirewallHyperVRule -Name 'AI Stand $ports' -ErrorAction SilentlyContinue | Measure-Object).Count" | tr -d '\r')
    if [ -z "$flag" ] && [ "$n" = 1 ]; then echo "  ${green}port $ports is open${reset}: other PCs can use http://$(lan_ip):$ports/human.html"
    elif [ -n "$flag" ] && [ "$n" = 0 ]; then echo "  ${green}port $ports is closed again${reset}"
    else echo "  ${red}the rule didn't change${reset}"; fi
}

# ---------------------------------------------------------------- the LLM

start_llm() {
    if [ "$STAND_LLM" = external ]; then
        echo "  using the LLM at ${LLM_URL:-http://localhost:11434} (STAND_LLM=external)"
        return 0
    fi
    export LLM_URL="http://localhost:$LLM_PORT"
    running llm && return 0
    if [ -z "$LLAMA_SERVER" ] || [ -z "$LLM_GGUF" ]; then
        echo "  ${red}No local LLM.${reset} Set LLAMA_SERVER (path to llama-server) and LLM_GGUF (a .gguf model) in .env,"
        echo "  or point LLM_URL at a running server and use STAND_LLM=external."
        return 1
    fi
    start_bg llm "$LLAMA_SERVER" -m "$LLM_GGUF" --alias "${LLM_MODEL:-qwen3.5:9b}" -ngl 99 -c 16384 \
        --parallel 4 --jinja --host 127.0.0.1 --port "$LLM_PORT"
    wait_ready llm "http://localhost:$LLM_PORT/health" 180
}

# ---------------------------------------------------------------- demos

stop_all() {
    for d in "${DEMOS[@]}"; do stop "$d"; done
    stop llm
}

launch() {
    local demo=$1 port url
    [ -n "${NAME[$demo]:-}" ] || { echo "unknown demo: $demo (pick one of: ${DEMOS[*]})"; return 1; }
    echo "${bold}${NAME[$demo]}${reset}"

    for d in "${DEMOS[@]}"; do [ "$d" != "$demo" ] && stop "$d"; done
    if [ -n "${NEEDS_LLM[$demo]:-}" ]; then start_llm || return 1; else stop llm; fi
    stop "$demo"  # restart it fresh

    port=$(free_port "${PORT[$demo]}")
    [ "$port" != "${PORT[$demo]}" ] && echo "  ${yellow}port ${PORT[$demo]} is taken by something else, using $port${reset}"
    echo "$port" >"$RUN/$demo.port"

    local extra=()
    [ "$demo" = cloak ] && [ "${CLOAK_CPU:-0}" = 1 ] && extra+=(--cpu)
    VIRTUAL_ENV= start_bg "$demo" uv run python "$demo/server.py" --port "$port" "${extra[@]}"

    local limit=60
    [ "$demo" = mirror ] && limit=600   # the first start compiles the model
    wait_ready "$demo" "http://localhost:$port/" "$limit" || return 1

    url="http://localhost:$port/"
    echo "  open ${bold}$url${reset}"
    open_url "$url"
    if [ "$demo" = turing ]; then
        echo "  human player, this PC:    ${bold}${url}human.html${reset}"
        echo "  human player, another PC: ${bold}http://$(lan_ip):$port/human.html${reset}  ${dim}(can't connect? ./stand.sh firewall)${reset}"
        open_url "${url}human.html"
    fi
    [ "$demo" = jailbreak ] && grep -m1 "Passwords" "$RUN/jailbreak.log" | sed "s/^/  ${dim}/; s/\$/${reset}/"
}

status() {
    for d in "${DEMOS[@]}"; do
        if running "$d"; then echo "  ${green}●${reset} ${NAME[$d]}  ${dim}http://localhost:$(port_of "$d")/${reset}"
        else echo "  ${dim}○ ${NAME[$d]}${reset}"; fi
    done
    if running llm; then echo "  ${green}●${reset} LLM server  ${dim}http://localhost:$LLM_PORT${reset}"
    else echo "  ${dim}○ LLM server${reset}"; fi
}

menu() {
    while true; do
        echo; echo "${bold}AI Stand${reset}"; status; echo
        echo "  1) AI Mirror   2) Jailbreak the Guardian   3) Invisibility Cloak   4) Human or Bot?"
        echo "  s) stop everything   q) quit (demos keep running)"
        read -rp "> " choice || break
        case "$choice" in
            1) launch mirror ;; 2) launch jailbreak ;; 3) launch cloak ;; 4) launch turing ;;
            s) stop_all ;; q|"") break ;; *) echo "pick 1-4, s or q" ;;
        esac
    done
}

case "${1:-menu}" in
    menu) menu ;;
    stop) stop_all ;;
    status) status ;;
    logs) tail -n 50 -f "$RUN/${2:-llm}.log" ;;
    firewall) firewall "${2:-open}" ;;
    *) launch "$1" ;;
esac
