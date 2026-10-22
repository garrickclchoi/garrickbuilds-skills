---
name: sfx-pass
description: 短片音效對位（SFX pass）。當用戶想「加音效 / 落 sfx / 配音效 / 對聲效 / 轉場加聲 / sound design」，或者要寫 sfx-plan、校準音效響度、檢查音效聽唔聽得到、混音效落已 render 嘅片，就用呢個 skill。涵蓋響度校準、逐個 beat 對位、cue sheet 審閱、ffmpeg 混音同可聽度數字驗證。唔包括 BGM 配樂同視覺 effect。
license: MIT
---

# sfx-pass — 音效對位

喺乾淨版影片 render 好之後，加音效落去。**音效係 post-mix，畫面原封不動 copy**，所以改音效係幾秒鐘嘅事，可以放心試。

## 你需要準備
- **已 render 好嘅片**（人聲清楚、冇音效）。
- **音效庫（自備）**：呢個 skill **唔附帶任何音效檔**。請用你有權用嘅音效（自己生成、買、或者明確標示免費商用）。擺入 `public/sfx/`，然後行 `python3 tools/build_sfx_catalog.py` 做響度標準化同出 `catalog.json`。
- **工具**：Python 3、ffmpeg。`reverb_throw.sh` 另外要 SoX（`brew install sox`）。
- 將 `tools/` 同 `examples/` 放入你嘅 project 根目錄；所有路徑相對呢個根目錄。

## 建議嘅「功能 → 聲」對應（可按自己風格改）

| 畫面發生咩事 | 用咩聲 | catalog category |
|---|---|---|
| 卡／字彈入 | pop | `emphasis` |
| 卡接管畫面、轉場 | whoosh | `motion` |
| 關鍵詞落點 | ding | `reward` |
| 重擊、結論落槌 | 低頻 impact | `emphasis` |
| 拉緊、賣關子 | riser | `tension` |

**音效音量 ≈ 人聲 40–50%**（即 `base_gain_db` 嘅由來）。花巧轉場／glitch 類音效易變雜音，慎用。

## 流程

### 1. 校準（每條新片、或者換咗音源都要做）
```bash
python3 tools/check_sfx.py sfx-plans/MyReel.json --calibrate
```
計出 `base_gain_db` 填返落 plan。**唔好跳呢步**：人聲通常比音效庫細聲，唔校準嘅話音效預設會大聲過人聲。

### 2. 落 cue —— 按功能揀聲，唔係按感覺揀
逐個 beat 問：**呢度需要邊種功能？** 然後照上表揀。格式見 `examples/sfx-plan.example.json`（`at_s` 用片內時間，0 = 人聲第一個字）。
- 密度：短影音大約 **12–18 cue／分鐘**，多過就變吵。
- **只有 2–3 個 hero beat 疊聲**，其餘一個聲，中間留白。
- 可有可無嘅質感 cue 標 `"optional": true`。
- **靜音位係音效嘅朋友**：人聲停嗰陣落一個聲，好過喺人聲上面硬塞十個。

### 3. 審閱 cue sheet（強烈建議）
```bash
python3 tools/mix_sfx.py sfx-plans/MyReel.json --print
```
只印 cue sheet，唔 render。先睇過、有需要俾客人／拍檔過目，再混音。

### 4. 混音
```bash
python3 tools/mix_sfx.py sfx-plans/MyReel.json
```
自動做輕手 sidechain duck（人聲大聲嗰陣將音效壓低幾 dB）同 limiter 防爆。

### 5. 用數字驗證，唔好靠估
```bash
python3 tools/check_sfx.py sfx-plans/MyReel.json --mixed out/my_reel_sfx.mp4
```
將混音版同人聲版逐個 cue 做 RMS 相減：
- **≥ +4dB**：關鍵 cue 要去到呢度
- **+1~+3dB**：質感 cue 啱
- **< +1dB**：聽唔到，要處理

## 落 gain 參考（相對 `base_gain_db`）

| cue 類型 | gain_db |
|---|---|
| 轉場 whoosh | −3 ~ 0 |
| 字幕／卡彈入 pop | 0 ~ +3 |
| 關鍵詞 ding | 0 ~ +3 |
| hero 落點 stamp／impact | +3 ~ +7（全片 2–3 個）|
| 底層質感 texture | −6 ~ −3 |

## 收尾質感：reverb throw
```bash
tools/reverb_throw.sh IN.wav OUT.wav [THROW_SEC=0.7] [REVERB=78] [TAIL_PAD=4] [WET=1.0]
```
乾聲播到最後一嚿先 bloom 開一條 reverb 尾，做「呢度完咗」嘅收尾感。引擎係 SoX Freeverb＋ffmpeg（唔好用 ffmpeg 嘅 `afir`，喺部分 build 會出 silence）。係額外選項，唔係預設要用。

## 幾個一定會撞到嘅坑
1. **短促音效（click／pop／stamp）本身細聲 3–5dB**：標準化時會先撞 peak 天花板。佢哋嘅 `gain_db` 要比上表高 3–5dB，呢個係預期行為。
2. **完全埋喺連續人聲底下嘅 cue，推 gain 冇用**（sidechain duck 會壓住）。搬去字與字之間嘅空隙，或者刪咗佢。
3. **覺得「嘈」= 要換聲嘅性格，唔係校細佢**。沙沙聲／glitch 質感校到幾細都係雜音。
4. **量度窗要窄**：0.3s 窗量 click。`check_sfx.py` 會按 category 揀窗，並標示「有隔籬 cue 溝入窗」同「靜音位」——見到就唔好信個數，用耳聽。
5. **`offset_s` 用嚟食走時間軸差異**：render 出嚟嘅 mp4 前面多咗嘢，改 `offset_s` 就得，整張 cue 表唔使郁。

## 音效庫管理
- `public/sfx/*.mp3`：標準化到約 −20 LUFS / −1.5 dBFS peak。
- 加新音效：擺入 `public/sfx/`，行 `python3 tools/build_sfx_catalog.py`；改咗標準要全部重整，加 `--renorm`。
- **命名要通用**（`whoosh-short-sweep`、`pop-long`），唔好用片名。
- ⚠️ **授權自己負責**：記低每個音效嘅出處同 license。AI 生成嘅音效，請睇清楚該服務嘅商用條款。
