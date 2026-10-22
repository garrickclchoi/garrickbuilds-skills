#!/usr/bin/env python3
"""
mix_sfx.py — 音效對位混音器。

流程：Remotion render 出乾淨嘅片 → 寫 sfx-plan.json（每個 cue 一行）→
呢個 script 用 ffmpeg 逐個 clip delay 到位、加 gain、summed 成 SFX bus、
sidechain duck 喺人聲底下、最後過 limiter 防爆。畫面原封不動 copy 過去，
所以改音效唔使重新 render Remotion（呢個係成套嘢最抵嘅地方）。

用法:
  python3 tools/mix_sfx.py sfx-plans/MyReel.json --print      # 只印 cue sheet，唔 render
  python3 tools/mix_sfx.py sfx-plans/MyReel.json              # 混音
  python3 tools/mix_sfx.py sfx-plans/MyReel.json --no-optional --end 30
  python3 tools/mix_sfx.py sfx-plans/MyReel.json --preview out/other.mp4 --out out/x.mp4

⚠️ 落 cue 之前建議同客人／自己過 --print 出嚟嘅 cue sheet（audit gate）。
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rp(p):
    return p if os.path.isabs(p) else os.path.join(ROOT, p)


def show(p):
    try:
        return os.path.relpath(p, ROOT)
    except ValueError:
        return p


def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        sys.stderr.write("\nFFMPEG 失敗:\n  " + " ".join(cmd) + "\n" + r.stdout[-4000:] + "\n")
        raise SystemExit(1)
    return r.stdout


def arg_val(args, name, cast=str):
    return cast(args[args.index(name) + 1]) if name in args else None


def main():
    args = sys.argv[1:]
    only_print = "--print" in args
    no_optional = "--no-optional" in args
    duck_override = False if "--no-duck" in args else (True if "--duck" in args else None)
    end_override = arg_val(args, "--end", float)
    out_override = arg_val(args, "--out")
    preview_override = arg_val(args, "--preview")

    consumed = {str(end_override), out_override, preview_override}
    positional = [a for a in args if not a.startswith("--") and a not in consumed]
    if not positional:
        sys.exit("要指定 plan，例如：python3 tools/mix_sfx.py sfx-plans/MyReel.json")
    plan_path = rp(positional[0])

    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)
    render = plan.get("render", {})

    catalog_path = rp(plan.get("catalog", "public/sfx/catalog.json"))
    with open(catalog_path, encoding="utf-8") as f:
        catalog = json.load(f)
    lib = {c["id"]: c for c in catalog.get("clips", [])}
    clips_dir = os.path.dirname(catalog_path)

    preview = rp(preview_override or render["preview"])
    out = rp(out_override or render["out"])
    end = end_override if end_override is not None else float(render.get("end_s", 1e9))
    duck = duck_override if duck_override is not None else bool(render.get("duck", True))

    # offset_s：plan 入面嘅 at_s 用「片內時間」（同 src/MyReel/data.ts 嘅 CAPTIONS 同一個鐘，
    # 0 = 人聲第一個字）。但 render 出嚟嘅 mp4 可能前面仲有 composition 嘅嘢。
    # offset_s 就係兩個鐘之間嘅差，加咗先落 ffmpeg。寫 cue 嗰陣唔使諗呢層。
    offset = float(plan.get("offset_s", 0.0))

    # base_gain_db：成張表嘅總校準。每個 cue 嘅 gain_db 係「相對基準」嘅數字
    # （跟品牌框架 §Effect：音效 = 人聲 40-50%），跨片可以照抄；
    # base_gain_db 就負責食走呢條片人聲響度嘅差異。
    # 原素材人聲通常得 -25 LUFS 左右，音效庫係 -20 LUFS —— 唔校就大聲過人聲 5dB。
    # 用 `python3 tools/check_sfx.py <plan> --calibrate` 計返啱嘅數。
    base = float(plan.get("base_gain_db", 0.0))

    events, missing = [], set()
    for e in plan["events"]:
        if no_optional and e.get("optional"):
            continue
        t = float(e["at_s"]) + offset
        if t >= end or t < 0:
            continue
        clip = lib.get(e["sfx_id"])
        if not clip:
            missing.add(e["sfx_id"])
            continue
        f = os.path.join(clips_dir, clip["file"])
        if not os.path.exists(f):
            missing.add(e["sfx_id"] + " (檔案唔見咗)")
            continue
        events.append(dict(e, mix_at=t, file=f, clip=clip))
    events.sort(key=lambda e: e["mix_at"])

    print("plan: {}   音效庫: {} 個 clip".format(show(plan_path), len(lib)))
    print("片源: {}".format(show(preview)))
    print("offset: {:+.3f}s   base_gain: {:+.1f}dB   end: {}   duck: {}".format(
        offset, base, "{:.2f}s".format(end) if end < 1e8 else "全長", duck))
    if base == 0.0:
        print("  ⚠ base_gain_db 未校準 —— 先行 check_sfx.py --calibrate")
    print("cue 數: {}{}".format(
        len(events),
        "  (略過 {} 個 optional)".format(sum(1 for x in plan["events"] if x.get("optional")))
        if no_optional else ""))
    print("  {:>7} {:>8}  {:<22} {:>6}  {}".format("片內", "mp4", "音效", "gain", "對位點"))
    for e in events:
        opt = "  (可有可無)" if e.get("optional") else ""
        print("  {:>6.2f}s {:>7.2f}s  {:<22} {:>4}dB  {}{}".format(
            float(e["at_s"]), e["mix_at"], e["sfx_id"],
            e.get("gain_db", 0), e.get("cue", "")[:44], opt))
    if missing:
        print("  ⚠ 音效庫冇：" + "、".join(sorted(missing)))

    if only_print:
        return
    if missing:
        sys.exit("有音效搵唔到 —— 先加落 public/sfx/ 再行 build_sfx_catalog.py。")
    if not events:
        sys.exit("冇 cue 可以混。")
    if not os.path.exists(preview):
        sys.exit("搵唔到片源: " + preview)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", preview]
    for e in events:
        cmd += ["-i", e["file"]]

    parts, labels = [], []
    for i, e in enumerate(events):
        ms = int(round(e["mix_at"] * 1000))
        g = base + float(e.get("gain_db", 0))
        parts.append("[{}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                     "adelay={}:all=1,volume={:.2f}dB[e{}]".format(i + 1, ms, g, i))
        labels.append("[e{}]".format(i))

    if len(labels) == 1:
        parts.append(labels[0] + "anull[sfxraw]")
    else:
        parts.append("".join(labels) +
                     "amix=inputs={}:normalize=0:dropout_transition=0[sfxraw]".format(len(labels)))

    if duck:
        parts.append("[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[v1][v2]")
        # 輕手 duck：只係人聲大聲嗰陣將音效塞低幾 dB，唔係要佢消失。
        # 每個 cue 嘅 gain_db 已經定咗佢喺人聲底下，呢度淨係執重疊。
        parts.append("[sfxraw][v1]sidechaincompress=threshold=0.15:ratio=2:"
                     "attack=5:release=200:makeup=2[sfxduck]")
        parts.append("[v2][sfxduck]amix=inputs=2:normalize=0[mixraw]")
    else:
        parts.append("[0:a]aformat=sample_rates=48000:channel_layouts=stereo[v2]")
        parts.append("[v2][sfxraw]amix=inputs=2:normalize=0[mixraw]")
    parts.append("[mixraw]alimiter=level_in=1:level_out=1:limit=0.97[mix]")

    cmd += ["-filter_complex", ";".join(parts),
            "-map", "0:v:0", "-map", "[mix]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    if end < 1e8:
        cmd += ["-t", "{:.3f}".format(end)]
    cmd += [out]

    print("\nrender 緊 -> {}".format(show(out)))
    run(cmd)
    dur = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", out]).strip()
    print("搞掂 -> {}  ({}s, {} 個 cue)".format(show(out), dur, len(events)))
    print("下一步：python3 tools/check_sfx.py {} --mixed {}".format(show(plan_path), show(out)))


if __name__ == "__main__":
    main()
