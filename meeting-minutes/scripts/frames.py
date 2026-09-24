#!/usr/bin/env python3
"""從螢幕錄影抽出關鍵畫面，給寫會議記錄時對「你看這個」。

whisper 只吃音訊。講者指著畫面卻沒念出路徑／檔名時，逐字稿會變成
「這裡有寫」——這支腳本在那些時間點截一張 JPEG，AI 再用 Read 看圖。

音訊檔（沒有真正的影像軌）會直接跳過。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audioclip import clip_name  # noqa: E402

MAX_FRAMES = 16
MIN_GAP_MS = 8_000
LOOKAHEAD_MS = 800
FALLBACK_INTERVAL_MS = 90_000
JPEG_QUALITY = 4  # ffmpeg -q:v，數字越小檔越大、越清楚。4 夠讀 IDE 文字
MAX_WIDTH = 1600

# 講者在指畫面時常見的說法。太寬（光「這個」）會抽一堆閒聊；
# 用 MIN_GAP 壓密度，MAX_FRAMES 壓總量。
POINTING = re.compile(
    r'你看|看這|看那|看一下|看到[了嗎吧沒]|'
    r'這裡|這邊|那裡|那邊|'
    r'這個|那個|'
    r'螢幕|畫面|'
    r'資料夾|檔案|路徑|'
    r'上面|下面|左邊|右邊|'
    r'點這|點那|選這|開這|貼這|複製這|'
    r'接到這裡|長記下來'
)


def has_video_stream(src: Path, *, ffmpeg: str, ffprobe: str | None = None) -> bool:
    """有可截的影像軌才算。封面圖（mjpeg 單張）不算。"""
    probe = ffprobe or shutil.which('ffprobe')
    if not probe:
        return src.suffix.lower() in {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}

    proc = subprocess.run(
        [
            probe,
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=codec_name,nb_frames,duration,width',
            '-of',
            'json',
            str(src),
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    if proc.returncode != 0:
        return False
    try:
        streams = json.loads(proc.stdout or '{}').get('streams') or []
    except json.JSONDecodeError:
        return False
    if not streams:
        return False
    s = streams[0]
    codec = (s.get('codec_name') or '').lower()
    if codec in {'mjpeg', 'png', 'bmp', 'gif'}:
        nb = s.get('nb_frames')
        try:
            if nb is not None and int(nb) <= 1:
                return False
        except ValueError:
            pass
    return True


def pick_timestamps(
    lines: list[tuple[int, int, str]],
    duration_ms: int | None,
) -> list[tuple[int, str]]:
    """回傳 (截圖毫秒, 為什麼抽)。已依時間去重、封頂。"""
    hits: list[tuple[int, str]] = []
    for start_ms, end_ms, text in lines:
        if not text or not POINTING.search(text):
            continue
        at = start_ms + LOOKAHEAD_MS
        if end_ms > start_ms:
            at = min(at, max(start_ms, end_ms - 200))
        snippet = re.sub(r'\s+', ' ', text).strip()
        if len(snippet) > 40:
            snippet = snippet[:40] + '…'
        hits.append((max(0, at), snippet))

    picked = _thin(hits, MIN_GAP_MS, MAX_FRAMES)

    if len(picked) < 4 and duration_ms and duration_ms >= FALLBACK_INTERVAL_MS:
        taken = [ms for ms, _ in picked]
        extra: list[tuple[int, str]] = []
        t = FALLBACK_INTERVAL_MS
        while t < duration_ms - 1000:
            if all(abs(t - e) >= MIN_GAP_MS for e in taken):
                extra.append((t, '間隔抽樣（指畫面的句子不夠）'))
                taken.append(t)
            t += FALLBACK_INTERVAL_MS
        picked = _thin(picked + extra, MIN_GAP_MS, MAX_FRAMES)

    return picked


def _thin(
    items: list[tuple[int, str]],
    min_gap_ms: int,
    cap: int,
) -> list[tuple[int, str]]:
    kept: list[tuple[int, str]] = []
    for ms, why in items:
        if kept and ms - kept[-1][0] < min_gap_ms:
            continue
        kept.append((ms, why))
    if len(kept) <= cap:
        return kept
    if cap <= 1:
        return kept[:1]
    step = (len(kept) - 1) / (cap - 1)
    return [kept[round(i * step)] for i in range(cap)]


def grab_jpeg(ffmpeg: str, src: Path, dst: Path, at_ms: int) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        '-y',
        '-loglevel',
        'error',
        '-ss',
        f'{at_ms / 1000:.3f}',
        '-i',
        str(src),
        '-frames:v',
        '1',
        '-vf',
        f"scale='min({MAX_WIDTH},iw)':-2",
        '-q:v',
        str(JPEG_QUALITY),
        str(dst),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except (subprocess.CalledProcessError, OSError):
        return False
    return dst.is_file() and dst.stat().st_size > 0


def write_index(
    index_path: Path,
    src: Path,
    frames_dir: Path,
    items: list[tuple[int, str, Path]],
) -> None:
    rel_dir = frames_dir.name
    rows = ['# 畫面截圖', '', f'來源：`{src.name}`', f'共 {len(items)} 張。', '']
    rows.append('寫會議記錄時請 **Read 這些 JPEG**，把畫面上的路徑、檔名、按鈕、指令寫進筆記。')
    rows.append('圖空白、載入中、或字太小讀不到，才標 ⚠️。')
    rows.append('')
    rows.append('| 時間 | 為什麼抽 | 檔案 |')
    rows.append('| --- | --- | --- |')
    for ms, why, img in items:
        ts = _fmt(ms)
        rows.append(f'| `{ts}` | {why.replace("|", "/")} | `{rel_dir}/{img.name}` |')
    rows.append('')
    index_path.write_text('\n'.join(rows) + '\n', encoding='utf-8')


def emit_frames(
    *,
    ffmpeg: str,
    src: Path,
    transcript_path: Path,
    lines: list[tuple[int, int, str]],
    duration_s: float | None,
    ffprobe: str | None = None,
) -> Path | None:
    """有影像軌才抽圖。成功回傳索引 .frames.md，否則 None。"""
    ffprobe = ffprobe or shutil.which('ffprobe')
    if not has_video_stream(src, ffmpeg=ffmpeg, ffprobe=ffprobe):
        return None

    duration_ms = int(duration_s * 1000) if duration_s else None
    stamps = pick_timestamps(lines, duration_ms)
    if not stamps:
        print('→ 畫面截圖：有影像軌，但沒對上可抽的時間點', flush=True)
        return None

    frames_dir = transcript_path.parent / f'{transcript_path.stem}.frames'
    if frames_dir.exists():
        for old in frames_dir.glob('*.jpg'):
            old.unlink()
    frames_dir.mkdir(parents=True, exist_ok=True)

    print(f'→ 畫面截圖：抽 {len(stamps)} 張（最多 {MAX_FRAMES}）', flush=True)
    saved: list[tuple[int, str, Path]] = []
    used_names: set[str] = set()
    for ms, why in stamps:
        base = clip_name(ms)
        name = f'{base}.jpg'
        n = 2
        while name in used_names:
            name = f'{base}-{n}.jpg'
            n += 1
        used_names.add(name)
        dst = frames_dir / name
        if grab_jpeg(ffmpeg, src, dst, ms):
            saved.append((ms, why, dst))

    if not saved:
        print('→ 畫面截圖：抽圖失敗（ffmpeg 沒截到畫面）', flush=True)
        return None

    index_path = transcript_path.with_suffix('.frames.md')
    write_index(index_path, src, frames_dir, saved)
    print(f'→ 畫面截圖：{index_path}（{len(saved)} 張）', flush=True)
    return index_path


def _fmt(ms: int) -> str:
    total = max(0, ms) // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'
