#!/usr/bin/env python3
"""
wx.py — 本机微信 4.x（macOS）聊天记录解密与导出。密钥由 extract_keys.sh 抓取。

  python3 wx.py doctor                          # 检查依赖、微信目录、密钥是否就绪
  python3 wx.py decrypt                         # 复制 DB+WAL 快照并解成明文（含最新未合并消息）
  python3 wx.py list [--top 30]                 # 按最近聊天时间列出会话和条数
  python3 wx.py find 张三                        # 按备注/昵称/微信号搜联系人
  python3 wx.py export 张三 [--since 2026-10-01] [--out 目录]
  python3 wx.py sns 张三|我                      # 朋友圈：只有本机刷到过的缓存

所有密钥、明文库和导出文件都在私有数据目录（默认 ~/.wechat-export，可用 WX_EXPORT_HOME 改），
不放进 Skill 目录，分享 Skill 不会带出任何聊天数据。只用于本人账号、本人电脑。
"""
import argparse, datetime, glob, hashlib, hmac, html, json, os, re, shutil, sqlite3, struct, subprocess, sys

BASE = os.path.expanduser("~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files")
DATA = os.path.expanduser(os.environ.get("WX_EXPORT_HOME", "~/.wechat-export"))
KEYS = os.environ.get("WX_KEYS") or os.path.join(DATA, "keys.json")
WORK = os.path.join(DATA, ".work")
PLAIN = os.path.join(WORK, "plain")
EXPORTS = os.path.join(DATA, "exports")
TYPES = {3: "[图片]", 34: "[语音]", 43: "[视频]", 47: "[表情]", 42: "[名片]", 48: "[位置]",
         50: "[通话]", 10000: "[系统消息]", 10002: "[撤回]"}


def _key_fits(key_hex, db_path):
    """用 SQLCipher 4 的首页 HMAC 验证密钥是否属于这个库（与 match_keys.py 同一算法）。"""
    try:
        page = open(db_path, "rb").read(4096)
    except OSError:
        return False
    if len(page) < 4096:
        return False
    mac_key = hashlib.pbkdf2_hmac("sha512", bytes.fromhex(key_hex), bytes(b ^ 0x3A for b in page[:16]), 2, dklen=32)
    h = hmac.new(mac_key, page[16:4032], hashlib.sha512)
    h.update(struct.pack("<I", 1))
    return h.digest() == page[4032:4096]


def account_dir():
    """同一台 Mac 可能登录过多个账号：取密钥能验证通过的那个；WX_ACCOUNT 可手动指定目录名。"""
    want = os.environ.get("WX_ACCOUNT")
    dirs = glob.glob(os.path.join(BASE, "*", "db_storage"))
    if want:
        dirs = [d for d in dirs if os.path.basename(os.path.dirname(d)) == want]
    if not dirs:
        sys.exit(f"[错误] 找不到微信数据目录 {BASE}（微信 4.x 登录过一次才会生成）")
    if os.path.exists(KEYS):
        key = json.load(open(KEYS)).get("contact/contact.db")
        fits = [d for d in dirs if key and _key_fits(key, os.path.join(d, "contact", "contact.db"))]
        if fits:
            return fits[0]
    return max(dirs, key=os.path.getmtime)


def me():
    # 账号目录名形如 <微信内部ID>_<4位后缀>
    return os.path.basename(os.path.dirname(account_dir())).rsplit("_", 1)[0]


def sqlcipher():
    path = shutil.which("sqlcipher")
    if not path and shutil.which("brew"):
        prefix = subprocess.run(["brew", "--prefix", "sqlcipher"], capture_output=True, text=True).stdout.strip()
        cand = os.path.join(prefix, "bin", "sqlcipher")
        path = cand if os.path.exists(cand) else None
    return path


def unzstd(blob):
    """4.x 部分消息用 zstd 压缩：优先用 Python 模块，没有就用 zstd 命令行。"""
    try:
        import zstandard
        return zstandard.ZstdDecompressor().decompress(blob, max_output_size=1 << 24).decode("utf-8", "replace")
    except ImportError:
        pass
    except Exception:
        return None
    if shutil.which("zstd"):
        r = subprocess.run(["zstd", "-dc"], input=blob, capture_output=True)
        if r.returncode == 0:
            return r.stdout.decode("utf-8", "replace")
    return None


