#!/usr/bin/env bash
# Linux: run ./start-webui.sh in a terminal to start the local web UI (webui design 3.2).
# First sets up .venv with uv from the hash-pinned requirements.lock; a missing font is explained on the page.
cd "$(dirname "$0")" || exit 1
PYTHON=.venv/bin/python

fail() {
    echo "$1失败，原因见上面的报错。网络不稳时再运行一次即可，下载完的包不会重下。" >&2
    exit 1
}

if [ ! -f scripts/webui.py ]; then
    echo "找不到 scripts/webui.py：这个脚本要留在仓库文件夹里运行，不要单独拷走。" >&2
    exit 1
fi
# Ready: .venv has its interpreter and a copy of the requirements.lock it was installed from. The copy is written
# after a good install, so an interrupted install or a lock changed by git pull installs again.
if [ ! -x "$PYTHON" ] || ! cmp -s requirements.lock .venv/requirements.lock; then
    if ! command -v uv >/dev/null 2>&1; then
        echo "要先装 uv（只装一次），用它建 Python 环境。装法见官网：" >&2
        echo "  https://docs.astral.sh/uv/getting-started/installation/" >&2
        echo "装好后新开一个终端，再运行 ./start-webui.sh。" >&2
        exit 1
    fi
    if [ ! -x "$PYTHON" ]; then
        echo "用 uv 建 Python 环境（.venv）。第一次运行要联网下载约 280–390 MiB 的依赖，需要几分钟。"
        rm -rf .venv
        uv venv --python 3.12 .venv || fail "建环境（uv venv）"
    else
        echo ".venv 里装的和 requirements.lock 对不上（仓库更新过，或者上次没装完），重新按它装。"
    fi
    uv pip install --python "$PYTHON" --require-hashes -r requirements.lock || fail "装依赖（uv pip install）"
    cp requirements.lock .venv/requirements.lock || fail "记下装好的锁文件（cp）"
fi
exec "$PYTHON" -I -X utf8 -u scripts/webui.py "$@"
