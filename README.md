# wechat-mac-export

在 **自己的 Mac** 上，把 **自己的** 微信 4.x 本地聊天记录解密成可读文本，按联系人导出成 Markdown。全程本地运行，不联网、不上传。

An agent skill (and standalone CLI) to decrypt and export **your own** local WeChat 4.x
chat history on **your own** Mac. Runs fully locally — no network, no upload.

实测 / Tested: macOS 26.5 + 微信 4.1.13 / 4.1.15（Apple Silicon）。

---

## ⚠️ 使用边界 / Scope

- **仅限本人账号、本人电脑。** 不要在别人的电脑上运行，不要读取别人账号的聊天记录——
  未经授权读取他人通信属于侵犯个人信息，可能违法。
- **For your own account on your own machine only.** Reading someone else's
  communications without authorization may be illegal.
- 抓到的 `keys.json` 等于全部聊天记录的钥匙：不要外发、不要进 Git、不要上传。
- 方法是把微信复制一份并重签名（加调试权限）后抓密钥，**不改动原版微信**，但属于非官方
  用法，风险自担。
- 导出的聊天里包含别人说的话，按隐私材料对待。

## 安装 / Install

作为 agent skill（Claude Code / Codex / 任意支持 skills 的代理）：

```bash
npx skills add lashimao/wechat-mac-export
```

或手动把本仓库放到 `~/.agents/skills/wechat-mac-export`（或 `~/.claude/skills/`）。

依赖 / Dependencies：

```bash
xcode-select --install          # lldb
brew install sqlcipher zstd
```

## 用法 / Usage

下面 `$S` 指本仓库的 `scripts` 目录。

```bash
python3 $S/wx.py doctor                          # 自检：依赖、微信目录、密钥
bash     $S/resign_wechat.sh                     # 1. 复制并重签名微信（一次）
bash     $S/extract_keys.sh                      # 2. 抓密钥（首次 / 微信升级后；会重启微信，正常登录）
python3 $S/wx.py decrypt                         # 3. 解密（每次想看最新消息时）
python3 $S/wx.py list                            # 最近会话
python3 $S/wx.py find 张三                        # 搜联系人
python3 $S/wx.py export 张三 --since 2026-10-01   # 导出 Markdown
python3 $S/wx.py sns 张三                         # 朋友圈（本机缓存部分）
```

密钥、明文库、导出结果都在 `~/.wechat-export/`（权限 700），**不在仓库目录里**，所以分享本仓库
不会带出任何聊天数据。

详细步骤、能读/读不到什么、故障排查见 [`SKILL.md`](SKILL.md)。

## 原理 / How it works

微信 4.1 起数据库密钥不再明文驻留内存，只在打开数据库的一瞬间出现在 CPU 寄存器里。
本工具把微信复制一份并用 `get-task-allow` 重签名，用系统自带 `lldb` 在 CommonCrypto 的
`CCKeyDerivationPBKDF` / `CCCryptorCreate` / `CCHmacInit` 上布断点，抓下密钥，再用
SQLCipher（AES-256-CBC, HMAC-SHA512, PBKDF2）逐页解密。无需 sudo。

## 致谢 / Credits

- 取密钥部分基于 [huahan111/wechat-mac-reader](https://github.com/huahan111/wechat-mac-reader)（MIT）。
- 思路源自 [dylan121322/wxkey-hook](https://github.com/dylan121322/wxkey-hook)（MIT）与看雪社区的逆向研究。
- 本仓库改为私有目录存密钥、去掉固定路径，并重写了解密与导出（快照解密、zstd、引用回复、
  群聊发言人、会话列表、多账号识别、自检）。详见 [`NOTICE.md`](NOTICE.md)。

## License

MIT，见 [`LICENSE`](LICENSE)。
