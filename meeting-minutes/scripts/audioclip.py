#!/usr/bin/env python3
"""從原始錄音切出短片段，給人校對時直接點開聽。

校對清單告訴你「00:23:50 這句可疑」，但人得自己開播放器拖到那個位置——一份
40 行的清單就要拖 40 次。這是整個迭代迴圈實際上最大的摩擦點，切片解決它。

recheck.py 也用這裡切片，它要把可疑片段餵回 whisper 重解碼。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PAD_BEFORE_MS = 2000  # 往前多給一點，不然一開口就開始聽不出前後文
PAD_AFTER_MS = 2000
MIN_CLIP_MS = 3000  # 太短的片段聽不出東西


def clip_name(start_ms: int) -> str:
    total = max(0, start_ms) // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f'{h:02d}-{m:02d}-{s:02d}'


def cut(
    ffmpeg: str,
    src: Path,
    dst: Path,
    start_ms: int,
    end_ms: int,
    *,
    pad_before_ms: int = PAD_BEFORE_MS,
    pad_after_ms: int = PAD_AFTER_MS,
    wav_16k: bool = False,
) -> bool:
    """切出 [start, end] 加上前後 padding 的片段。成功回傳 True。

    wav_16k=True 時輸出 16kHz 單聲道 WAV（whisper 要吃的格式），
    否則輸出 AAC（給人聽的，檔案小很多）。
    """
    start = max(0, start_ms - pad_before_ms)
    dur = max(MIN_CLIP_MS, (end_ms - start_ms) + pad_before_ms + pad_after_ms)
    codec = (
        ['-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le']
        if wav_16k
        else ['-c:a', 'aac', '-b:a', '64k']
    )
    cmd = [
        ffmpeg,
        '-y',
        '-loglevel',
        'error',
        # -ss 放在 -i 前面是快速 seek。短片段只是拿來聽／重解碼，
        # 不需要 frame-accurate，換到的速度差很多（40 段就有感）。
        '-ss',
        f'{start / 1000:.3f}',
        '-t',
        f'{dur / 1000:.3f}',
        '-i',
        str(src),
        '-vn',
        *codec,
        str(dst),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except (subprocess.CalledProcessError, OSError):
        return False
    return dst.is_file() and dst.stat().st_size > 0


def cut_many(
    ffmpeg: str,
    src: Path,
    out_dir: Path,
    spans: list[tuple[int, int]],
    *,
    wav_16k: bool = False,
) -> dict[int, str]:
    """批次切片，回傳 {start_ms: 檔名}。切失敗的就不會出現在結果裡。"""
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {}
    ext = 'wav' if wav_16k else 'm4a'
    made: dict[int, str] = {}
    for start_ms, end_ms in spans:
        name = f'{clip_name(start_ms)}.{ext}'
        if cut(ffmpeg, src, out_dir / name, start_ms, end_ms, wav_16k=wav_16k):
            made[start_ms] = name
    return made
