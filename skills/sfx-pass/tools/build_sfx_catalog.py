#!/usr/bin/env python3
"""
build_sfx_catalog.py — 掃描 public/sfx/，做響度標準化，寫 catalog.json。

點解要標準化：sfx-plan.json 入面每個 cue 嘅 gain_db 係「相對 clip 標準音量」。
如果啲 clip 本身大細聲差 10dB，gain_db 就完全冇意義，你調極都調唔準。
全部拉到 -20 LUFS / -1.5 dBFS peak ceiling 之後，gain_db 先係可以跨片重用嘅數字。

⚠️ 短促音效（click / pop / stamp）會先撞到 -1.5 dBFS peak 天花板，
   先至去到 -20 LUFS，所以佢哋 catalog 出嚟會比長音效細聲 3-5dB。
   呢個係預期行為 —— 落 plan 時佢哋嘅 gain_db 要比 sustained 音效高 3-5dB。

用法:
  python3 tools/build_sfx_catalog.py            # 標準化未處理嘅 + 寫 catalog
  python3 tools/build_sfx_catalog.py --dry-run  # 只量度，唔改檔
  python3 tools/build_sfx_catalog.py --renorm   # 全部重新標準化（改咗 target 時用）
"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SFX_DIR = os.path.join(ROOT, "public", "sfx")
CATALOG = os.path.join(SFX_DIR, "catalog.json")

TARGET_LUFS = -20.0
PEAK_CEILING_DBFS = -1.5

# 由檔名推 category + tags。改名唔使改 code，改呢度就得。
# category 係「呢個聲做咩用」，落 plan 時揀聲用 function 揀，唔係用感覺揀：
#   motion(推進) / tension(拉緊) / emphasis(重點) / snap(乾脆) / reward(獎勵) / foley(實物) / texture(氛圍)
RULES = [
    (r"^vine-boom|^bonk", "emphasis", ["impact", "hit", "重擊", "meme", "boom"]),
    (r"punch", "emphasis", ["impact", "hit", "punch", "重擊"]),
    (r"^error", "emphasis", ["error", "警示", "buzz", "wrong"]),
    (r"^record-scratch", "emphasis", ["scratch", "急停", "反轉", "meme"]),
    (r"^sad-violin", "foley", ["violin", "sad", "自嘲", "meme"]),
    (r"^slide-whistle|^sad-trombone", "foley", ["cartoon", "卡通", "自嘲", "meme"]),
    (r"^dramatic-violin", "tension", ["sting", "懸疑", "賣關子", "meme"]),
    (r"^camera-shutter", "snap", ["shutter", "咔", "相機"]),
    (r"^whoosh|^swoosh|whoosh", "motion", ["whoosh", "transition", "轉場", "推進"]),
    (r"^riser|riser|swell", "tension", ["riser", "build", "拉緊", "期待"]),
    (r"^scan|hum", "tension", ["hum", "sweep", "懸疑"]),
    (r"^impact|^launch|thump|stamp", "emphasis", ["impact", "hit", "重擊", "落點"]),
    (r"^pop", "emphasis", ["pop", "reveal", "彈出", "現身"]),
    (r"^click", "snap", ["ui", "click", "咔", "乾脆"]),
    (r"^ding|^chime|reward", "reward", ["chime", "positive", "叮", "正面"]),
    (r"sparkle|shimmer|magic", "reward", ["sparkle", "shimmer", "閃", "溫暖"]),
    (r"^page|^knock|^keys|pencil|chess", "foley", ["foley", "實物"]),
    (r"^clock|^wind|^stream|tick", "texture", ["texture", "氛圍", "底噪"]),
]


def classify(stem):
    for pat, cat, tags in RULES:
        if re.search(pat, stem):
            extra = [t for t in stem.split("-") if t not in tags]
            return cat, tags + extra
    return "misc", stem.split("-")


def ff(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        sys.stderr.write("\nFFMPEG FAILED:\n  " + " ".join(cmd) + "\n" + r.stdout[-3000:] + "\n")
        raise SystemExit(1)
    return r.stdout


def measure(path):
    """返回 (duration_s, integrated_lufs, true_peak_dbfs)。

    ⚠️ ebur128 嘅 integrated loudness 要夠長先量得準：短過 ~3s 嘅 clip 會直接
    報 -70 LUFS（絕對 gate 嘅底）。音效庫入面大部分都係 0.2-2s，所以量之前
    要用 apad 補靜音。靜音會被 gating 濾走，唔會拉低個值，但夠長俾 gating 行得到。
    唔補嘅話所有短音效都會報 -70，變成淨係做 peak normalize —— 咁 gain_db 就
    再次唔可比（呢個 bug 第一版真係中過）。
    """
    dur = float(ff(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1", path]).strip())
    out = ff(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
              "-af", "apad=pad_dur=4,ebur128=peak=true", "-f", "null", "-"])
    # ebur128 summary 喺最尾：I: -23.4 LUFS / Peak: -1.2 dBFS
    lufs = peak = None
    tail = out[-2500:]
    m = re.search(r"I:\s*(-?[\d.]+|-inf)\s*LUFS", tail)
    if m:
        lufs = float("-inf") if m.group(1) == "-inf" else float(m.group(1))
    peaks = re.findall(r"Peak:\s*(-?[\d.]+|-inf)\s*dBFS", tail)
    if peaks:
        vals = [float("-inf") if p == "-inf" else float(p) for p in peaks]
        peak = max(vals)
    return dur, lufs, peak


def normalize(path, lufs, peak):
    """一次性線性增益：拉到 -20 LUFS，但唔准超過 -1.5 dBFS peak。
    對短促音效，peak 條線會先夾住 —— 呢個係故意嘅，唔壓縮就唔會整死 transient。"""
    if lufs is None or lufs == float("-inf") or peak is None or peak == float("-inf"):
        return None
    gain = min(TARGET_LUFS - lufs, PEAK_CEILING_DBFS - peak)
    if abs(gain) < 0.05:
        return 0.0
    tmp = path + ".norm.mp3"
    ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", path,
        "-af", "volume={:.2f}dB".format(gain), "-c:a", "libmp3lame", "-b:a", "192k", tmp])
    shutil.move(tmp, path)
    return gain


def main():
    dry = "--dry-run" in sys.argv
    renorm = "--renorm" in sys.argv

    old = {}
    if os.path.exists(CATALOG):
        with open(CATALOG, encoding="utf-8") as f:
            old = {c["id"]: c for c in json.load(f).get("clips", [])}

    files = sorted(f for f in os.listdir(SFX_DIR) if f.lower().endswith((".mp3", ".wav", ".m4a")))
    clips = []
    print("{:<26} {:>7} {:>9} {:>8}  {}".format("id", "dur", "LUFS", "peak", "動作"))
    for fn in files:
        path = os.path.join(SFX_DIR, fn)
        stem = os.path.splitext(fn)[0]
        prev = old.get(stem)
        dur, lufs, peak = measure(path)

        action = "已標準化"
        normalized = prev.get("normalized") if prev else False
        if not dry and (renorm or not normalized):
            g = normalize(path, lufs, peak)
            if g is None:
                action = "⚠ 靜音/量度失敗"
            elif g == 0.0:
                action = "已達標"
                normalized = True
            else:
                action = "調整 {:+.1f}dB".format(g)
                normalized = True
                dur, lufs, peak = measure(path)
        elif dry:
            g = min(TARGET_LUFS - lufs, PEAK_CEILING_DBFS - peak) if lufs not in (None, float("-inf")) else None
            action = "(dry) 會調 {:+.1f}dB".format(g) if g else "(dry) 唔使調"

        cat, tags = classify(stem)
        clips.append({
            "id": stem,
            "file": fn,
            "category": cat,
            "tags": tags,
            "duration_s": round(dur, 2),
            "peak_dbfs": round(peak, 1) if peak not in (None, float("-inf")) else None,
            "loudness_lufs": round(lufs, 1) if lufs not in (None, float("-inf")) else None,
            "normalized": normalized,
            "source": (prev or {}).get("source", "unknown"),
            "license": (prev or {}).get("license", "未確認 —— 商用前要補返出處"),
            "used_in": (prev or {}).get("used_in", []),
        })
        print("{:<26} {:>6.2f}s {:>8} {:>8}  {}".format(
            stem, dur,
            "{:.1f}".format(lufs) if lufs not in (None, float("-inf")) else "-inf",
            "{:.1f}".format(peak) if peak not in (None, float("-inf")) else "-inf",
            action))

    if dry:
        print("\n(dry-run，冇寫檔)")
        return

    with open(CATALOG, "w", encoding="utf-8") as f:
        json.dump({
            "note": ("音效庫。全部 clip 標準化到 ~{} LUFS / {} dBFS peak ceiling，"
                     "所以 sfx-plan.json 嘅 gain_db 跨片可比。短促音效會撞 peak 天花板先，"
                     "所以佢哋 LUFS 會偏細 —— 落 plan 時 gain_db 要 +3~5dB 補返。"
                     ).format(TARGET_LUFS, PEAK_CEILING_DBFS),
            "target_lufs": TARGET_LUFS,
            "peak_ceiling_dbfs": PEAK_CEILING_DBFS,
            "clips": clips,
        }, f, ensure_ascii=False, indent=2)

    by_cat = {}
    for c in clips:
        by_cat.setdefault(c["category"], []).append(c["id"])
    print("\n寫咗 {} 個 clip -> {}".format(len(clips), os.path.relpath(CATALOG, ROOT)))
    for cat in sorted(by_cat):
        print("  {:<10} {}".format(cat, ", ".join(sorted(by_cat[cat]))))


if __name__ == "__main__":
    main()
