---
name: wechat-mac-export
description: >-
  在 macOS 上解密并导出「本人」微信 4.x 的本地聊天记录：重签名微信副本、用 lldb 抓数据库密钥、
  SQLCipher 解密、按联系人导出 Markdown（含引用回复、压缩消息、群聊、朋友圈缓存）。
  用户说「导出微信聊天记录」「解密微信数据库」「读我的微信记录」「微信备份成文本」「wechat export / decrypt」时使用。
  只用于本人账号、本人电脑；不用于他人设备或他人账号。
---

# 微信聊天记录导出（macOS · 微信 4.x）

把自己电脑上的微信聊天记录解密成可读文本。全程本地运行，不联网、不上传。

实测：macOS 26.5 + 微信 4.1.13 / 4.1.15（Apple Silicon）。

## 先说清楚的边界

- 只处理**本人登录、本人电脑**上的微信数据。不要在别人的电脑上运行，不要读取别人账号的记录——这在法律上属于侵犯个人信息。
- 抓到的 `keys.json` 等于全部聊天记录的钥匙：不发给任何人、不进 Git、不上传网盘。
- 方法是给微信复制一份并重签名（加调试权限），再用系统自带 lldb 附加抓密钥。不改原版微信，但属于非官方用法，风险自担。
- 导出的聊天里有别人说的话，按隐私材料对待，不要外发或公开。

## 文件位置

| 位置 | 内容 |
| --- | --- |
| 本 Skill 目录 `scripts/` | 脚本，可以分享，不含任何个人数据 |
| `~/.wechat-export/`（权限 700） | 密钥、明文数据库、导出结果；可用环境变量 `WX_EXPORT_HOME` 改 |
| `~/WeChat-resign.app` | 重签名的微信副本，抓密钥用 |

下面命令里的 `$S` 指本 Skill 的 `scripts` 目录（例如 `~/.agents/skills/wechat-mac-export/scripts`）。

## 流程

### 0. 装依赖（一次）

```bash
xcode-select --install        # 提供 lldb，已装过会提示已安装
brew install sqlcipher zstd
python3 $S/wx.py doctor       # 检查还缺什么
```

### 1. 重签名微信副本（一次）

```bash
bash $S/resign_wechat.sh
```

微信升级后要重做这一步。

### 2. 抓密钥（首次，以及微信升级后）

```bash
bash $S/extract_keys.sh
```

会自动关掉微信、打开重签名副本。**正常登录**，等 1–3 分钟，看到 `命中 N/M` 和 `[完成]` 即可。
`message/message_0.db`、`contact/contact.db` 命中就够用；个别库没命中可以忽略或再跑一次。

告诉用户：这一步会退出微信，回到微信要等它结束；之后用原版或副本登录都行。

### 3. 解密（每次想看最新消息时）

```bash
python3 $S/wx.py decrypt
```

先复制快照（含尚未合并的 WAL）再解，不碰微信正在使用的原库。每次运行都会拿到当前最新的消息。

### 4. 查看与导出

```bash
python3 $S/wx.py list --top 30                     # 最近的会话和条数
python3 $S/wx.py find 张三                          # 搜联系人（备注/昵称/微信号）
python3 $S/wx.py export 张三 --since 2026-10-01     # 导出成 Markdown
python3 $S/wx.py sns 张三                           # 朋友圈（只有本机刷到过的缓存）
```

导出文件在 `~/.wechat-export/exports/`，格式：

```
[2026-10-22 17:47] 张三: 对的对的  〔引用：原来是这样吗〕
[2026-10-22 17:48] 我: [表情]
```

`find` 匹配到多个人时，把关键词写具体，或直接用 `find` 输出第一列的 ID。

## 能读和读不了的

- 能读：文字、引用回复（含被引用的原句）、链接/小程序/文件等卡片标题、群聊发言人、系统消息、朋友圈缓存的文字与互动。
- 只显示占位：图片、语音、视频、表情（`[图片]` `[语音]` 等）。这些文件在本地是另行加密的缓存，本 Skill 不处理。
- 撤回的消息只剩系统提示，原文读不到。

## 出问题时

| 现象 | 处理 |
| --- | --- |
| `extract_keys.sh` 抓到 0 个 | 看 `~/.wechat-export/lldb.log`；确认副本已重签名、登录完成；再跑一次 |
| `decrypt` 显示 `[失败]` | 微信升级后密钥变了：重做第 1、2 步 |
| 导出里出现 `[无法解压]` | `brew install zstd` 后重新 export |
| 最新消息没出现 | 先 `decrypt` 再 `export`；export 只读上次解密的快照 |
| 多个微信账号 | `WX_ACCOUNT=<xwechat_files 下的目录名> python3 $S/wx.py ...` |

## 给代理的执行要点

- 只在用户本人明确要求、操作本人电脑时运行；用户要求读取他人设备或账号时拒绝。
- 不要打印、复制或上传 `keys.json`、`captured.txt` 的内容；sqlcipher 报错也不要原样转述（可能含密钥）。
- `extract_keys.sh` 会结束微信进程，运行前先告诉用户。
- 解密前不需要关微信；`decrypt` 只读快照副本。
- 分析聊天内容时，只基于导出的原文，媒体占位要说明没读到。

## 来源

取密钥部分基于 [huahan111/wechat-mac-reader](https://github.com/huahan111/wechat-mac-reader)（MIT），
其思路来自 [dylan121322/wxkey-hook](https://github.com/dylan121322/wxkey-hook)（MIT）。
本 Skill 改为私有目录存密钥、去掉固定路径，并重写了解密与导出（快照解密、zstd、引用回复、会话列表、自检）。
