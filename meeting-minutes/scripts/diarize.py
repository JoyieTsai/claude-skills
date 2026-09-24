#!/usr/bin/env python3
"""給逐字稿的每一句標上講者代號（A／B／C…）。

**為什麼不用現成的整包 diarization**（pyannote segmentation ＋ 時間軸對位）：
實測過，兩個問題。
1. 它自己切一套語音段落，再拿那套段落去跟 whisper 的行對時間。兩套切法對不齊，
   結果「換人的那一句」最容易標錯——短插話（「對啊」「也還好啊」）會被吸進
   前一個人的區塊，正好是讀的人最想知道是誰講的那幾句。
2. 它的自動人數判斷在實測的 27 分鐘雙人會議上分出 30～74 個人
   （clustering threshold 0.5 → 0.6），不能上線。

**這裡的做法**：whisper 已經把每一句的起訖時間切好了，直接對「每一句」取聲紋，
再把聲紋分群。每一行都用自己那段聲音判斷，不需要跟任何時間軸對位。
同一份 27 分鐘錄音，聲紋只花 10 秒（整包方案要 100 秒），
而且結果與整包方案強制分 2 人的輸出吻合 88%——兩個獨立方法互相印證。

**人數怎麼自動決定**：先只看「較長的句子」（≥3 秒）。短句的聲紋是雜訊，
實測同一人／不同人的平均相似度在 ≥0.6 秒時是 0.380／0.267（幾乎分不開），
到 ≥3 秒時拉開到 0.508／0.350。所以用長句跑階層式分群定出人數，
再用這個人數對全部句子跑 k-means。

模型只需要一個聲紋模型（不需要 segmentation 模型），
`3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx`，28MB，中文語料訓練的。
沒裝 sherpa-onnx 或沒下載模型時，整個功能安靜跳過——逐字稿照樣產出，只是沒有講者。
"""

from __future__ import annotations

import sys
import wave
from dataclasses import dataclass, field
from pathlib import Path

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]

try:
    import sherpa_onnx
except ImportError:  # pragma: no cover
    sherpa_onnx = None  # type: ignore[assignment]

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

EMB_MODEL = '3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx'
EMB_MODEL_URL = (
    'https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/main/'
    + EMB_MODEL
)

SAMPLE_RATE = 16_000

# 太短的句子聲紋不可靠（「對」只有 0.3 秒，特徵幾乎是雜訊）。
# 低於這個長度不參與分群，最後用最近的群心補標，並在逐字稿標 `?`。
MIN_EMBED_S = 0.60

# 決定「幾個人」時只看這麼長以上的句子。實測相似度差距：
# ≥0.6s 同一人 0.380／不同人 0.267（幾乎分不開）；≥1.5s 是 0.439／0.292。
LONG_S = 1.5
MIN_LONG_LINES = 20  # 湊不到這麼多行就不猜人數，直接當 1 個人

# **為什麼人數不能用固定的相似度門檻**：相似度的絕對高度是每份錄音自己的，
# 不是跨錄音可比的量。實測兩場都是雙人會議，≥3 秒句子的相似度中位數卻是
# 0.427（27 分鐘設計審查）與 0.523（14 分鐘檢討會）——同一個門檻 0.35
# 在前者分出 2 人、在後者分出 1 人（漏掉一個人）。
#
# 所以改用輪廓係數：它量的是「群內距離 vs 最近的別群距離」的相對差距，
# 每份錄音自己跟自己比。實測兩場都正確選到 2 人。
SIL_MIN = 0.12  # 最好的分法都低於這個值＝沒有分群結構，當 1 個人
SIL_MARGIN = 0.90  # 較少的人數只要有最佳值的九成好，就選人數少的那個

# 安全網一：會議室收得到的聲音本來就有限，分出 20 個人一定是在切雜訊。
MAX_SPEAKERS = 6

# 安全網二：講話總時長佔比低於此值的群，併進最像的那一群。
MIN_CLUSTER_SHARE = 0.03

# 短句補標時，最像與第二像的差距小於此值＝分不出來，沿用前一行的人。
AMBIGUOUS_GAP = 0.05

