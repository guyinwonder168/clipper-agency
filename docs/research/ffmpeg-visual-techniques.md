# FFmpeg Visual Techniques Reference

> Compiled for Visual Director enhancement (Phase 18).
> Sources: `tanersener/ffmpeg-video-slideshow-scripts`, `mifi/editly`, `NapoleonWils0n/ffmpeg-scripts`, FFmpeg docs.

---

## Table of Contents

1. [Scene Treatments](#scene-treatments)
2. [Transitions](#transitions)
3. [FPS Rules](#fps-rules)
4. [Pacing Rules (TikTok)](#pacing-rules-tiktok)
5. [Offset Calculation for Multi-Scene xfade](#offset-calculation-for-multi-scene-xfade)
6. [Practical Command Examples](#practical-command-examples)
7. [Appendix: All FFmpeg xfade Transition Types](#appendix-all-ffmpeg-xfade-transition-types)

---

## Scene Treatments

### ken_burns_zoom_in

- **FFmpeg filter:**
  ```
  zoompan=z='min(pzoom+0.0015,1.5)':d={frames}:s=1080x1920:fps=30
  ```
  Center-focused zoom (no pan):
  ```
  zoompan=z='min(pzoom+0.001*{speed},2)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':fps=30:s=1080x1920
  ```
- **Duration:** 3–7s (default 5s)
- **Input type:** image
- **Use:** still images, photos, establishing shots

**Zoom speed reference** (from tanersener):

| Speed value | Increment/frame | Time to 1.5x (at 30fps) |
|-------------|-----------------|--------------------------|
| 1 (slowest) | 0.001           | ~16.7s                   |
| 2 (slow)    | 0.002           | ~8.3s                    |
| 3 (moderate)| 0.003           | ~5.6s                    |
| 4 (faster)  | 0.004           | ~4.2s                    |
| 5 (fastest) | 0.005           | ~3.3s                    |

**Critical pre-step:** Image must be pre-scaled to 5× target width before zoompan to provide pixels for panning:
```
scale=5400:-1,zoompan=...
```

**Pan directions** (randomized per image — pick one):

| Direction | x formula | y formula |
|-----------|-----------|-----------|
| Center (pure zoom) | `iw/2-(iw/zoom/2)` | `ih/2-(ih/zoom/2)` |
| Top-right | `iw/2` | `-(ih/zoom/2)` |
| Bottom-right | `iw/2` | `(ih/zoom/2)` |
| Top-left | `-(iw/zoom/2)` | `-(ih/zoom/2)` |
| Bottom-left | `-(iw/zoom/2)` | `(ih/zoom/2)` |

---

### ken_burns_pan_left

- **FFmpeg filter:**
  ```
  zoompan=z='1.05':x='iw-(iw/zoom)*on/{frames}':y='ih/2-(ih/zoom)/2':d={frames}:s=1080x1920:fps=30
  ```
  Alternative from tanersener (constant-zoom horizontal pan):
  ```
  zoompan=z='1.3+0.1':x='(progress*(iw-iw/zoom))':y='ih/2-(ih/zoom)/2':d={frames}:s=1080x1920:fps=30
  ```
- **Duration:** 3–7s
- **Input type:** image
- **Use:** wide/landscape photos, panoramic shots

**Ken Burns math from editly** (JS reference, translate to FFmpeg expressions):

| Direction | Scale | Pan X |
|-----------|-------|-------|
| `in`      | `1 + amount × progress` (1→1.1) | 0 |
| `out`     | `1 + amount × (1-progress)` (1.1→1) | 0 |
| `left`    | `1.3 + amount` (fixed) | `-(progress × range - range/2)` |
| `right`   | `1.3 + amount` (fixed) | `progress × range - range/2` |

Where `amount = 0.1` default, `range = amount × 1000`.

---

### ken_burns_zoom_out

- **FFmpeg filter:**
  ```
  zoompan=z='1.5-in*0.002*{speed}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':fps=30:s=1080x1920
  ```
- **Duration:** 3–7s
- **Input type:** image
- **Use:** reveal shots, pulling back from detail
- **Notes:** Uses `in` (frame counter) instead of `pzoom`. Starts at 1.5× and zooms out.

---

### lower_third_slide

- **FFmpeg filter:**
  ```
  drawtext=text='{text}':fontsize=42:fontcolor=white:x=(w-text_w)/2:y=h*0.75:box=1:boxcolor=black@0.6:boxborderw=10
  ```
  Animated slide-in from left (from tanersener pattern):
  ```
  drawtext=text='{text}':fontsize=48:fontcolor=white:x='if(lt(t,0.5),-500-w+1000*t,20)':y=h-150:box=1:boxcolor=black@0.6:boxborderw=10
  ```
- **Duration:** 2–4s overlay
- **Input type:** text
- **Use:** artist names, attribution, context bars

**Semi-transparent background bar** (separate filter, applied before drawtext):
```
drawbox=x=0:y=h-150:w=w:h=60:color=black@0.65:t=fill
```

**Scrolling ticker text** (right-to-left loop):
```
drawtext=text='{text}':fontsize=30:fontcolor=white:x='w-mod(t/{speed}*((w+text_w)/{speed}),w+text_w)':y=h-50
```
Speed: `1=fastest`, `5=slowest`.

---

### text_card_reveal

- **FFmpeg filter:**
  ```
  drawtext=text='{text}':fontsize=64:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:alpha='if(lt(t,0.5),t/0.5,1)'
  ```
  With fade-in + fade-out:
  ```
  drawtext=text='{text}':fontsize=72:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:alpha='if(lt(t,1),t,if(gt(t,{duration}-1),{duration}-t,1))'
  ```
- **Duration:** 3–5s
- **Input type:** text
- **Use:** quotes, facts, text reveals, dramatic statements

---

### hook_big_caption

- **FFmpeg filter:**
  ```
  drawtext=text='{text}':fontsize=80:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:borderw=4:bordercolor=black
  ```
  With subtle scale pulse (using zoompan wrapper):
  ```
  zoompan=z='1.0+0.02*sin(on/15)':d={frames}:s=1080x1920:fps=30,drawtext=text='{text}':fontsize=80:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:borderw=4:bordercolor=black
  ```
- **Duration:** 2–3s
- **Input type:** text
- **Use:** opening hook, always scene 1, maximum visual impact

---

### cinematic_crop

- **FFmpeg filter:**
  ```
  crop=ih*9/16:ih,scale=1080:1920
  ```
  With smart center crop (crop widest dimension):
  ```
  crop='min(iw,ih*9/16):min(ih,ih)':(iw-min(iw,ih*9/16))/2:0,scale=1080:1920
  ```
- **Duration:** source duration
- **Input type:** video
- **Use:** landscape video → 9:16 vertical

**Aspect ratio handling** (4 modes from tanersener):

| Mode | FFmpeg Filters |
|------|---------------|
| **Contain** (letterbox) | `scale='if(gte(iw/ih,9/16),1080,-1)':'if(gte(iw/ih,9/16),-1,1920)',pad=1080:1920:(1080-iw)/2:(1920-ih)/2:color=black` |
| **Cover** (crop fill) | `scale='if(gte(iw/ih,9/16),-1,1080)':'if(gte(iw/ih,9/16),1920,-1)',crop=1080:1920` |
| **Stretch** | `scale=1080:1920` |
| **Contain-blur** | Two streams: `scale=1080:1920,boxblur=100` (background) + `scale=contain` (foreground), `overlay` centered |

---

### slow_motion

- **FFmpeg filter:**
  ```
  setpts=2.0*PTS
  ```
  Speed factors: `0.5` = 2× slow, `0.25` = 4× slow, `2.0` = 2× fast
- **Duration:** source × speed factor
- **Input type:** video
- **Use:** 60fps → 30fps = natural 50% slow-mo, dramatic moments

---

### fade_to_black

- **FFmpeg filter:**
  ```
  fade=t=out:st={duration}-1:d=1
  ```
  Fade from black at start:
  ```
  fade=t=in:st=0:d=0.5
  ```
  Both fade-in and fade-out on same stream:
  ```
  fade=t=in:st=0:d=0.5,fade=t=out:st={duration-0.5}:d=0.5
  ```
- **Duration:** source + fade
- **Input type:** video (closing scene only)
- **Use:** scene endings, dramatic pauses

---

## Transitions

### crossfade

- **FFmpeg:**
  ```
  xfade=transition=fade:duration=0.3:offset={offset}
  ```
- Default transition, smooth blend
- **Duration:** 0.3s default (range 0.2–1.0s)

### wipe_left

- **FFmpeg:**
  ```
  xfade=transition=wipeleft:duration=0.5:offset={offset}
  ```
- Timeline/progression feel
- **Variants:** `wiperight`, `wipeup`, `wipedown`, `wipetl`, `wipetr`, `wipebl`, `wipebr`

### dissolve

- **FFmpeg:**
  ```
  xfade=transition=dissolve:duration=0.4:offset={offset}
  ```
- Sentimental/dramatic moments, softer than crossfade

### circle_open

- **FFmpeg:**
  ```
  xfade=transition=circleopen:duration=0.5:offset={offset}
  ```
- Playful reveal
- **Variant:** `circleclose` (reverse direction)

### hard_cut

- No FFmpeg filter needed — simply concat without transition
- For punch emphasis, high energy, maintaining pacing

### slide

- **FFmpeg:**
  ```
  xfade=transition=slideleft:duration=0.5:offset={offset}
  ```
- **Variants:** `slideright`, `slideup`, `slidedown`
- Good for topic changes, momentum

### smooth

- **FFmpeg:**
  ```
  xfade=transition=smoothleft:duration=0.5:offset={offset}
  ```
- **Variants:** `smoothright`, `smoothup`, `smoothdown`
- Softer than slide, with easing

### directional_fade

- **FFmpeg:**
  ```
  xfade=transition=fadeblack:duration=0.5:offset={offset}
  ```
- **Variants:** `fadewhite`, `fadegrays`, `fadefast`, `fadeslow`
- Brief dip through black/white between scenes

---

## FPS Rules

- **TikTok target:** 30fps (ALL scenes)
- **Stock footage:** varies 24/25/30/50/60fps
- **Images → video:** zoompan at 30fps
- **60fps → 30fps:** = 50% slow-mo (use `setpts=2.0*PTS`)
- **Mixed fps in concat:** = frame duplication → stutter/hang

**Normalization filter** (applied to every input before concat/xfade):
```
settb=AVTB,setpts=PTS-STARTPTS,fps=30
```

**Frame count formula:**
```
frames = duration_seconds × 30
```

**Even dimension enforcement** (prevents H.264 errors):
```
scale=trunc(iw/2)*2:trunc(ih/2)*2
```

---

## Pacing Rules (TikTok)

| Parameter | Value | Notes |
|-----------|-------|-------|
| Hook window | first 1–3s | Grab attention immediately |
| Scene changes | every 2–5s | Maintain engagement |
| Minimum scene | 2.0s | Never shorter |
| Maximum clip | 5.0s | Keep it snappy |
| Images with Ken Burns | 3–7s | With motion effect |
| Videos trimmed | 3–10s | With cut points |
| Closing | fade to black over 0.5–1s | Clean ending |
| Caption speed | 3 words/second | Readable pace |
| Preferred transitions | crossfade, hard_cut | Default set |

---

## Offset Calculation for Multi-Scene xfade

### Two videos

```
offset_1 = clip1_duration - transition_duration
```

With 0.1s safety margin (from NapoleonWils0n):
```
offset_1 = clip1_duration - transition_duration - 0.1
```

### N videos (variable durations)

```
offset_0 = clip[0].duration - transition_duration
offset_n = offset_{n-1} + clip[n].duration - transition_duration
```

**Example (3 clips, 5s each, 1s transition):**
```
offset_1 = 5 - 1 = 4
offset_2 = 4 + 5 - 1 = 8    # NOT 9 — common mistake
```

### Audio crossfade with xfade

```bash
ffmpeg -i clip1.mp4 -i clip2.mp4 \
  -filter_complex "\
    [0:v][1:v]xfade=transition=fade:duration=0.5:offset=4.5[v]; \
    [0:a]atrim=0:4.9[a]; \
    [a][1:a]acrossfade=d=0.5[af]" \
  -map "[v]" -map "[af]" \
  -pix_fmt yuv420p -movflags +faststart output.mp4
```

Key: `atrim` clip1 audio to `duration - 0.1` before feeding `acrossfade`.

### Chaining 3+ videos with xfade

```bash
ffmpeg -i v0.mp4 -i v1.mp4 -i v2.mp4 \
  -filter_complex "\
    [0:v][1:v]xfade=transition=fade:duration=0.5:offset=4.5[v1]; \
    [v1][2:v]xfade=transition=fade:duration=0.5:offset=8.0[v]" \
  -map "[v]" -pix_fmt yuv420p output.mp4
```

### Split A/V for many clips (10+ videos, avoids desync)

```bash
# Step 1: Video only
ffmpeg ... -filter_complex "$VIDEO_FILTERS" -map "[v]" -c:v libx264 -an -y video.mp4

# Step 2: Audio only
ffmpeg ... -filter_complex "$AUDIO_FILTERS" -map "[a]" -c:a aac -y audio.m4a

# Step 3: Mux
ffmpeg -i video.mp4 -i audio.m4a -c copy final.mp4
```

### Mix concat (hard cut) + xfade in same chain

```bash
ffmpeg -i s0.mp4 -i s1.mp4 -i s2.mp4 \
  -filter_complex "\
    [0:v]settb=AVTB,setpts=PTS-STARTPTS,fps=30[n0]; \
    [1:v]settb=AVTB,setpts=PTS-STARTPTS,fps=30[n1]; \
    [2:v]settb=AVTB,setpts=PTS-STARTPTS,fps=30[n2]; \
    [n0][n1]concat=n=2:v=1[v1]; \
    [v1][n2]xfade=transition=fade:duration=0.5:offset=7.0[outv]" \
  -map "[outv]" output.mp4
```

---

## Practical Command Examples

### Example 1: Image slideshow with Ken Burns zoom-in

```bash
ffmpeg -y \
  -loop 1 -i photo1.jpg -loop 1 -i photo2.jpg -loop 1 -i photo3.jpg \
  -filter_complex "\
    [0:v]scale=5400:-1,zoompan=z='min(pzoom+0.002,1.5)':d=150:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,fps=30,trim=duration=5[s0]; \
    [1:v]scale=5400:-1,zoompan=z='min(pzoom+0.002,1.5)':d=150:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,fps=30,trim=duration=5[s1]; \
    [2:v]scale=5400:-1,zoompan=z='min(pzoom+0.002,1.5)':d=150:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,fps=30,trim=duration=5[s2]; \
    [s0][s1]xfade=transition=fade:duration=0.5:offset=4.5[v1]; \
    [v1][s2]xfade=transition=fade:duration=0.5:offset=9.0[outv]" \
  -map "[outv]" -c:v libx264 -preset fast -crf 23 \
  -pix_fmt yuv420p -movflags +faststart output.mp4
```

### Example 2: Text card with fade reveal + lower third on video

```bash
ffmpeg -y -i background.jpg \
  -filter_complex "\
    [0:v]scale=1080:1920,format=yuva420p[bg]; \
    [bg]drawtext=text='Did you know?':fontsize=80:fontcolor=white:\
      x=(w-text_w)/2:y=(h-text_h)/3:borderw=3:bordercolor=black:\
      alpha='if(lt(t,1),t,if(gt(t,3),4-t,1))'[t1]; \
    [t1]drawtext=text='Most artists struggle with...':fontsize=42:\
      fontcolor=white:x=(w-text_w)/2:y=h*0.75:box=1:\
      boxcolor=black@0.6:boxborderw=10:\
      enable='between(t,1,4)'[outv]" \
  -map "[outv]" -t 5 -c:v libx264 -pix_fmt yuv420p output.mp4
```

### Example 3: Landscape video → vertical with Ken Burns + captions

```bash
ffmpeg -y -i landscape_clip.mp4 \
  -filter_complex "\
    [0:v]crop=ih*9/16:ih,scale=1080:1920,setsar=1,fps=30, \
    drawtext=text='Breaking News':fontsize=48:fontcolor=white:\
      x=20:y=h-80:box=1:boxcolor=black@0.6:boxborderw=8:\
      enable='between(t,0,3)', \
    drawtext=text='Tahukah kamu?':fontsize=36:fontcolor=yellow:\
      x=(w-text_w)/2:y=40:borderw=2:bordercolor=black:\
      enable='between(t,1,5)'[outv]" \
  -map "[outv]" -c:v libx264 -pix_fmt yuv420p output.mp4
```

### Example 4: Multi-scene with mixed transitions (hard_cut → crossfade → hard_cut)

This matches the current engine.py pattern:

```bash
ffmpeg -y -i s0.mp4 -i s1.mp4 -i s2.mp4 -i s3.mp4 \
  -filter_complex "\
    [0:v]settb=AVTB,setpts=PTS-STARTPTS,fps=30[n0]; \
    [1:v]settb=AVTB,setpts=PTS-STARTPTS,fps=30[n1]; \
    [2:v]settb=AVTB,setpts=PTS-STARTPTS,fps=30[n2]; \
    [3:v]settb=AVTB,setpts=PTS-STARTPTS,fps=30[n3]; \
    [n0][n1]concat=n=2:v=1[v1]; \
    [v1][n2]xfade=transition=fade:duration=0.3:offset=7.7[v2]; \
    [v2][n3]concat=n=2:v=1[outv]" \
  -map "[outv]" -c:v libx264 -pix_fmt yuv420p output.mp4
```

### Example 5: Scrolling news ticker overlay

```bash
ffmpeg -y -i video.mp4 \
  -vf "\
    drawbox=x=0:y=h-60:w=w:h=60:color=black@0.65:t=fill, \
    drawtext=textfile=ticker.txt:fontsize=28:fontcolor=white:\
      x='w-mod(t/3*((w+text_w)/3),w+text_w)':y=h-45:\
      fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" \
  -c:v libx264 -c:a copy output.mp4
```

### Example 6: Blurred background letterbox (editly contain-blur pattern)

```bash
ffmpeg -y -i video.mp4 \
  -filter_complex "\
    [0:v]scale=1080:1920,boxblur=100[bg]; \
    [0:v]scale='if(gte(iw/ih,9/16),1080,-1)':'if(gte(iw/ih,9/16),-1,1920)'[fg]; \
    [bg][fg]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2:format=rgb[outv]" \
  -map "[outv]" -c:v libx264 -pix_fmt yuv420p output.mp4
```

---

## Appendix: All FFmpeg xfade Transition Types

Complete list from FFmpeg 7.x+ (`libavfilter/vf_xfade.c`):

| Category | Transitions |
|----------|------------|
| **Fade variants** | `fade`, `fadeblack`, `fadewhite`, `fadegrays`, `fadefast`, `fadeslow` |
| **Wipe** | `wipeleft`, `wiperight`, `wipeup`, `wipedown`, `wipetl`, `wipetr`, `wipebl`, `wipebr` |
| **Slide** | `slideleft`, `slideright`, `slideup`, `slidedown` |
| **Smooth** | `smoothleft`, `smoothright`, `smoothup`, `smoothdown` |
| **Circle/Rect** | `circleopen`, `circleclose`, `circlecrop`, `rectcrop` |
| **Vertical/Horizontal blinds** | `vertopen`, `vertclose`, `horzopen`, `horzclose` |
| **Diagonal** | `diagtl`, `diagtr`, `diagbl`, `diagbr` |
| **Slice** | `hlslice`, `hrslice`, `vuslice`, `vdslice` |
| **Wind** | `hlwind`, `hrwind`, `vuwind`, `vdwind` |
| **Cover/Reveal** | `coverleft`, `coverright`, `coverup`, `coverdown`, `revealleft`, `revealright`, `revealup`, `revealdown` |
| **Other** | `dissolve`, `pixelize`, `distance`, `radial`, `hblur`, `squeezeh`, `squeezev`, `zoomin`, `custom` |

**Recommended set for TikTok content:**

| Name | Best For | Default Duration |
|------|----------|-----------------|
| `fade` (crossfade) | Default, smooth blend | 0.3s |
| `wipeleft` | Topic changes, progression | 0.5s |
| `dissolve` | Sentimental/dramatic | 0.4s |
| `circleopen` | Playful reveal | 0.5s |
| `slideleft` | Momentum, energy | 0.4s |
| `fadeblack` | Scene breaks, dramatic pause | 0.5s |
| `zoomin` | Focus emphasis | 0.5s |
| hard cut (no filter) | Punch emphasis, high energy | 0s |

---

## Important FFmpeg Pitfalls

1. **`-pix_fmt yuv420p`** — Always add after xfade for player compatibility. xfade may output yuv444p.
2. **`-movflags +faststart`** — Always add for MP4 output (moov atom at start).
3. **Even dimensions** — H.264 requires even width/height. Use `scale=trunc(iw/2)*2:trunc(ih/2)*2`.
4. **SAR normalization** — After any scale/crop, apply `setsar=1/1` to prevent distortion.
5. **PTS reset** — After trim/split operations, use `setpts=PTS-STARTPTS` to reset timestamps.
6. **0.1s safety margin** — Subtract 0.1s from xfade offset to prevent transitions running past clip end.
7. **Transition < shortest clip** — Transition duration must be less than the shortest clip, or FFmpeg errors.
8. **Pixel format for compositing** — Use `format=rgba` for alpha compositing, then `format=yuv420p` for output.
9. **`shortest=1`** on overlay — Stops when shorter stream ends, prevents infinite loop.
10. **Audio desync with 10+ clips** — Split video/audio rendering, then mux with `-c copy`.
