#!/usr/bin/env bash
# reverb_throw.sh — DRY audio that blooms into a wet Freeverb tail right as it cuts.
# The signature audio move:
# the body stays clean; only the LAST moment gets thrown into reverb and drags out into silence.
# Stack it with a riser / SFX at a cut point for depth.
#
# Deps: sox (brew install sox — ffmpeg's afir convolution is BROKEN in our build, outputs silence) + ffmpeg.
# Usage: reverb_throw.sh IN.wav OUT.wav [THROW_SEC=0.7] [REVERB=78] [TAIL_PAD=4] [WET=1.0]
#   IN        = an already-trimmed audio clip (the cut you want to end on)
#   THROW_SEC = how much of the ENDING gets sent to reverb (0.7 = just the last beat/chord)
#   REVERB    = sox reverberance 0-100 (tail length/lushness; 78 = ~2-3s hall)
#   TAIL_PAD  = seconds of silence appended so the tail has room to ring
#   WET       = wet-tail mix level vs the dry body (1.0 default)
# Output is normalized to -3 dB (tasteful, not slamming).
set -euo pipefail
IN="$1"; OUT="$2"
THROW="${3:-0.7}"; REV="${4:-78}"; PAD="${5:-4}"; WET="${6:-1.0}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

DUR=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$IN")
START=$(echo "$DUR - $THROW" | bc -l)
DELAYMS=$(printf '%.0f' "$(echo "$START*1000" | bc -l)")

# 1. isolate the ending, pad so the reverb can ring out
ffmpeg -y -ss "$START" -t "$THROW" -i "$IN" "$TMP/tailsrc.wav" -loglevel error
ffmpeg -y -i "$TMP/tailsrc.wav" -af "apad=pad_dur=$PAD" "$TMP/tailpad.wav" -loglevel error
# 2. WET-ONLY Freeverb on just that ending
sox "$TMP/tailpad.wav" "$TMP/wet.wav" reverb -w "$REV" 45 100 100 20 1
# 3. dry full clip, padded to match
ffmpeg -y -i "$IN" -af "apad=pad_dur=$PAD" "$TMP/dry.wav" -loglevel error
# 4. bloom the wet tail in at the cut, mixed UNDER the clean dry body
ffmpeg -y -i "$TMP/dry.wav" -i "$TMP/wet.wav" -filter_complex \
  "[1:a]adelay=${DELAYMS}|${DELAYMS}[wd];[0:a][wd]amix=inputs=2:weights=1 ${WET}:normalize=0[mix]" \
  -map "[mix]" "$TMP/raw.wav" -loglevel error
# 5. normalize to -3 dB
MAX=$(ffmpeg -i "$TMP/raw.wav" -af volumedetect -f null - 2>&1 | grep max_volume | grep -oE '\-?[0-9.]+ dB' | grep -oE '\-?[0-9.]+')
GAIN=$(echo "scale=2; -3.0 - ($MAX)" | bc)
ffmpeg -y -i "$TMP/raw.wav" -af "volume=${GAIN}dB" "$OUT" -loglevel error
echo "wrote $OUT (throw=${THROW}s reverb=${REV} pad=${PAD}s wet=${WET})"
