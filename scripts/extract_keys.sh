#!/bin/bash
# extract_keys.sh — 抓取本机微信数据库密钥（无需 sudo）
# 用法: bash extract_keys.sh
# 前提: 已运行 resign_wechat.sh 生成了 ~/WeChat-resign.app
# 密钥和中间文件只写进私有数据目录（默认 ~/.wechat-export，可用 WX_EXPORT_HOME 改），不写进 Skill 目录。
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="${WX_EXPORT_HOME:-$HOME/.wechat-export}"
mkdir -p "$DATA"; chmod 700 "$DATA"
export WX_CAPTURED="$DATA/captured.txt"
KEYS="$DATA/keys.json"
APP="$HOME/WeChat-resign.app"
WAIT_SECONDS=180
CMDS="$DATA/lldb.cmds"
LOG="$DATA/lldb.log"

if [ ! -d "$APP" ]; then
    echo "[错误] 找不到 $APP，请先运行: bash resign_wechat.sh"; exit 1
fi

killall WeChat 2>/dev/null
sleep 2
: > "$WX_CAPTURED"; chmod 600 "$WX_CAPTURED"

cat > "$CMDS" <<CMDS
command script import $SCRIPT_DIR/hook_keys.py
break set -n CCCryptorCreate
break command add -F hook_keys.cryptor_bp
break set -n CCKeyDerivationPBKDF
break command add -F hook_keys.pbkdf_bp
break set -n CCHmacInit
break command add -F hook_keys.hmac_bp
continue
CMDS

echo "[*] 启动 lldb 等待附加..."
nohup lldb -b -o "process attach --name WeChat --waitfor" -s "$CMDS" > "$LOG" 2>&1 &
LLDB_PID=$!
sleep 4

echo "[*] 启动微信副本: $APP （请正常登录）"
open "$APP"

echo "[*] 抓取中（最多 ${WAIT_SECONDS} 秒，登录后自动完成）..."
for i in $(seq 1 $((WAIT_SECONDS / 5))); do
    sleep 5
    N=$(grep -c AESKEY "$WX_CAPTURED" 2>/dev/null || echo 0)
    kill -0 $LLDB_PID 2>/dev/null || break
    echo "    已捕捉候选密钥: $N"
done
kill $LLDB_PID 2>/dev/null

if [ ! -s "$WX_CAPTURED" ]; then
    echo "[失败] 没抓到任何密钥，排查日志: $LOG"; exit 1
fi

echo "[*] 用 HMAC 逐库验证并配对 ..."
python3 "$SCRIPT_DIR/match_keys.py" "$WX_CAPTURED" "$KEYS"
rm -f "$WX_CAPTURED" "$CMDS"

echo
echo "[完成] 密钥已保存到 $KEYS（权限 600，等同于全部聊天记录的钥匙，切勿外传）"
echo "下一步: python3 $SCRIPT_DIR/wx.py decrypt"