KMEANS_RESTARTS = 8  # 固定種子＋多次重啟取最好，結果才可重現

CACHE_DIR = paths.VAR_DIR / 'embeddings'  # 聲紋快取，改人數重標時用


@dataclass
class SpeakerTag:
    """一行的講者標記。"""

    label: str  # 'A'、'B'…
    uncertain: bool  # True＝句子太短，是用最接近的人補的；逐字稿標 `?`


@dataclass
class DiarizeResult:
    tags: list[SpeakerTag | None]  # 與 lines 一一對應；None＝完全無法判斷
    speakers: list[str] = field(default_factory=list)  # 代號，依講話時長排序（A 最多）
    seconds: dict[str, float] = field(default_factory=dict)
    uncertain_lines: int = 0
    clustered_lines: int = 0  # 真的有聲紋參與分群的行數
    skipped: str | None = None  # 跳過的理由

    @property
    def total_seconds(self) -> float:
        return sum(self.seconds.values()) or 1.0

    def share(self, label: str) -> float:
        return 100.0 * self.seconds.get(label, 0.0) / self.total_seconds


def model_path(models_dir: Path | None = None) -> Path:
    return (models_dir or paths.MODELS_DIR) / EMB_MODEL


def unavailable_reason(models_dir: Path | None = None) -> str | None:
    """回傳跳過的理由；None＝可以跑。"""
    if sherpa_onnx is None:
        return '未安裝 sherpa-onnx（重跑 install.sh，Windows 是 install.cmd）'
    if np is None:
        return '未安裝 numpy（重跑 install.sh，Windows 是 install.cmd）'
    path = model_path(models_dir)
    if not path.is_file():
        return f'找不到聲紋模型（重跑 install.sh 下載，Windows 是 install.cmd）：{path}'
    return None