def doctor():
    ok = True
    for name, found, fix in [
        ("sqlcipher", sqlcipher(), "brew install sqlcipher"),
        ("lldb", shutil.which("lldb"), "xcode-select --install"),
        ("zstd", shutil.which("zstd") or _has("zstandard"), "brew install zstd"),
    ]:
        print(f"{'[OK]' if found else '[缺]'} {name}" + ("" if found else f"  → {fix}"))
        ok &= bool(found)
    app = "/Applications/WeChat.app/Contents/Info.plist"
    if os.path.exists(app):
        v = subprocess.run(["defaults", "read", app.removesuffix(".plist"), "CFBundleShortVersionString"],
                           capture_output=True, text=True).stdout.strip()
        print(f"[OK] 微信 {v}")
    else:
        print("[缺] /Applications/WeChat.app"); ok = False
    print(f"[{'OK' if os.path.isdir(os.path.expanduser('~/WeChat-resign.app')) else '缺'}] 重签名副本 ~/WeChat-resign.app"
          "（缺就运行 resign_wechat.sh）")
    print(f"[OK] 账号目录 {os.path.basename(os.path.dirname(account_dir()))}")
    if os.path.exists(KEYS):
        print(f"[OK] 密钥 {len(json.load(open(KEYS)))} 个：{KEYS}")
    else:
        print(f"[缺] 密钥 {KEYS}（运行 extract_keys.sh）"); ok = False
    print("全部就绪" if ok else "按上面提示补齐后再继续")


def _has(mod):
    try:
        __import__(mod); return True
    except ImportError:
        return False


def decrypt():
    if not os.path.exists(KEYS):
        sys.exit(f"[错误] 没有密钥 {KEYS}，先运行 extract_keys.sh")
    cipher = sqlcipher()
    if not cipher:
        sys.exit("[错误] 没装 sqlcipher：brew install sqlcipher")
    keys = json.load(open(KEYS))
    src_root = account_dir()
    os.makedirs(PLAIN, mode=0o700, exist_ok=True)
    os.chmod(DATA, 0o700)
    wanted = [r for r in keys if r in ("contact/contact.db", "session/session.db", "sns/sns.db")
              or re.fullmatch(r"message/message_\d+\.db", r)]
    for rel in sorted(wanted):
        src = os.path.join(src_root, rel)
        if not os.path.exists(src):
            continue
        snap = os.path.join(WORK, "snap", rel.replace("/", "_"))
        dst = os.path.join(PLAIN, rel.replace("/", "_"))
        os.makedirs(os.path.dirname(snap), mode=0o700, exist_ok=True)
        # 复制快照（连同 WAL）再解，不碰微信正在用的原库
        for suf in ("", "-wal", "-shm"):
            if os.path.exists(snap + suf):
                os.remove(snap + suf)
            if os.path.exists(src + suf):
                shutil.copy2(src + suf, snap + suf)
        if os.path.exists(dst):
            os.remove(dst)
        salt = open(snap, "rb").read(16).hex()
        sql = (f"PRAGMA key = \"x'{keys[rel]}{salt}'\";\n"
               "PRAGMA cipher_page_size=4096; PRAGMA cipher_hmac_algorithm=HMAC_SHA512;\n"
               "PRAGMA cipher_kdf_algorithm=PBKDF2_HMAC_SHA512;\n"
               f"ATTACH DATABASE '{dst}' AS plain KEY '';\n"
               "SELECT sqlcipher_export('plain');\nDETACH DATABASE plain;\n")
        r = subprocess.run([cipher, snap], input=sql, capture_output=True, text=True)
        ok = os.path.exists(dst) and not r.stderr.strip()
        if ok:
            ok = sqlite3.connect(dst).execute("PRAGMA quick_check(1)").fetchone()[0] == "ok"
        # 不打印 sqlcipher 原始报错，里面可能带密钥
        print(f"{'[OK]' if ok else '[失败]'} {rel}" + ("" if ok else "（微信升级后密钥会变，重跑 extract_keys.sh）"))
        for suf in ("", "-wal", "-shm"):
            if os.path.exists(snap + suf):
                os.remove(snap + suf)


def _need_plain():
    if not os.path.exists(os.path.join(PLAIN, "contact_contact.db")):
        sys.exit("[错误] 还没有明文库，先运行: python3 wx.py decrypt")


