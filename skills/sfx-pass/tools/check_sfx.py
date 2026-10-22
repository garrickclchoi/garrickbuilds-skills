#!/usr/bin/env python3
"""
check_sfx.py — 用數字驗證每個音效真係聽得到。

點解要有呢個：cue sheet 睇落好靚，但混完之後有啲音效根本聽唔到 —— 人聲遮住咗、
duck 壓死咗、或者 gain 落得太細。淨係靠耳仔聽會走漏，尤其係口播片人聲幾乎冇停。
呢個 script 將「混音後」同「人聲原版」喺每個 cue 嘅時間窗做 RMS 相減，
用 dB 話你知邊個 cue 真係浮得出嚟。

判斷標準:
  >= +4dB   劇情關鍵 cue（轉場、reveal、punchline）—— 要去到呢度先算數
  +1~+3dB   氛圍質感 —— 咁樣就啱，唔使再推
  < +1dB    ⚠ 基本上聽唔到

⚠️ 量度窗要夠窄。0.6s 窗會將一個 50ms 嘅 click 溝到冇晒，
   隔籬一個大聲 cue 仲會漏入嚟造成假通過。所以短促音效用 0.3s，
   riser 呢類要量最尾三分一（佢啲能量喺尾段）。

用法:
  python3 tools/check_sfx.py sfx-plans/MyReel.json --mixed out/my_sfx.mp4
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 唔同 category 用唔同量度窗（秒）。短促嘅要窄，唔係會被溝淡。
WINDOW = {"snap": 0.30, "emphasis": 0.30, "foley": 0.40,
          "motion": 0.50, "reward": 0.60, "texture": 0.60}
TENSION_TAIL = 0.34  # riser 類：只量最尾 1/3


def rp(p):
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def rms_db(path, start, dur):
    """喺 [start, start+dur) 度量 RMS（dBFS）。靜音返 -inf。"""
    if start < 0:
        dur += start
        start = 0
    if dur <= 0:
        return float("-inf")
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-ss", "{:.3f}".format(start),
         "-t", "{:.3f}".format(dur), "-i", path, "-vn",
         "-af", "volumedetect", "-f", "null", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stdout)
    return float(m.group(1)) if m else float("-inf")


def integrated_lufs(path):
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn",
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    m = re.search(r"I:\s*(-?[\d.]+)\s*LUFS", r.stdout[-2500:])
    return float(m.group(1)) if m else None


def calibrate(plan, plan_path, voice, catalog):
    """計出呢條片應該用嘅 base_gain_db。

    品牌框架 §Effect 原則：音效音量 = 人聲 40-50%。
    40-50% 振幅 ≈ 人聲以下 6-8 dB，所以：
        目標音效響度 = 人聲 LUFS - 7
        base_gain_db = 目標 - 音效庫標準響度
    唔做呢步嘅話，所有 gain_db 都係對住一個錯嘅零點喺度調，點調都唔會啱。
    """
    target_lufs = catalog.get("target_lufs", -20.0)
    v = integrated_lufs(voice)
    if v is None:
        sys.exit("量唔到人聲響度：" + voice)
    base = round((v - 7.0) - target_lufs, 1)
    print("人聲版: {}".format(os.path.relpath(voice, ROOT)))
    print("  人聲整體響度      {:>7.1f} LUFS".format(v))
    print("  音效庫標準響度    {:>7.1f} LUFS".format(target_lufs))
    print("  差距              {:>+7.1f} dB {}".format(
        target_lufs - v, "(音效大聲過人聲！)" if target_lufs > v else ""))
    print("\n  品牌框架 §Effect：音效 = 人聲 40-50%（即人聲以下約 7dB）")
    print("  → base_gain_db = {:+.1f}".format(base))
    print("\n  落去 {}:".format(os.path.relpath(plan_path, ROOT)))
    print('    "base_gain_db": {},'.format(base))
    print("\n  之後每個 cue 嘅 gain_db 就係相對呢個基準：")
    print("    轉場 whoosh   -3 ~ 0      推進，唔搶")
    print("    字幕/reveal pop  0 ~ +3   跟住畫面彈")
    print("    hero 落點 stamp/impact  +3 ~ +7   全片得 2-3 個")
    print("    質感 texture   -6 ~ -3    聽唔真都冇所謂")


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        sys.exit("用法: python3 tools/check_sfx.py <plan.json> [--calibrate | --mixed <混音後.mp4>]")
    plan_path = rp(args[0])
    mixed = rp(args[args.index("--mixed") + 1]) if "--mixed" in args else None

    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)
    render = plan.get("render", {})
    voice = rp(render["preview"])
    mixed = mixed or rp(render["out"])
    offset = float(plan.get("offset_s", 0.0))

    with open(rp(plan.get("catalog", "public/sfx/catalog.json")), encoding="utf-8") as f:
        catalog = json.load(f)
    lib = {c["id"]: c for c in catalog["clips"]}

    if "--calibrate" in args:
        if not os.path.exists(voice):
            sys.exit("搵唔到人聲片源: " + voice)
        calibrate(plan, plan_path, voice, catalog)
        return

    for p in (voice, mixed):
        if not os.path.exists(p):
            sys.exit("搵唔到: " + p)

    cues = sorted((dict(e, mix_at=float(e["at_s"]) + offset) for e in plan["events"]),
                  key=lambda e: e["mix_at"])
    times = [c["mix_at"] for c in cues]

    print("人聲版: {}".format(os.path.relpath(voice, ROOT)))
    print("混音版: {}\n".format(os.path.relpath(mixed, ROOT)))
    print("  {:>8}  {:<22} {:>6} {:>7}  {:<6} {}".format(
        "mp4", "音效", "gain", "浮出", "判斷", "備註"))

    weak = []
    for i, c in enumerate(cues):
        clip = lib.get(c["sfx_id"])
        if not clip:
            print("  {:>7.2f}s  {:<22}  ⚠ 音效庫冇呢個 id".format(c["mix_at"], c["sfx_id"]))
            continue
        cat = clip.get("category", "misc")
        dur = float(clip.get("duration_s", 0.5))

        if cat == "tension":
            w = max(0.3, dur * TENSION_TAIL)
            start = c["mix_at"] + dur - w   # riser 量尾段
        else:
            w = min(WINDOW.get(cat, 0.5), max(dur, 0.2))
            start = c["mix_at"]

        v_rms = rms_db(voice, start, w)
        d = rms_db(mixed, start, w) - v_rms

        # 隔籬 cue 漏入量度窗 = 個數字信唔過
        near = [t for j, t in enumerate(times) if j != i and start - 0.05 < t < start + w]
        if near:
            note = "⚠ 有隔籬 cue 溝入窗，個數信唔過"
        elif v_rms < -45:
            # 落喺靜音位（人聲未開始 / 停頓）：加咩落去都係 +20dB 以上，
            # 呢個數唔代表「喺人聲之下浮唔浮到出」。要靠耳仔聽會唔會太搶。
            note = "（靜音位，個數冇參考值 — 用耳聽）"
        else:
            note = c.get("cue", "")[:30]

        if v_rms < -45:
            verdict = "— 靜音"
        elif d >= 4:
            verdict = "✅ 清晰"
        elif d >= 1:
            verdict = "◐ 質感"
        else:
            verdict = "❌ 聽唔到"
            weak.append(c)
        print("  {:>7.2f}s  {:<22} {:>4}dB {:>+6.1f}dB  {:<6} {}".format(
            c["mix_at"], c["sfx_id"], c.get("gain_db", 0), d, verdict, note))

    print()
    if weak:
        print("⚠ {} 個 cue 浮唔出：{}".format(
            len(weak), "、".join(w["sfx_id"] for w in weak)))
        print("  處理次序（唔好淨係推 gain）：")
        print("  1. 短促音效（click/pop/stamp）撞 peak 天花板，本身就細聲 3-5dB —— 加返 gain 係啱嘅。")
        print("  2. 完全埋喺連續人聲底下嘅 cue，推到 +9 都係同一個數（duck 一路壓住）。")
        print("     擺去字與字之間嘅空隙，或者索性刪咗佢。推 gain 只會令停頓位爆音。")
        print("  3. 如果覺得「嘈」，係要換聲嘅『性格』（換個乾淨啲嘅），唔係校細佢 ——")
        print("     沙沙聲/glitch 質感落喺人聲上面點校都係雜音。")
    else:
        print("✅ 全部 cue 都浮得出。")


if __name__ == "__main__":
    main()
