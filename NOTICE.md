# 第三方来源

- scripts/resign_wechat.sh、scripts/match_keys.py、scripts/debug.entitlements：原样取自 huahan111/wechat-mac-reader（MIT，见 LICENSE）。
- scripts/hook_keys.py、scripts/extract_keys.sh：改写自同一项目，改为把候选密钥写入私有目录 ~/.wechat-export，不再写死路径。
- 上游思路来自 dylan121322/wxkey-hook（MIT）。
- scripts/wx.py：本 Skill 自写。