def contacts():
    _need_plain()
    c = sqlite3.connect(os.path.join(PLAIN, "contact_contact.db"))
    rows = c.execute("SELECT username, alias, remark, nick_name FROM contact").fetchall()
    c.close()
    return rows


def find(word):
    hits = [r for r in contacts() if any(word in (x or "") for x in r)]
    for u, a, rm, n in hits:
        print(f"{u}\t备注={rm or '-'}\t昵称={n or '-'}\t微信号={a or '-'}")
    return hits


def list_sessions(top):
    names = {u: (rm or n or u) for u, _, rm, n in contacts()}
    by_table = {"Msg_" + hashlib.md5(u.encode()).hexdigest(): u for u in names}
    stats = {}
    for db in sorted(glob.glob(os.path.join(PLAIN, "message_message_*.db"))):
        conn = sqlite3.connect(db)
        for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"):
            if t not in by_table:
                continue
            n, last = conn.execute(f"SELECT count(*), max(create_time) FROM {t}").fetchone()
            old = stats.get(t, (0, 0))
            stats[t] = (old[0] + n, max(old[1], last or 0))
        conn.close()
    for t, (n, last) in sorted(stats.items(), key=lambda x: -x[1][1])[:top]:
        print(f"{datetime.datetime.fromtimestamp(last):%Y-%m-%d %H:%M}\t{n}条\t{names[by_table[t]]}")


def clean(c, is_group):
    if isinstance(c, bytes):
        c = unzstd(c)
        if c is None:
            return "[无法解压：brew install zstd]"
    c = c or ""
    if is_group:
        m = re.match(r"^[\w-]+:\n(.*)$", c, re.S)
        c = m.group(1) if m else c
    if "<msg" in c[:200] or c.startswith("<?xml"):
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", c, re.S)
        text = html.unescape(t.group(1).strip()[:200]) if t else ""
        ref = re.search(r"<refermsg>(.*?)</refermsg>", c, re.S)
        if ref:  # 引用回复：正文 + 被引用的那句
            quoted = re.search(r"<content>(.*?)</content>", ref.group(1), re.S)
            q = html.unescape(quoted.group(1)).strip() if quoted else ""
            q = re.sub(r"<[^>]+>", "", q)[:80] if not q.startswith("<") else "[非文字消息]"
            return f"{text}  〔引用：{q}〕"
        return f"[卡片] {text}" if text else "[XML消息]"
    return c.strip()


def resolve(word):
    hits = find(word)
    if len(hits) != 1:
        sys.exit(f"匹配到 {len(hits)} 个联系人，请把关键词写具体（可直接用上面第一列的 ID）")
    return hits[0]


def export(word, since=None, out=None):
    user, _, remark, nick = resolve(word)
    names = {u: (rm or n or u) for u, _, rm, n in contacts()}
    my = me()
    table = "Msg_" + hashlib.md5(user.encode()).hexdigest()
    start = int(datetime.datetime.strptime(since, "%Y-%m-%d").timestamp()) if since else 0
    msgs = []
    for db in sorted(glob.glob(os.path.join(PLAIN, "message_message_*.db"))):
        conn = sqlite3.connect(db)
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            conn.close(); continue
        id2u = dict(conn.execute("SELECT rowid, user_name FROM Name2Id"))
        for lt, sid, ts, seq, c in conn.execute(
                f"SELECT local_type, real_sender_id, create_time, sort_seq, message_content FROM {table} "
                "WHERE create_time >= ?", (start,)):
            base = lt & 0xFFFFFFFF
            sender = id2u.get(sid, "")
            who = "我" if sender == my else names.get(sender, sender or "?")
            if base in (1, 49):
                txt = clean(c, user.endswith("@chatroom")) or "[空]"
            else:
                txt = TYPES.get(base, f"[类型{base}]")
            msgs.append((seq, ts, who, txt))
        conn.close()
    msgs.sort()
    label = re.sub(r'[\\/:*?"<>|\s]+', "_", remark or nick or user)
    out = out or EXPORTS
    os.makedirs(out, mode=0o700, exist_ok=True)
    path = os.path.join(out, f"{label}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {remark or nick}（{nick}）\n\n")
        for _, ts, who, txt in msgs:
            f.write(f"[{datetime.datetime.fromtimestamp(ts):%Y-%m-%d %H:%M}] {who}: {txt}\n")
    os.chmod(path, 0o600)
    if msgs:
        first = datetime.datetime.fromtimestamp(msgs[0][1]); last = datetime.datetime.fromtimestamp(msgs[-1][1])
        print(f"[OK] {path}\n共 {len(msgs)} 条，最早 {first:%Y-%m-%d %H:%M}，最晚 {last:%Y-%m-%d %H:%M}")
    else:
        print("[空] 没有消息")