def read_wav_mono16k(path: Path):
    """讀 transcribe.to_wav_16k_mono() 產生的 WAV。刻意不吃別的格式。"""
    with wave.open(str(path)) as f:
        if f.getnchannels() != 1 or f.getsampwidth() != 2:
            raise ValueError(f'需要 16-bit 單聲道 WAV：{path}')
        rate = f.getframerate()
        raw = f.readframes(f.getnframes())
    if rate != SAMPLE_RATE:
        raise ValueError(f'需要 {SAMPLE_RATE}Hz，拿到 {rate}Hz：{path}')
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def embed_lines(
    wav: Path,
    lines: list[tuple[int, int, str]],
    models_dir: Path | None = None,
    *,
    progress: bool = True,
):
    """對每一行算聲紋（已 L2 normalize）。回傳 (embeddings, durations)；
    算不出來的行是 NaN。"""
    samples = read_wav_mono16k(wav)
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(model_path(models_dir)), num_threads=2, provider='cpu'
    )
    if not config.validate():
        raise ValueError('聲紋模型設定無效')
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)

    embeddings = np.full((len(lines), extractor.dim), np.nan, dtype=np.float32)
    durations = np.zeros(len(lines), dtype=np.float32)
    min_samples = int(MIN_EMBED_S * SAMPLE_RATE)

    for i, (start_ms, end_ms, text) in enumerate(lines):
        if text.startswith('⚠️'):
            # 幻聽摺疊留下的標記，不是人講的話。留 NaN＝沿用前一行、不影響佔比
            continue
        durations[i] = max(0.0, (end_ms - start_ms) / 1000.0)
        a = max(0, int(start_ms / 1000.0 * SAMPLE_RATE))
        b = min(len(samples), int(end_ms / 1000.0 * SAMPLE_RATE))
        chunk = samples[a:b]
        if len(chunk) < min_samples:
            continue
        stream = extractor.create_stream()
        stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=chunk)
        stream.input_finished()
        vec = np.asarray(extractor.compute(stream), dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            embeddings[i] = vec / norm
        if progress and i % 50 == 0:
            print(
                f'\r  聲紋… {100.0 * (i + 1) / len(lines):5.1f}%',
                end='',
                file=sys.stderr,
                flush=True,
            )

    if progress:
        print('\r  聲紋… 完成    ', file=sys.stderr, flush=True)
    return embeddings, durations


def _kmeans(x, k, *, restarts: int = KMEANS_RESTARTS):
    """球面 k-means（cosine）。固定種子＋多次重啟取最好，結果可重現。"""
    if k <= 1 or len(x) <= k:
        return np.zeros(len(x), dtype=np.int32)

    best_labels, best_score = None, -np.inf
    for seed in range(restarts):
        rng = np.random.default_rng(seed)
        centers = [x[rng.integers(len(x))]]
        for _ in range(k - 1):
            d = 1.0 - np.max(np.stack([x @ c for c in centers]), axis=0)
            d = np.clip(d, 1e-9, None)
            centers.append(x[rng.choice(len(x), p=d / d.sum())])
        c = np.stack(centers)
        labels = np.full(len(x), -1, dtype=np.int32)
        for _ in range(60):
            new = np.argmax(x @ c.T, axis=1).astype(np.int32)
            if (new == labels).all():
                break
            labels = new
            for j in range(k):
                rows = x[labels == j]
                if len(rows):
                    v = rows.mean(axis=0)
                    norm = float(np.linalg.norm(v))
                    c[j] = v / norm if norm else v
        score = float(np.max(x @ c.T, axis=1).sum())
        if score > best_score:
            best_labels, best_score = labels, score
    return best_labels


def _centroid(emb, weights):
    vec = (emb * weights[:, None]).sum(axis=0)
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


def _merge_tiny(labels, weights, emb, *, min_share: float):
    """講話佔比太小的群併進最像的大群。這是擋掉「分出一堆人」的關鍵。"""
    groups = sorted(set(labels.tolist()))
    if len(groups) <= 1:
        return labels
    mass = {g: float(weights[labels == g].sum()) for g in groups}
    total = sum(mass.values()) or 1.0
    big = [g for g in groups if mass[g] / total >= min_share]
    if not big:
        big = [max(groups, key=lambda g: mass[g])]
    small = [g for g in groups if g not in big]
    if not small:
        return labels

    big_centroids = np.stack(
        [_centroid(emb[labels == g], weights[labels == g]) for g in big]
    )
    out = labels.copy()
    for g in small:
        sims = big_centroids @ _centroid(emb[labels == g], weights[labels == g])
        out[labels == g] = big[int(np.argmax(sims))]
    return out


def _silhouette(x, labels) -> float:
    """cosine 版輪廓係數。+1＝分得很乾淨，0＝群界模糊，負的＝分錯了。"""
    groups = sorted(set(labels.tolist()))
    if len(groups) < 2:
        return float('nan')
    dist = 1.0 - x @ x.T
    scores = []
    for i in range(len(x)):
        own_mask = labels == labels[i]
        own_mask[i] = False
        if own_mask.sum() == 0:
            continue
        a = float(dist[i][own_mask].mean())
        b = min(float(dist[i][labels == g].mean()) for g in groups if g != labels[i])
        denom = max(a, b)
        if denom > 0:
            scores.append((b - a) / denom)
    return float(np.mean(scores)) if scores else float('nan')


def _guess_speaker_count(emb, durations, usable) -> int:
    """只看較長的句子決定人數，用輪廓係數挑。挑不出結構就回 1。"""
    mask = usable & (durations >= LONG_S)
    if mask.sum() < MIN_LONG_LINES:
        return 1
    x, w = emb[mask], durations[mask]

    scored: list[tuple[int, float]] = []
    for k in range(2, MAX_SPEAKERS + 1):
        if len(x) <= k:
            break
        labels = _merge_tiny(_kmeans(x, k), w, x, min_share=MIN_CLUSTER_SHARE)
        actual = len(set(labels.tolist()))
        if actual < 2:
            continue
        score = _silhouette(x, labels)
        if score == score:  # 不是 NaN
            scored.append((actual, score))
    if not scored:
        return 1

    best_score = max(score for _k, score in scored)
    if best_score < SIL_MIN:
        return 1
    # 人數少的優先：只要有最佳值九成好就選它，避免把同一個人拆成兩個
    good = [k for k, score in scored if score >= best_score * SIL_MARGIN]
    return min(good)


def assign_speakers(
    emb,
    durations,
    lines: list[tuple[int, int, str]],
    *,
    speakers: int | None = None,
) -> DiarizeResult:
    """把算好的聲紋分群並標到每一行。分群很快（不到 1 秒），
    所以「改人數重標」不必重算聲紋，也不必重新轉錄。"""
    usable = ~np.isnan(emb[:, 0])
    if usable.sum() < 2:
        return DiarizeResult(
            [None] * len(lines), skipped='可用的句子太少（錄音太短或太碎）'
        )

    k = speakers or _guess_speaker_count(emb, durations, usable)
    sub_emb, sub_w = emb[usable], durations[usable]
    sub_labels = _kmeans(sub_emb, k)
    if not speakers:
        sub_labels = _merge_tiny(
            sub_labels, sub_w, sub_emb, min_share=MIN_CLUSTER_SHARE
        )

    groups = sorted(set(sub_labels.tolist()))
    talk = {g: float(sub_w[sub_labels == g].sum()) for g in groups}
    order = sorted(groups, key=lambda g: -talk[g])  # A 是講最多的那個人
    name = {g: chr(ord('A') + i) for i, g in enumerate(order)}

    rows = np.flatnonzero(usable).tolist()
    label_of_row = {row: int(sub_labels[i]) for i, row in enumerate(rows)}

    tags: list[SpeakerTag | None] = [None] * len(lines)
    seconds: dict[str, float] = {}
    uncertain = 0
    prev_label: str | None = None

    for i, (_s, _e, text) in enumerate(lines):
        if text.startswith('⚠️'):
            continue  # 摺疊標記不屬於任何人，也不打斷發言區塊
        if i in label_of_row:
            tags[i] = SpeakerTag(name[label_of_row[i]], uncertain=False)
        else:
            # 句子太短沒有聲紋：沿用前一行的人
            if prev_label is None:
                continue
            tags[i] = SpeakerTag(prev_label, uncertain=True)
            uncertain += 1
        prev_label = tags[i].label
        seconds[prev_label] = seconds.get(prev_label, 0.0) + float(durations[i])

    present = [name[g] for g in order if seconds.get(name[g], 0.0) > 0]
    return DiarizeResult(
        tags=tags,
        speakers=present,
        seconds=seconds,
        uncertain_lines=uncertain,
        clustered_lines=int(usable.sum()),
    )


def diarize_lines(
    wav: Path,
    lines: list[tuple[int, int, str]],
    models_dir: Path | None = None,
    *,
    speakers: int | None = None,
    progress: bool = True,
    cache_stem: str | None = None,
) -> DiarizeResult:
    """主入口。lines 是 transcribe.segments_to_lines() 的 (start_ms, end_ms, text)。

    cache_stem 有給的話，聲紋會存進 var/embeddings/，之後 relabel.py 改人數
    就不用重算（也不用留著原始錄音）。
    """
    reason = unavailable_reason(models_dir)
    if reason:
        return DiarizeResult([None] * len(lines), skipped=reason)
    if not lines:
        return DiarizeResult([], skipped='逐字稿沒有內容')

    emb, durations = embed_lines(wav, lines, models_dir, progress=progress)
    if cache_stem:
        try:
            save_cache(cache_stem, emb, durations, lines)
        except OSError as exc:  # 快取寫不進去不該讓轉錄失敗
            print(f'   · 聲紋快取寫入失敗（不影響這次結果）：{exc}', flush=True)
    return assign_speakers(emb, durations, lines, speakers=speakers)


# ── 聲紋快取：讓「改人數重標」不必重跑轉錄 ──────────────────────────────
# 一場 27 分鐘的會議約 600KB。放 var/（不進版控、可重建）。


def cache_path(stem: str) -> Path:
    return CACHE_DIR / f'{stem}.npz'


def save_cache(stem: str, emb, durations, lines: list[tuple[int, int, str]]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(stem)
    np.savez_compressed(
        path,
        emb=emb,
        dur=durations,
        start_ms=np.array([s for s, _e, _t in lines], dtype=np.int64),
        end_ms=np.array([e for _s, e, _t in lines], dtype=np.int64),
        text=np.array([t for _s, _e, t in lines], dtype=object),
        version=np.array([1]),
    )
    return path


def load_cache(stem: str):
    """回傳 (emb, durations, lines)。沒有快取回 None。"""
    path = cache_path(stem)
    if not path.is_file():
        return None
    z = np.load(path, allow_pickle=True)
    lines = [
        (int(s), int(e), str(t))
        for s, e, t in zip(z['start_ms'], z['end_ms'], z['text'])
    ]
    return z['emb'], z['dur'], lines


# ── 逐字稿上的呈現 ───────────────────────────────────────────────────


def _fmt_ts(ms: int) -> str:
    s = int(ms) // 1000
    return f'{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}'


def summary_line(result: DiarizeResult) -> str:
    """逐字稿開頭那行「講者：…」。

    代號刻意用「講者 A」而不是「說話者A」：範本、lint_minutes.py、使用流程
    通篇都是「講者 A」。同一個概念在逐字稿與會議記錄裡叫兩個名字，讀的人
    得自己對應，而那正是最該省下來的力氣。
    """
    summary = '／'.join(
        f'{label} {result.share(label):.0f}%' for label in result.speakers
    )
    return f'講者：{len(result.speakers)} 人（{summary}）'


def who_block(result: DiarizeResult) -> list[str]:
    """逐字稿開頭的「誰是誰」對照表，留給人填名字。"""
    out = ['', '## 誰是誰', '', '| 代號 | 名字 | 講了多久 |', '| --- | --- | --- |']
    for label in result.speakers:
        out.append(
            f'| 講者 {label} | @? | {result.seconds[label] / 60:.0f} 分'
            f'（{result.share(label):.0f}%） |'
        )
    # 只分出一個人時，講「兩人搶話會標錯」是廢話，該講的是「可能漏了插話的人」。
    if len(result.speakers) == 1:
        note = (
            '> 整份都當成同一個人在講。**這可能是錯的**——'
            '如果其實有人插話問問題，只是講得少，聲紋就分不出來。'
        )
    else:
        note = (
            '> 講者是用聲紋自動分群的，**會有錯**。'
            '兩人搶話、同時講、只回一句「對啊」的地方最容易標錯。'
        )
    if result.uncertain_lines:
        note += (
            f' 另有 {result.uncertain_lines} 行句子太短、聲紋不可靠，'
            '是沿用前一行的人。'
        )
    out.extend(['', note, '', '> 人數不對就重標（幾秒鐘，不用重新轉錄）：'
                '`scripts/relabel.py <這份逐字稿> --speakers 3`'])
    return out


def render_body(
    lines: list[tuple[int, int, str]], result: DiarizeResult | None
) -> list[str]:
    """逐字稿的內文。

    `[HH:MM:SS] 內容` 那幾行**一個字都不動**——review.py／eval.py 是靠那個
    格式讀逐字稿的。講者只在換人時多插一行。
    """
    tags = result.tags if result and result.speakers else None
    out: list[str] = []
    prev_label: str | None = None
    for i, (start_ms, _end_ms, text) in enumerate(lines):
        if text.startswith('⚠️'):
            out.append(f'> {text}')
            continue
        if tags:
            tag = tags[i] if i < len(tags) else None
            label = tag.label if tag else None
            if label and label != prev_label:
                out.append('')
                out.append(f'**講者 {label}**')
            prev_label = label or prev_label
        out.append(f'[{_fmt_ts(start_ms)}] {text}')
    return out


def emit_console(result: DiarizeResult) -> None:
    if result.skipped:
        print(f'→ 講者：略過（{result.skipped}）', flush=True)
        return
    if not result.speakers:
        print('→ 講者：判斷不出來，這次不標', flush=True)
        return
    parts = [
        f'{label} {result.seconds[label] / 60:.0f}分（{result.share(label):.0f}%）'
        for label in result.speakers
    ]
    print(f'→ 講者：分出 {len(result.speakers)} 人　' + '　'.join(parts), flush=True)
    if result.uncertain_lines:
        print(
            f'   · {result.uncertain_lines} 行太短、聲紋不可靠，沿用前一行並標 `?`',
            flush=True,
        )
