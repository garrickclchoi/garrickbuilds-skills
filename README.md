# garrickbuilds-skills

廣東話短片創作者用嘅 Claude Code skills。作者：Garrick（IG [@garrickbuilds](https://www.instagram.com/garrickbuilds/)）。

| Skill | 用途 |
|---|---|
| [`speak-human-hk`](skills/speak-human-hk) | 廣東話口播稿去 AI 味：拆走 AI 套話、書面語同翻譯腔；亦可將口述轉錄稿整理成節拍表。改編自 [speak-human-tw](https://github.com/Raymondhou0917/speak-human-tw)（Raymond Hou，MIT）。 |
| [`sfx-pass`](skills/sfx-pass) | 短片音效對位：校準響度 → 按功能落 cue → ffmpeg 混音 → 用數字驗證聽得到。**唔附音效檔**，請自備有授權嘅音效。 |

## 安裝（Claude Code）

```bash
git clone https://github.com/garrickclchoi/garrickbuilds-skills.git
cp -R garrickbuilds-skills/skills/speak-human-hk ~/.claude/skills/
cp -R garrickbuilds-skills/skills/sfx-pass ~/.claude/skills/
```

`sfx-pass` 嘅 `tools/` 同 `examples/` 要放入你自己嘅影片 project 根目錄，詳見 [SKILL.md](skills/sfx-pass/SKILL.md)。

## 授權
MIT。`speak-human-hk` 含改編自 speak-human-tw 嘅部分，原作者授權見 [`LICENSE-speak-human-tw`](skills/speak-human-hk/LICENSE-speak-human-tw)。

本 repo 同所提及嘅第三方工具冇官方關係。