def sns(word, since=None, out=None):
    """导出某人朋友圈（只有本机微信刷到过、缓存下来的那部分）。word 写“我”导出自己的。"""
    if word == "我":
        user, label = me(), "我"
    else:
        user, _, remark, nick = resolve(word)
        label = remark or nick or user
    start = int(datetime.datetime.strptime(since, "%Y-%m-%d").timestamp()) if since else 0
    conn = sqlite3.connect(os.path.join(PLAIN, "sns_sns.db"))
    posts = []
    for tid, xml in conn.execute("SELECT tid, content FROM SnsTimeLine WHERE user_name=?", (user,)):
        tag = lambda t: (re.search(rf"<{t}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{t}>", xml, re.S) or [None, ""])[1]
        ts = int(tag("createTime") or 0)
        if ts < start:
            continue
        kind = {"1": "图片", "7": "图片", "15": "视频", "54": "视频", "3": "链接", "2": "文字",
                "5": "视频号", "28": "视频号"}.get(tag("type"), "类型" + tag("type"))
        media = len(re.findall(r"<media>", xml))
        place = re.search(r'<location [^>]*poiName="([^"]*)"', xml)
        link = tag("title") if kind in ("链接", "视频号") else ""
        inter = conn.execute("SELECT type, from_nickname, content FROM SnsMessage_tmp3 WHERE feed_id=? "
                             "ORDER BY create_time", (tid,)).fetchall()
        posts.append((ts, tag("contentDesc").strip(), kind, media, place.group(1) if place else "", link, inter))
    conn.close()
    posts.sort()
    out = out or EXPORTS
    os.makedirs(out, mode=0o700, exist_ok=True)
    path = os.path.join(out, re.sub(r'[\\/:*?"<>|\s]+', "_", label) + "_朋友圈.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {label} 的朋友圈（本机缓存）\n\n")
        for ts, text, kind, media, place, link, inter in posts:
            f.write(f"## {datetime.datetime.fromtimestamp(ts):%Y-%m-%d %H:%M}\n\n")
            if text:
                f.write(text + "\n\n")
            extra = [f"[{kind}×{media}]" if media else f"[{kind}]"]
            if link:
                extra.append(f"链接：{link}")
            if place:
                extra.append(f"位置：{place}")
            f.write(" ".join(extra) + "\n\n")
            for t, who, c in inter:
                f.write(f"- {who}：{'赞' if t == 1 else c}\n")
            if inter:
                f.write("\n")
    os.chmod(path, 0o600)
    if posts:
        print(f"[OK] {path}\n共 {len(posts)} 条，最早 {datetime.datetime.fromtimestamp(posts[0][0]):%Y-%m-%d}，"
              f"最晚 {datetime.datetime.fromtimestamp(posts[-1][0]):%Y-%m-%d}")
    else:
        print("[空] 本机没有缓存这个人的朋友圈（在微信里点开过他的朋友圈后再 decrypt 一次）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="本机微信 4.x 聊天记录解密与导出（仅限本人账号）")
    ap.add_argument("cmd", choices=["doctor", "decrypt", "list", "find", "export", "sns"])
    ap.add_argument("word", nargs="?")
    ap.add_argument("--since", help="只导出该日期之后，格式 2026-10-01")
    ap.add_argument("--out", help="导出目录，默认 ~/.wechat-export/exports")
    ap.add_argument("--top", type=int, default=30, help="list 显示多少个会话")
    a = ap.parse_args()
    if a.cmd in ("find", "export", "sns") and not a.word:
        ap.error(f"{a.cmd} 需要一个联系人关键词")
    {"doctor": doctor, "decrypt": decrypt, "list": lambda: list_sessions(a.top), "find": lambda: find(a.word),
     "export": lambda: export(a.word, a.since, a.out), "sns": lambda: sns(a.word, a.since, a.out)}[a.cmd]()
