#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智绘声影2.0+剪映自动视频工作台
"""

import os
import sys
import io
import re
import json
import uuid
import math
import random
import shutil
import string
import datetime
import subprocess
import webbrowser
from pathlib import Path

# ==========================================
# 0. 本地持久化配置与独立缓存目录设置
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. 设置 Gradio 上传临时目录至当前工程下的 gradio_tmp/
GRADIO_TMP_DIR = os.path.join(BASE_DIR, "gradio_tmp")
os.makedirs(GRADIO_TMP_DIR, exist_ok=True)
os.environ["GRADIO_TEMP_DIR"] = GRADIO_TMP_DIR

# 2. 设置拖入上传文件生成的默认输出目录 outputs/
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)

import gradio as gr

CONFIG_FILE = os.path.join(BASE_DIR, "app_config.json")

def get_default_draft_path():
    """获取系统默认的剪映草稿路径"""
    if sys.platform == "darwin":  # macOS
        return os.path.expanduser("~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft")
    elif sys.platform == "win32":  # Windows
        return os.path.expanduser("~/AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft")
    return ""

def load_config():
    """读取本地配置"""
    default_cfg = {
        "base_drafts_dir": get_default_draft_path(),
        "last_selected_project": ""
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                default_cfg.update(cfg)
        except Exception:
            pass
    return default_cfg

def save_config(cfg):
    """保存本地配置"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存配置失败: {e}")

def open_folder_in_explorer(file_or_dir_path):
    """跨平台打开 Finder (Mac) 或 资源管理器 (Windows) 并定位高亮文件/文件夹"""
    if not file_or_dir_path:
        return
    clean_path = str(file_or_dir_path).strip().strip('"\'“”‘’')
    if not os.path.exists(clean_path):
        return
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", clean_path])
        elif sys.platform == "win32":
            if os.path.isdir(clean_path):
                subprocess.run(["explorer", os.path.normpath(clean_path)])
            else:
                subprocess.run(["explorer", "/select,", os.path.normpath(clean_path)])
        else:
            folder = os.path.dirname(clean_path) if os.path.isfile(clean_path) else clean_path
            subprocess.run(["xdg-open", folder])
    except Exception as e:
        print(f"打开文件夹失败: {e}")

def normalize_path(path_str: str) -> str:
    """清理并规整路径：剥离中英文引号、去除反斜杠转义、规范化路径"""
    if not path_str:
        return ""
    p = str(path_str).strip()
    p = p.strip('"\'“”‘’')
    p = p.replace(r"\ ", " ")
    if p:
        p = os.path.normpath(os.path.expanduser(p))
    return p

def resolve_input_path(path_str, file_obj):
    """同时兼容手动/带引号绝对路径与上传文件"""
    if path_str and path_str.strip():
        p = normalize_path(path_str)
        if os.path.exists(p):
            return p, True
    if file_obj is not None:
        return file_obj.name, False
    return None, False

def determine_out_path(source_file_path: str, suffix: str, ext: str, save_in_origin: bool, is_real_source: bool) -> str:
    p = Path(source_file_path).resolve()
    target_ext = ext if ext else p.suffix
    if not target_ext.startswith('.'):
        target_ext = '.' + target_ext
    filename = f"{p.stem}{suffix}{target_ext}"
    
    if save_in_origin and is_real_source:
        out_path = p.parent / filename
    else:
        out_path = Path(OUTPUTS_DIR) / filename
    return str(out_path)

# ==========================================
# 0.1 FFmpeg 跨平台执行引擎 (PingPong 专用)
# ==========================================
def get_ffmpeg_executable():
    """获取系统中可用的 ffmpeg 命令路径"""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return None

def get_ffprobe_duration_us(video_path):
    """获取视频物理文件的真实微秒时长"""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        dur_sec = float(res.stdout.strip())
        return int(dur_sec * 1000000)
    except Exception:
        return None

def build_pingpong_video(src_video_path: str, num_repeats: int) -> str:
    """
    通过 FFmpeg 渲染正放+倒放相间的无缝 PingPong 实体视频（静音纯净画面）
    num_repeats: 拼接总片数（>=2），例如 2 片: 正+反；3 片: 正+反+正
    返回生成后的本地视频绝对路径
    """
    src_p = Path(src_video_path).resolve()
    ffmpeg_bin = get_ffmpeg_executable()
    if not ffmpeg_bin:
        raise RuntimeError("系统未检测到 ffmpeg，请确保已安装 ffmpeg 并配置环境变量！")

    out_name = f"{src_p.stem}_pingpong_{num_repeats}x{src_p.suffix}"
    out_dir = src_p.parent
    # 若源目录不可写，退回 outputs 目录
    if not os.access(out_dir, os.W_OK):
        out_dir = Path(OUTPUTS_DIR)
    out_path = out_dir / out_name

    # 若之前已生成过且文件存在，直接复用
    if out_path.exists() and out_path.stat().st_size > 1000:
        return str(out_path)

    # 构造复杂滤镜图：偶数位正放，奇数位反放
    # 如 num_repeats=3: [0:v]split=3[v0][v1][v2]; [v1]reverse[r1]; [v0][r1][v2]concat=n=3:v=1[outv]
    splits = "".join([f"[v{i}]" for i in range(num_repeats)])
    filter_parts = [f"[0:v]split={num_repeats}{splits}"]
    
    concat_inputs = []
    for i in range(num_repeats):
        if i % 2 == 1:
            filter_parts.append(f"[v{i}]reverse[r{i}]")
            concat_inputs.append(f"[r{i}]")
        else:
            concat_inputs.append(f"[v{i}]")
            
    concat_str = "".join(concat_inputs)
    filter_parts.append(f"{concat_str}concat=n={num_repeats}:v=1[outv]")
    filter_complex = ";".join(filter_parts)

    cmd = [
        ffmpeg_bin, "-y",
        "-i", str(src_p),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-an",
        str(out_path)
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg 生成 PingPong 视频失败: {res.stderr}")
    return str(out_path)

# ==========================================
# 1. 文本与字幕核心算法
# ==========================================
CHARS_TO_IGNORE_PUNCT = string.punctuation + \
    '。、，．；：？！…—·‘’“”（）【】｛｝～' + \
    '！＂＃＄％＆＇（）＊＋，－．／：；＜＝＞？＠［＼］＾＿｀｛｜｝～' + \
    '《》￥……〖〗〔〕「」『』 \t\n\r\u3000'

KEEP_CHARS_PUNCT = {'—', '《', '》', '+', '-', '×', '÷', '·'}
PUNCT_ZH = {
    '。', '、', '，', '．', '；', '：', '？', '！', '…',
    '‘', '’', '“', '”', '【', '】', '｛', '｝', '～', '〖', '〗',
    '！', '＂', '＃', '＄', '％', '＆', '＇', '（', '）', '＊', '，',
    '．', '／', '：', '；', '＜', '＝', '＞', '？', '＠', '［',
    '＼', '］', '＾', '＿', '｀', '｛', '｜', '｝', '～',
    '¥', '℃', '々', '→', '↑', '↓', '←', '￣'
}
ALL_PUNCT_CHECK = (set(string.punctuation) | PUNCT_ZH) - KEEP_CHARS_PUNCT

def get_effective_char_count(text):
    if not isinstance(text, str): return 0
    return len([char for char in text if char not in CHARS_TO_IGNORE_PUNCT])

def srt_time_to_ms(time_str):
    time_str = time_str.strip().replace('.', ',')
    parts = time_str.split(':')
    h = int(parts[0])
    m = int(parts[1])
    s_parts = parts[2].split(',')
    s = int(s_parts[0])
    ms = int(s_parts[1])
    return (h * 3600 + m * 60 + s) * 1000 + ms

def parse_srt_for_timing(filepath):
    entries = []
    total_effective_chars = 0
    with io.open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read().strip()
    pattern = re.compile(r'(\d+)\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*([\s\S]*?)(?=\n\n|\Z)', re.MULTILINE)
    for match in pattern.findall(content):
        index, start_time, end_time, text = int(match[0]), match[1], match[2], match[3].strip()
        text_lines = [l.strip() for l in text.splitlines() if not re.match(r'^\d+$', l.strip()) and '-->' not in l]
        cleaned_text = "".join(text_lines)
        effective_len = get_effective_char_count(cleaned_text)
        start_ms = srt_time_to_ms(start_time)
        end_ms = srt_time_to_ms(end_time)
        entries.append({
            'index': index, 'start': start_time, 'end': end_time, 
            'start_ms': start_ms, 'end_ms': end_ms, 'effective_len': effective_len
        })
        total_effective_chars += effective_len
    entries.sort(key=lambda x: x['start_ms'])
    return entries, total_effective_chars

def core_process_text_no_marks(path_str, file_obj, save_in_origin):
    filepath, is_real = resolve_input_path(path_str, file_obj)
    if not filepath or not os.path.exists(filepath):
        return "请在输入框粘贴/拖入 TXT 文件路径，或上传 TXT 文件！", "", None, ""

    processed_lines = []
    line_count, blank_lines = 0, 0
    with open(filepath, 'r', encoding='utf-8-sig', errors='ignore') as infile:
        for line in infile:
            line_count += 1
            sline = line.strip()
            if not sline:
                blank_lines += 1
                continue
            chars = [' ' if c in ALL_PUNCT_CHECK else c for c in sline]
            processed_lines.append(' '.join("".join(chars).split()))

    output_content = "\n".join(processed_lines)
    out_path = determine_out_path(filepath, "_No_Marks", ".txt", save_in_origin, is_real)
    with open(out_path, 'w', encoding='utf-8-sig') as f:
        f.write(output_content)
    
    loc_msg = f"原目录: {out_path}" if (save_in_origin and is_real) else f"工作台输出目录: {out_path}"
    log = f"处理完成！原始行数: {line_count} | 移除空行: {blank_lines} | 保留行数: {len(processed_lines)}\n💾 文件已保存至 [{loc_msg}]"
    return log, output_content, out_path, out_path

def core_merge_srt(srt_path_str, srt_file_obj, txt_path_str, txt_file_obj, save_in_origin):
    srt_p, is_real = resolve_input_path(srt_path_str, srt_file_obj)
    txt_p, _ = resolve_input_path(txt_path_str, txt_file_obj)
    if not srt_p or not txt_p or not os.path.exists(srt_p) or not os.path.exists(txt_p):
        return "请同时提供 SRT 和 TXT 文件路径或上传文件！", "", None, ""

    source_entries, src_chars = parse_srt_for_timing(srt_p)
    
    lines_data, tgt_chars = [], 0
    with io.open(txt_p, 'r', encoding='utf-8', errors='ignore') as f:
        for i, line in enumerate(f):
            raw = line.strip()
            if raw:
                eff_len = get_effective_char_count(raw)
                if eff_len > 0:
                    lines_data.append({'original': raw, 'effective_len': eff_len, 'line_num': i + 1})
                    tgt_chars += eff_len

    if not source_entries or not lines_data:
        return "解析文件失败，请检查文件内容！", "", None, ""

    final_entries = []
    source_srt_idx = 0
    consumed_chars = 0
    for target_idx, target_line in enumerate(lines_data):
        needed = target_line['effective_len']
        accumulated = 0
        seg_start = None
        last_full_end = None
        last_contrib_idx = -1

        while accumulated < needed and source_srt_idx < len(source_entries):
            cur_block = source_entries[source_srt_idx]
            avail = cur_block['effective_len'] - consumed_chars
            if avail <= 0:
                last_full_end = cur_block['end']
                source_srt_idx += 1
                consumed_chars = 0
                continue
            if seg_start is None:
                seg_start = cur_block['start']
            last_contrib_idx = source_srt_idx
            take = min(needed - accumulated, avail)
            accumulated += take
            consumed_chars += take
            if consumed_chars >= cur_block['effective_len']:
                last_full_end = cur_block['end']
                source_srt_idx += 1
                consumed_chars = 0
            if accumulated >= needed:
                break

        final_start = seg_start or (final_entries[-1]['end'] if final_entries else "00:00:00,000")
        if last_contrib_idx != -1:
            final_end = last_full_end if (consumed_chars > 0 and last_full_end) else source_entries[last_contrib_idx]['end']
        else:
            final_end = final_start

        final_entries.append(f"{target_idx + 1}\n{final_start} --> {final_end}\n{target_line['original']}")

    output_content = "\n\n".join(final_entries) + "\n\n"
    out_path = determine_out_path(srt_p, "_merged", ".srt", save_in_origin, is_real)
    with io.open(out_path, 'w', encoding='utf-8-sig') as f:
        f.write(output_content)

    loc_msg = f"原SRT目录: {out_path}" if (save_in_origin and is_real) else f"工作台输出目录: {out_path}"
    log = f"映射完成！共生成 {len(final_entries)} 条字幕。\n字符统计: 源SRT({src_chars}) vs 目标TXT({tgt_chars})\n💾 文件已保存至 [{loc_msg}]"
    return log, output_content, out_path, out_path

def core_inject_srt_duration_to_prompts(srt_path_str, srt_file_obj, txt_path_str, txt_file_obj, fps_str, time_unit, multiplier, save_in_origin):
    srt_p, _ = resolve_input_path(srt_path_str, srt_file_obj)
    txt_p, is_real = resolve_input_path(txt_path_str, txt_file_obj)
    if not srt_p or not txt_p or not os.path.exists(srt_p) or not os.path.exists(txt_p):
        return "请同时提供 SRT 文件 和 TXT 文件路径或上传文件！", "", None, ""

    fps = float(fps_str)
    mult = float(multiplier)
    
    srt_entries, _ = parse_srt_for_timing(srt_p)
    if not srt_entries:
        return "SRT 文件解析失败或内容为空！", "", None, ""
    
    with open(txt_p, 'r', encoding='utf-8', errors='ignore') as f:
        raw_text = f.read()

    raw_blocks = [b.strip() for b in raw_text.strip().split('\n\n') if b.strip()]
    prompt_items = []
    for blk in raw_blocks:
        lines = blk.split('\n', 1)
        title_line = lines[0].strip()
        body_line = lines[1].strip() if len(lines) > 1 else ""
        if '|' in title_line:
            title_line = title_line.split('|')[0].strip()
        prompt_items.append({"title": title_line, "body": body_line})

    num_srt = len(srt_entries)
    num_txt = len(prompt_items)

    log_lines = [f"📊 【数量核对】SRT 字幕句数: {num_srt} 句 | TXT 提示词分镜数: {num_txt} 段"]
    if num_srt == num_txt:
        log_lines.append("✅ 完美对齐！SRT 与 TXT 数量完全一致。")
    elif num_srt > num_txt:
        log_lines.append(f"⚠️ 提示：SRT 句数比 TXT 提示词多 {num_srt - num_txt} 句，已自动截取前 {num_txt} 句匹配时长。")
    else:
        log_lines.append(f"⚠️ 警告：TXT 提示词比 SRT 句数多 {num_txt - num_srt} 个！多出的提示词分镜将无法匹配时长。")

    durations_ms = []
    curr_start_ms = 0
    for i in range(num_srt):
        if i < num_srt - 1:
            next_start = srt_entries[i+1]['start_ms']
            dur = max(1, next_start - curr_start_ms)
        else:
            dur = max(1, srt_entries[i]['end_ms'] - curr_start_ms)
        durations_ms.append(dur)
        curr_start_ms += dur

    output_blocks = []
    process_len = min(num_txt, num_srt)

    for i in range(process_len):
        item = prompt_items[i]
        dur_ms = durations_ms[i]
        target_sec = (dur_ms / 1000.0) * mult
        
        if "帧数" in time_unit or time_unit == "frames":
            total_frames = int(round(target_sec * fps))
            dur_str = f"{total_frames}f"
        else:
            dur_str = f"{target_sec:.1f}s"

        output_blocks.append(f"{item['title']}|{dur_str}\n{item['body']}")

    if num_txt > num_srt:
        for i in range(num_srt, num_txt):
            item = prompt_items[i]
            output_blocks.append(f"{item['title']}|未知时长\n{item['body']}")

    output_content = "\n\n".join(output_blocks) + "\n"
    out_path = determine_out_path(txt_p, "_with_duration", ".txt", save_in_origin, is_real)
    with open(out_path, 'w', encoding='utf-8-sig') as f:
        f.write(output_content)

    log_lines.append(f"🎉 处理完成！已成功注入 {process_len} 个分镜的时长参数（系数: {mult}x）。")
    loc_msg = f"原TXT目录: {out_path}" if (save_in_origin and is_real) else f"工作台输出目录: {out_path}"
    log_lines.append(f"💾 文件已保存至 [{loc_msg}]")
    return "\n".join(log_lines), output_content, out_path, out_path

# ==========================================
# 2. 媒体文件智能整理与去重备份核心算法
# ==========================================
MEDIA_CATEGORY_EXTENSIONS = {
    'doc': {'txt', 'doc', 'docx', 'md', 'json', 'py', 'pdf'},
    'image': {'jpg', 'jpeg', 'png', 'psd', 'tiff', 'webp'},
    'audio': {'wav', 'mp3', 'wma', 'm4a', 'flac', 'ogg', 'aac'},
    'video': {'mp4', 'mov', 'm4v', 'mkv', 'avi', 'flv'}
}

EXT_TO_CATEGORY = {}
for cat, exts in MEDIA_CATEGORY_EXTENSIONS.items():
    for ext in exts:
        EXT_TO_CATEGORY[ext] = cat

def clean_media_base_name(stem: str) -> str:
    pattern = r'(_\d+|-\d+|\s+\d+|_\(\d+\)|\(\d+\)|\[\d+\]|[-_\s]*副本|\(副本\))$'
    cur = stem
    while True:
        new_cur = re.sub(pattern, '', cur, flags=re.IGNORECASE).strip()
        if new_cur == cur or not new_cur:
            break
        cur = new_cur
    return cur if cur else stem

def extract_group_key(stem: str) -> str:
    clean_stem = clean_media_base_name(stem)
    match = re.match(r'^(\d+)[._\-\s]', clean_stem)
    if match:
        return f"prefix_{match.group(1)}"
    return f"name_{clean_stem.lower()}"

def get_unique_target_path(target_folder: Path, filename: str) -> Path:
    dest = target_folder / filename
    if not dest.exists():
        return dest
    name_stem = dest.stem
    ext = dest.suffix
    counter = 1
    while True:
        new_dest = target_folder / f"{name_stem}_dup{counter}{ext}"
        if not new_dest.exists():
            return new_dest
        counter += 1

def core_clean_media_folder(folder_path_str, mode_choice, retain_filter="all"):
    if not folder_path_str or not folder_path_str.strip():
        return "请先输入或粘贴需要整理的文件夹路径！", ""
    
    clean_p = normalize_path(folder_path_str)
    directory = Path(clean_p).resolve()
    if not directory.exists() or not directory.is_dir():
        return f"❌ 错误: 路径不存在或不是文件夹: {clean_p}", ""

    parent_dir = directory.parent
    file_list = []
    try:
        for item in directory.iterdir():
            if item.is_dir() or item.name.startswith('.'):
                continue
            ext = item.suffix.lstrip('.').lower()
            cat = EXT_TO_CATEGORY.get(ext, 'other')
            base_name = clean_media_base_name(item.stem)
            group_key = extract_group_key(item.stem)
            mtime = item.stat().st_mtime
            file_list.append({
                'path': item, 'filename': item.name, 'stem': item.stem,
                'base_name': base_name, 'group_key': group_key,
                'ext': ext, 'category': cat, 'mtime': mtime
            })
    except Exception as e:
        return f"扫描文件夹出错: {e}", ""

    if not file_list:
        return "💡 该目录中没有可处理的文件！", str(parent_dir)

    cluster_groups = {}
    for f in file_list:
        cluster_groups.setdefault(f['group_key'], []).append(f)

    to_keep = []
    to_archive = []
    exempt_count = 0

    for g_key, group_items in cluster_groups.items():
        if len(group_items) == 1:
            to_keep.append(group_items[0])
            exempt_count += 1
            continue

        if retain_filter != "all":
            matched_items = [item for item in group_items if item['category'] == retain_filter]
            if matched_items:
                matched_items.sort(key=lambda x: x['mtime'], reverse=True)
                to_keep.append(matched_items[0])
                for old in matched_items[1:]:
                    to_archive.append(old)
                for non_matched in group_items:
                    if non_matched['category'] != retain_filter:
                        to_archive.append(non_matched)
            else:
                group_items.sort(key=lambda x: x['mtime'], reverse=True)
                to_keep.append(group_items[0])
                for old in group_items[1:]:
                    to_archive.append(old)
        else:
            sub_groups = {}
            for f in group_items:
                if mode_choice.startswith("A"):
                    sub_k = (f['base_name'], f['ext'])
                elif mode_choice.startswith("B"):
                    sub_k = (f['base_name'], f['category'])
                else:
                    sub_k = f['base_name']
                sub_groups.setdefault(sub_k, []).append(f)

            for s_k, s_files in sub_groups.items():
                s_files.sort(key=lambda x: x['mtime'], reverse=True)
                to_keep.append(s_files[0])
                for old in s_files[1:]:
                    to_archive.append(old)

    if not to_archive:
        return f"🎉 扫描完毕！共检查 {len(file_list)} 个文件（其中 {exempt_count} 个独立无冲突文件已豁免保护），无需移动归档。", str(parent_dir)

    success_count = 0
    log_details = []
    for item in to_archive:
        cat_name = item['category']
        backup_folder_name = f"{cat_name}_backup"
        target_dir = parent_dir / backup_folder_name
        target_dir.mkdir(parents=True, exist_ok=True)

        target_file_path = get_unique_target_path(target_dir, item['filename'])
        shutil.move(str(item['path']), str(target_file_path))
        success_count += 1
        log_details.append(f" 📦 归档: [{item['filename']}] ➡️ [{backup_folder_name}/]")

    filter_desc = f"【指定优先保留: {retain_filter.upper()}】" if retain_filter != 'all' else "【保留全部大类】"
    summary_log = [
        f"✅ 媒体整理完成！{filter_desc}",
        f"📊 总文件数: {len(file_list)} | 🟢 原地保留: {len(to_keep)} (含 {exempt_count} 个无冲突独立文件) | 📦 移动归档: {success_count}",
        f"📁 备份文件已自动分发至同级备份目录: {parent_dir}",
        "-" * 45,
        "【归档详情列表】:"
    ] + log_details

    return "\n".join(summary_log), str(parent_dir)

# ==========================================
# 3. 剪映草稿处理核心算法
# ==========================================
def scan_jianying_projects(draft_dir):
    clean_dir = normalize_path(draft_dir)
    if not clean_dir or not os.path.exists(clean_dir):
        return []
    try:
        folders = []
        for entry in os.listdir(clean_dir):
            full_path = os.path.join(clean_dir, entry)
            if os.path.isdir(full_path) and not entry.startswith('.'):
                folders.append(str(entry))
        return sorted(folders, key=lambda s: str(s).lower())
    except Exception as e:
        print(f"扫描草稿目录错误: {e}")
        return []

def get_draft_json_file(project_dir):
    p1 = os.path.join(project_dir, "draft_info.json")
    if os.path.exists(p1): return p1
    p2 = os.path.join(project_dir, "draft_content.json")
    if os.path.exists(p2): return p2
    return p1

def backup_draft_json(json_path, tag="backup"):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{json_path}.{tag}_{ts}.json"
    shutil.copy2(json_path, backup_path)
    return backup_path

def inspect_draft_aspect_ratio(draft_dir, project_name):
    clean_dir = normalize_path(draft_dir)
    if not clean_dir or not project_name:
        return -600, 8.0, 115, 30
    project_dir = os.path.join(clean_dir, str(project_name))
    draft_json_path = get_draft_json_file(project_dir)
    if os.path.exists(draft_json_path):
        try:
            with open(draft_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            canvas_cfg = data.get("canvas_config", {})
            width = canvas_cfg.get("width", 1080)
            height = canvas_cfg.get("height", 1920)
            is_vertical = (height > width) or (canvas_cfg.get("ratio") == "9:16")
            if is_vertical:
                return -600, 8.0, 115, 30
            else:
                return -380, 5.0, 100, 30
        except Exception:
            pass
    return -600, 8.0, 115, 30

def resolve_jianying_material_path(raw_path: str, project_dir: str):
    """
    自适应兼容两种素材模式：
    1. 复制至草稿（带 ##_draftpath_placeholder_xxx_## 占位符）
    2. 保留在原有位置（外部真实绝对路径）
    返回: (真实可读写的物理路径, 原始占位符前缀/None)
    """
    if not raw_path:
        return "", None
    
    placeholder_match = re.search(r'(##_draftpath_placeholder_[^#]+_##)', raw_path)
    placeholder_token = placeholder_match.group(1) if placeholder_match else None

    if placeholder_token:
        # 模式一：复制至草稿 -> 还原为工程内的真实路径
        real_path = raw_path.replace(placeholder_token, project_dir)
        return normalize_path(real_path), placeholder_token
    else:
        # 模式二：保留在原有位置 -> 直接使用原生路径
        return normalize_path(raw_path), None

def core_align_media_logic(draft_dir, project_name, video_mode="stretch_08_pingpong", snap_audio_boundary=True):
    """
    图文/视频轨道自动对齐
    1. 首分镜顶头(0)
    2. 每个分镜的终点绝对以【下一句字幕起点】或【音频真实断点】为收刀线，绝不擅自捅到全片尾巴！
    3. 智能锁定分片最多的真正字幕轨道
    """
    clean_dir = normalize_path(draft_dir)
    if not clean_dir or not project_name:
        yield "❌ 请选择剪映草稿目录和工程名称！"
        return
    
    project_dir = os.path.join(clean_dir, str(project_name))
    draft_json_path = get_draft_json_file(project_dir)
    if not os.path.exists(draft_json_path):
        yield f"❌ 未在选定工程中找到草稿文件: {project_dir}"
        return
    local_res_dir = os.path.join(project_dir, "Resources", "local")
    os.makedirs(local_res_dir, exist_ok=True)
    backup_path = backup_draft_json(draft_json_path, "align_bak")
    with open(draft_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    tracks = data.get("tracks", [])
    video_track = next((t for t in tracks if t.get("type") == "video"), None)
    text_tracks = [t for t in tracks if t.get("type") == "text" and len(t.get("segments", [])) > 0]
    if not video_track or not text_tracks:
        yield "❌ 错误：草稿中必须包含至少一条【主视频/图片轨道】和一条【有效字幕轨道】！"
        return
    # 1. 扫描所有音频物理片段
    raw_audio_clips = []
    for t in tracks:
        if t.get("type") == "audio":
            for seg in t.get("segments", []):
                tg = seg.get("target_timerange", {})
                st = int(tg.get("start", 0))
                dt = int(tg.get("duration", 0))
                if dt > 0:
                    raw_audio_clips.append({"start": st, "end": st + dt})
    raw_audio_clips.sort(key=lambda x: x["start"])
    # 2. 纯粹直连：锁定唯一的主字幕轨作为标尺
    if len(text_tracks) > 1:
        text_track = max(text_tracks, key=lambda t: len(t.get("segments", [])))
    else:
        text_track = text_tracks[0]
    v_segs = sorted(video_track.get("segments", []), key=lambda s: int(s.get("target_timerange", {}).get("start", 0)))
    t_segs = sorted(text_track.get("segments", []), key=lambda s: int(s.get("target_timerange", {}).get("start", 0)))
    num_pairs = min(len(v_segs), len(t_segs))
    if num_pairs == 0:
        yield "❌ 未找到可对齐的片段！"
        return
    mat_videos_dict = {v["id"]: v for v in data.get("materials", {}).get("videos", [])}
    mat_speeds_dict = {s["id"]: s for s in data.get("materials", {}).get("speeds", [])}
    def set_speed_material(seg, speed_val):
        speed_mat = None
        for ref in seg.get("extra_material_refs", []):
            if ref in mat_speeds_dict:
                speed_mat = mat_speeds_dict[ref]
                break
        if not speed_mat:
            speed_id = str(uuid.uuid4()).upper()
            speed_mat = {"curve_speed": None, "id": speed_id, "mode": 0, "speed": float(speed_val), "type": "speed"}
            data.setdefault("materials", {}).setdefault("speeds", []).append(speed_mat)
            seg.setdefault("extra_material_refs", []).append(speed_id)
        else:
            speed_mat["speed"] = float(speed_val)
        seg["speed"] = float(speed_val)
    # 3. 核心：计算每个分镜的严格物理区间
    computed_spans = []
    for i in range(num_pairs):
        cur_t_st = int(t_segs[i].get("target_timerange", {}).get("start", 0))
        cur_t_dt = int(t_segs[i].get("target_timerange", {}).get("duration", 1000000))
        
        # 终点首先看有没有下一句字幕（以全部字幕为准，绝不仅看视频数量！）
        if i < len(t_segs) - 1:
            next_t_st = int(t_segs[i+1].get("target_timerange", {}).get("start", cur_t_st + cur_t_dt))
        else:
            next_t_st = cur_t_st + cur_t_dt
        # 起点计算：第0个死死顶头0；其余严格以字幕或新音频起始为界
        if i == 0:
            seg_start = 0
        else:
            seg_start = cur_t_st
            if snap_audio_boundary and raw_audio_clips:
                prev_base = int(t_segs[i-1].get("target_timerange", {}).get("start", 0))
                for clip in raw_audio_clips:
                    if prev_base < clip["start"] <= cur_t_st:
                        seg_start = clip["start"]
                        break
        # 终点默认吸附到下一句字幕头
        seg_end = next_t_st
        # 音频截断判断：如果在 [seg_start, seg_end] 之间音频结束了，必须在该音频尾截断！
        if snap_audio_boundary and raw_audio_clips:
            possible_cuts = []
            for clip in raw_audio_clips:
                if seg_start < clip["end"] < seg_end:
                    possible_cuts.append(clip["end"])
                if seg_start < clip["start"] < seg_end:
                    possible_cuts.append(clip["start"])
            if possible_cuts:
                seg_end = min(possible_cuts)
        if seg_end <= seg_start:
            seg_end = seg_start + max(500000, cur_t_dt)
        computed_spans.append((int(seg_start), int(seg_end)))
    mod_count = 0
    pingpong_rendered_count = 0
    new_video_segments = []
    live_logs = [f"🚀 正在分析草稿分镜 (共 {num_pairs} 对)...已锁定严格字幕间隙标尺"]
    yield "\n".join(live_logs)
    # 4. 执行应用与 PingPong (按需渲染，绝不过度延伸)
    for i in range(num_pairs):
        v = v_segs[i]
        mat_id = v.get("material_id")
        video_mat = mat_videos_dict.get(mat_id, {})
        mat_type = video_mat.get("type", "photo")
        video_path, placeholder_token = resolve_jianying_material_path(video_mat.get("path", ""), project_dir)
        real_probe_dur = get_ffprobe_duration_us(video_path) if (video_path and os.path.exists(video_path)) else None
        raw_vid_dur = int(real_probe_dur or video_mat.get("duration", 3000000))
        seg_start, seg_end = computed_spans[i]
        dur = max(1, seg_end - seg_start)
        if mat_type == "photo":
            v["target_timerange"] = {"start": seg_start, "duration": dur}
            v["source_timerange"] = {"start": 0, "duration": dur}
            if "common_keyframes" in v and isinstance(v["common_keyframes"], list):
                for prop in v["common_keyframes"]:
                    kfs = prop.get("keyframe_list", [])
                    if kfs:
                        kfs[-1]["time_offset"] = int(dur)
            new_video_segments.append(v)
            mod_count += 1
        else:
            # 模式 D: 0.8x + PingPong
            if video_mode == "stretch_08_pingpong":
                fixed_speed = 0.8
                source_needed = int(dur * fixed_speed)
                if raw_vid_dur >= source_needed:
                    v["target_timerange"] = {"start": seg_start, "duration": dur}
                    v["source_timerange"] = {"start": 0, "duration": source_needed}
                    set_speed_material(v, fixed_speed)
                    new_video_segments.append(v)
                    mod_count += 1
                else:
                    repeats = max(2, math.ceil(source_needed / raw_vid_dur))
                    raw_s = raw_vid_dur / 1000000.0
                    tgt_s = dur / 1000000.0
                    live_logs.append(f"⚠️ [分镜 {i+1}] 0.8x不足({raw_s:.2f}s < 目标{tgt_s:.2f}s) -> PingPong({repeats}片往复)...")
                    yield "\n".join(live_logs)
                    if not os.path.exists(video_path):
                        live_logs.append(f"❌ 警告: 找不到源视频文件: {video_path}")
                        yield "\n".join(live_logs)
                    else:
                        try:
                            pingpong_file = build_pingpong_video(video_path, repeats)
                            new_dur = raw_vid_dur * repeats
                            if placeholder_token and project_dir in pingpong_file:
                                video_mat["path"] = pingpong_file.replace(project_dir, placeholder_token)
                            else:
                                video_mat["path"] = pingpong_file
                            video_mat["duration"] = int(new_dur)
                            video_mat["material_name"] = os.path.basename(pingpong_file)
                            raw_vid_dur = new_dur
                            pingpong_rendered_count += 1
                            live_logs.append(f"  ✅ [分镜 {i+1}] FFmpeg 渲染成功！新时长: {new_dur/1000000:.2f}s")
                            yield "\n".join(live_logs)
                        except Exception as e:
                            live_logs.append(f"  ❌ FFmpeg 渲染失败: {e}")
                            yield "\n".join(live_logs)
                    v["target_timerange"] = {"start": seg_start, "duration": dur}
                    v["source_timerange"] = {"start": 0, "duration": source_needed}
                    set_speed_material(v, fixed_speed)
                    new_video_segments.append(v)
                    mod_count += 1
            # 模式 C: 1.0x + PingPong
            elif video_mode == "pingpong_1x":
                if raw_vid_dur >= dur:
                    v["target_timerange"] = {"start": seg_start, "duration": dur}
                    v["source_timerange"] = {"start": 0, "duration": dur}
                    set_speed_material(v, 1.0)
                    new_video_segments.append(v)
                    mod_count += 1
                else:
                    repeats = max(2, math.ceil(dur / raw_vid_dur))
                    raw_s = raw_vid_dur / 1000000.0
                    tgt_s = dur / 1000000.0
                    live_logs.append(f"⚠️ [分镜 {i+1}] 视频不足({raw_s:.2f}s < 目标{tgt_s:.2f}s) -> PingPong({repeats}片往复)...")
                    yield "\n".join(live_logs)
                    if not os.path.exists(video_path):
                        live_logs.append(f"❌ 警告: 找不到源视频文件: {video_path}")
                        yield "\n".join(live_logs)
                    else:
                        try:
                            pingpong_file = build_pingpong_video(video_path, repeats)
                            new_dur = raw_vid_dur * repeats
                            if placeholder_token and project_dir in pingpong_file:
                                video_mat["path"] = pingpong_file.replace(project_dir, placeholder_token)
                            else:
                                video_mat["path"] = pingpong_file
                            video_mat["duration"] = int(new_dur)
                            video_mat["material_name"] = os.path.basename(pingpong_file)
                            raw_vid_dur = new_dur
                            pingpong_rendered_count += 1
                            live_logs.append(f"  ✅ [分镜 {i+1}] FFmpeg 渲染成功！新时长: {new_dur/1000000:.2f}s")
                            yield "\n".join(live_logs)
                        except Exception as e:
                            live_logs.append(f"  ❌ FFmpeg 渲染失败: {e}")
                            yield "\n".join(live_logs)
                    v["target_timerange"] = {"start": seg_start, "duration": dur}
                    v["source_timerange"] = {"start": 0, "duration": dur}
                    set_speed_material(v, 1.0)
                    new_video_segments.append(v)
                    mod_count += 1
            # 模式 A: 纯降速
            elif video_mode == "slow_down":
                if raw_vid_dur >= dur:
                    v["target_timerange"] = {"start": seg_start, "duration": dur}
                    v["source_timerange"] = {"start": 0, "duration": dur}
                    set_speed_material(v, 1.0)
                else:
                    calc_speed = raw_vid_dur / dur
                    v["target_timerange"] = {"start": seg_start, "duration": dur}
                    v["source_timerange"] = {"start": 0, "duration": raw_vid_dur}
                    set_speed_material(v, calc_speed)
                new_video_segments.append(v)
                mod_count += 1
            # 模式 B: 原速循环复制
            elif video_mode == "loop_copy":
                if raw_vid_dur >= dur:
                    v["target_timerange"] = {"start": seg_start, "duration": dur}
                    v["source_timerange"] = {"start": 0, "duration": dur}
                    set_speed_material(v, 1.0)
                    new_video_segments.append(v)
                    mod_count += 1
                else:
                    rem_dur = dur
                    sub_start = seg_start
                    while rem_dur > 0:
                        take_dur = min(rem_dur, raw_vid_dur)
                        clone_seg = json.loads(json.dumps(v))
                        clone_seg["id"] = str(uuid.uuid4()).upper()
                        clone_seg["target_timerange"] = {"start": sub_start, "duration": take_dur}
                        clone_seg["source_timerange"] = {"start": 0, "duration": take_dur}
                        set_speed_material(clone_seg, 1.0)
                        new_video_segments.append(clone_seg)
                        sub_start += take_dur
                        rem_dur -= take_dur
                        mod_count += 1
    max_track_end = max([int(s["target_timerange"]["start"]) + int(s["target_timerange"]["duration"]) for s in new_video_segments], default=0)
    curr_start = max_track_end
    if len(v_segs) > num_pairs:
        for i in range(num_pairs, len(v_segs)):
            v = v_segs[i]
            d = int(v.get("target_timerange", {}).get("duration", 1000000))
            v["target_timerange"]["start"] = int(curr_start)
            curr_start += d
            new_video_segments.append(v)
            mod_count += 1
    video_track["segments"] = new_video_segments
    max_track_end = max([int(s["target_timerange"]["start"]) + int(s["target_timerange"]["duration"]) for s in new_video_segments], default=0)
    data["duration"] = int(max(data.get("duration", 0), max_track_end))
    with open(draft_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    snap_msg = "（已按音频物理断点严格截断对齐）" if snap_audio_boundary else ""
    pingpong_msg = f"\n🏓 PingPong 统计: 共对 {pingpong_rendered_count} 个素材完成了往复渲染填满，主轨分镜数保持 1:1（共 {len(new_video_segments)} 个分镜）！"
    live_logs.append(f"\n🎉 全部对齐成功！{snap_msg}{pingpong_msg}\n- 对齐片段数: {mod_count}\n- 视频轨道当前总长度: {max_track_end/1000000:.2f}秒\n- 自动备份: {os.path.basename(backup_path)}")
    yield "\n".join(live_logs)

def core_add_keyframes_only_logic(draft_dir, project_name, zoom_min, zoom_max, pan_mag, auto_blur_bg=True):
    clean_dir = normalize_path(draft_dir)
    if not clean_dir or not project_name:
        return "请选择剪映草稿目录和工程名称！"
    
    project_dir = os.path.join(clean_dir, str(project_name))
    draft_json_path = get_draft_json_file(project_dir)
    if not os.path.exists(draft_json_path):
        return f"未找到工程配置文件: {draft_json_path}"

    backup_path = backup_draft_json(draft_json_path, "kf_bak")
    with open(draft_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    tracks = data.get("tracks", [])
    video_track = next((t for t in tracks if t.get("type") == "video"), None)
    if not video_track:
        return "错误：未找到主视频/图片轨道！"

    mat_videos_dict = {v["id"]: v for v in data.get("materials", {}).get("videos", [])}
    effects = ['zoom_in', 'zoom_out', 'pan_ltr', 'pan_rtl', 'pan_ttb', 'pan_btt']
    mod_count, skipped_videos = 0, 0

    def make_kf(offset, val):
        return {
            "curveType": "Line", "graphID": "", "id": uuid.uuid4().hex,
            "left_control": {"x": 0.0, "y": 0.0}, "right_control": {"x": 0.0, "y": 0.0},
            "time_offset": int(offset), "values": [float(val)]
        }

    for seg in video_track.get("segments", []):
        mat_id = seg.get("material_id")
        video_mat = mat_videos_dict.get(mat_id, {})
        if video_mat.get("type") == "video":
            skipped_videos += 1
            continue

        dur = seg.get("target_timerange", {}).get("duration", 0)
        if dur <= 0: continue

        eff = random.choice(effects)
        start_sx, end_sx = 1.0, 1.0
        start_sy, end_sy = 1.0, 1.0
        start_px, end_px = 0.0, 0.0
        start_py, end_py = 0.0, 0.0

        if eff == 'zoom_in':
            end_sx = end_sy = random.uniform(zoom_min, zoom_max)
        elif eff == 'zoom_out':
            start_sx = start_sy = random.uniform(zoom_min, zoom_max)
        elif eff == 'pan_ltr':
            start_px, end_px = -pan_mag, pan_mag
        elif eff == 'pan_rtl':
            start_px, end_px = pan_mag, -pan_mag
        elif eff == 'pan_ttb':
            start_py, end_py = pan_mag, -pan_mag
        elif eff == 'pan_btt':
            start_py, end_py = -pan_mag, pan_mag

        prop_map = {
            "KFTypeScaleX": (start_sx, end_sx), "KFTypeScaleY": (start_sy, end_sy),
            "KFTypePositionX": (start_px, end_px), "KFTypePositionY": (start_py, end_py)
        }

        seg["common_keyframes"] = []
        for prop_name, (s_val, e_val) in prop_map.items():
            seg["common_keyframes"].append({
                "id": uuid.uuid4().hex,
                "keyframe_list": [make_kf(0, s_val), make_kf(dur, e_val)],
                "material_id": "", "property_type": prop_name
            })
        mod_count += 1

    if auto_blur_bg:
        for cv in data.get("materials", {}).get("canvases", []):
            cv["type"] = "canvas_blur"
            cv["blur"] = 0.0625

    with open(draft_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    bg_msg = "（已开启高斯模糊背景填充）" if auto_blur_bg else ""
    return f"✨ 运镜处理完成！\n- 成功为 {mod_count} 个图片片段生成随机关键帧 {bg_msg}\n- 自动识别并跳过 {skipped_videos} 个原生视频素材\n- 自动备份: {os.path.basename(backup_path)}"

def core_subtitle_styling_logic(draft_dir, project_name, sub_pixel_y=-600, font_size=8.0, scale_pct=115, stroke_val=30):
    clean_dir = normalize_path(draft_dir)
    if not clean_dir or not project_name:
        return "请选择剪映草稿目录和工程名称！"
    
    project_dir = os.path.join(clean_dir, str(project_name))
    draft_json_path = get_draft_json_file(project_dir)
    if not os.path.exists(draft_json_path):
        return f"未找到工程配置文件: {draft_json_path}"

    backup_path = backup_draft_json(draft_json_path, "sub_style_bak")
    with open(draft_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    tracks = data.get("tracks", [])
    canvas_cfg = data.get("canvas_config", {})
    height = float(canvas_cfg.get("height", 1920))
    
    norm_y = float(sub_pixel_y) / height
    target_scale = float(scale_pct) / 100.0
    stroke_width_val = float(stroke_val) * 0.002
    target_font_size = float(font_size)

    mod_text_count = 0
    for txt in data.get("materials", {}).get("texts", []):
        txt["font_size"] = target_font_size
        txt["text_color"] = "#ffffff"
        txt["text_alpha"] = 1.0
        txt["border_alpha"] = 1.0
        txt["border_color"] = "#000000"
        txt["border_width"] = stroke_width_val
        txt["alignment"] = 1                   # 居中对齐
        txt["preset_has_set_alignment"] = True # 预设居中生效
        txt["typesetting"] = 0                 # 横排
        txt["use_effect_default_color"] = True

        raw_content = txt.get("content", "")
        if raw_content:
            try:
                c_data = json.loads(raw_content)
                raw_text_str = c_data.get("text", "")
                text_len = len(raw_text_str)
                c_data["styles"] = [{
                    "fill": {"content": {"solid": {"color": [1.0, 1.0, 1.0]}}},
                    "range": [0, text_len],
                    "strokes": [{"width": stroke_width_val, "content": {"solid": {"color": [0.0, 0.0, 0.0]}}}],
                    "useLetterColor": True,
                    "size": target_font_size,
                    "font": {"path": "/Applications/VideoFusion-macOS.app/Contents/Resources/Font/SystemFont/zh-hans.ttf", "id": ""}
                }]
                txt["content"] = json.dumps(c_data, ensure_ascii=False)
            except Exception:
                pass
        mod_text_count += 1

    seg_count = 0
    for t in tracks:
        if t.get("type") == "text":
            for seg in t.get("segments", []):
                clip = seg.setdefault("clip", {})
                clip["alpha"] = 1.0
                clip["flip"] = {"horizontal": False, "vertical": False}
                clip["rotation"] = 0.0
                clip["scale"] = {"x": target_scale, "y": target_scale}
                clip["transform"] = {"x": 0.0, "y": norm_y}
                seg_count += 1

    with open(draft_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return (
        f"💬 字幕效果处理完成！\n"
        f"- 统一设置 {mod_text_count} 条字幕为标准【白底黑框】\n"
        f"- 剪映界面实测参数校准: Y = {sub_pixel_y} (内部 norm_y: {norm_y:.4f})\n"
        f"- 描边粗细: {stroke_val} (内部 width: {stroke_width_val:.4f}) | 字号: {target_font_size} | 缩放: {scale_pct}%\n"
        f"- 已将 {seg_count} 个字幕片段水平完美居中 (X=0.0)\n"
        f"- 自动备份: {os.path.basename(backup_path)}"
    )

def core_manage_video_audio_logic(draft_dir, project_name, action_type):
    clean_dir = normalize_path(draft_dir)
    if not clean_dir or not project_name:
        return "请选择剪映草稿目录和工程名称！"

    project_dir = os.path.join(clean_dir, str(project_name))
    draft_json_path = get_draft_json_file(project_dir)
    if not os.path.exists(draft_json_path):
        return f"未找到工程配置文件: {draft_json_path}"

    backup_path = backup_draft_json(draft_json_path, "audio_mgr_bak")
    with open(draft_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    tracks = data.get("tracks", [])
    video_track = next((t for t in tracks if t.get("type") == "video"), None)
    if not video_track:
        return "错误：未在草稿中找到视频轨道！"

    mat_videos_dict = {v["id"]: v for v in data.get("materials", {}).get("videos", [])}
    new_audio_segments = []
    processed_count = 0

    for seg in video_track.get("segments", []):
        mat_id = seg.get("material_id")
        video_mat = mat_videos_dict.get(mat_id, {})
        
        if video_mat.get("type") == "video":
            processed_count += 1
            if action_type == 'extract_only':
                audio_id = str(uuid.uuid4()).upper()
                audio_entry = {
                    "app_id": 0, "category_id": "", "category_name": "local", "check_flag": 1,
                    "duration": video_mat.get("duration", 0), "id": audio_id,
                    "name": video_mat.get("material_name", "视频原声") + " [提取音频]",
                    "path": video_mat.get("path", ""), "type": "extract_music", "wave_points": []
                }
                data.setdefault("materials", {}).setdefault("audios", []).append(audio_entry)

                speed_id = str(uuid.uuid4()).upper()
                cur_speed = seg.get("speed", 1.0)
                speed_entry = {"curve_speed": None, "id": speed_id, "mode": 0, "speed": float(cur_speed), "type": "speed"}
                data.setdefault("materials", {}).setdefault("speeds", []).append(speed_entry)

                audio_seg = {
                    "caption_info": None, "cartoon": False, "clip": None, "common_keyframes": [],
                    "enable_adjust": False, "enable_color_correct_adjust": False, "enable_color_curves": True,
                    "enable_color_match_adjust": False, "enable_color_wheels": True, "enable_lut": False,
                    "enable_smart_color_adjust": False, "extra_material_refs": [speed_id], "group_id": "",
                    "id": str(uuid.uuid4()).upper(), "intensifies_audio": False, "is_placeholder": False,
                    "is_tone_modify": False, "keyframe_refs": [], "last_nonzero_volume": 1.0,
                    "material_id": audio_id, "render_index": 0,
                    "responsive_layout": {"enable": False, "horizontal_pos_layout": 0, "size_layout": 0, "target_follow": "", "vertical_pos_layout": 0},
                    "reverse": False, "source_timerange": seg.get("source_timerange"),
                    "speed": float(cur_speed), "target_timerange": seg.get("target_timerange"),
                    "template_id": "", "template_scene": "default", "track_attribute": 0,
                    "track_render_index": 0, "uniform_scale": None, "visible": True, "volume": 1.0
                }
                new_audio_segments.append(audio_seg)

            seg["volume"] = 0.0
            seg["last_nonzero_volume"] = 0.0

    if processed_count == 0:
        return "提示：当前轨道中未发现视频文件素材（全部为图片）！"

    if new_audio_segments:
        new_track = {
            "attribute": 0, "flag": 0, "id": str(uuid.uuid4()).upper(),
            "is_default_name": True, "name": "Extracted Video Audio",
            "segments": new_audio_segments, "type": "audio"
        }
        data["tracks"].append(new_track)

    with open(draft_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if action_type == 'extract_only':
        return f"🎵 原声分离成功！已将 {processed_count} 个视频音频提取至全新独立音轨。\n- 自动备份: {os.path.basename(backup_path)}"
    else:
        return f"🗑️ 原声去除成功！已静音/移除 {processed_count} 个视频片段自带的声音。\n- 自动备份: {os.path.basename(backup_path)}"

def core_generate_audio_title_track(draft_dir, project_name, split_char=".", font_size_1=12, font_size_2=9, line_spacing=-0.23, duration_sec=3.0):
    clean_dir = normalize_path(draft_dir)
    if not clean_dir or not project_name:
        return "请选择剪映草稿目录和工程名称！"
    
    project_dir = os.path.join(clean_dir, str(project_name))
    draft_json_path = get_draft_json_file(project_dir)
    if not os.path.exists(draft_json_path):
        return f"未找到工程配置文件: {draft_json_path}"
    backup_path = backup_draft_json(draft_json_path, "title_bak")
    with open(draft_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    audio_materials = {a["id"]: a.get("name", "") for a in data.get("materials", {}).get("audios", [])}
    tracks = data.get("tracks", [])
    audio_tracks = [t for t in tracks if t.get("type") == "audio"]
    if not audio_tracks:
        return "错误：工程中未找到任何音频轨道！"
        
    audio_segments = []
    for t in audio_tracks:
        for seg in t.get("segments", []):
            audio_segments.append(seg)
    audio_segments.sort(key=lambda s: int(s.get("target_timerange", {}).get("start", 0)))

    processed_filenames = set()
    title_items = []
    for seg in audio_segments:
        mat_id = seg.get("material_id")
        filename = audio_materials.get(mat_id, "")
        if not filename or filename in processed_filenames:
            continue
        processed_filenames.add(filename)
        start_time = int(seg.get("target_timerange", {}).get("start", 0))
        base_name = os.path.splitext(filename)[0]
        if split_char and split_char in base_name:
            base_name = base_name.split(split_char, 1)[1]
        if "-" in base_name:
            parts = base_name.split("-", 1)
            line1, line2 = parts[0].strip(), parts[1].strip()
            full_text = f"{line1}\n{line2}"
            is_two_lines = True
            len1, len2 = len(line1), len(line2)
        else:
            full_text = base_name.strip()
            is_two_lines = False
            len1, len2 = len(full_text), 0
        title_items.append({
            "start": start_time, "text": full_text,
            "is_two_lines": is_two_lines, "len1": len1, "len2": len2
        })
    if not title_items:
        return "未发现有效的音频素材文件名！"
    dur_us = int(duration_sec * 1000000)
    new_text_segments = []
    for item in title_items:
        text_id = str(uuid.uuid4()).upper()
        anim_id = str(uuid.uuid4()).upper()
        seg_id = str(uuid.uuid4()).upper()
        if item["is_two_lines"]:
            styles = [
                {"fill": {"content": {"solid": {"color": [1, 1, 1]}}}, "font": {"id": "", "path": "/Applications/VideoFusion-macOS.app/Contents/Resources/Font/SystemFont/zh-hans.ttf"}, "range": [0, item["len1"]], "size": float(font_size_1), "strokes": [{"content": {"solid": {"color": [0, 0, 0]}}, "width": 0.08}], "useLetterColor": True},
                {"fill": {"content": {"solid": {"color": [1, 1, 1]}}}, "font": {"id": "", "path": "/Applications/VideoFusion-macOS.app/Contents/Resources/Font/SystemFont/zh-hans.ttf"}, "range": [item["len1"], item["len1"] + 1], "size": float(font_size_1), "strokes": [{"content": {"solid": {"color": [0, 0, 0]}}, "width": 0.08}], "useLetterColor": True},
                {"fill": {"content": {"solid": {"color": [1, 1, 1]}}}, "font": {"id": "", "path": "/Applications/VideoFusion-macOS.app/Contents/Resources/Font/SystemFont/zh-hans.ttf"}, "range": [item["len1"] + 1, item["len1"] + 1 + item["len2"]], "size": float(font_size_2), "strokes": [{"content": {"solid": {"color": [0, 0, 0]}}, "width": 0.08}], "useLetterColor": True}
            ]
            cur_line_spacing = float(line_spacing)
            main_font_size = float(font_size_2)
        else:
            styles = [
                {"fill": {"content": {"solid": {"color": [1, 1, 1]}}}, "font": {"id": "", "path": "/Applications/VideoFusion-macOS.app/Contents/Resources/Font/SystemFont/zh-hans.ttf"}, "range": [0, item["len1"]], "size": float(font_size_1), "strokes": [{"content": {"solid": {"color": [0, 0, 0]}}, "width": 0.08}], "useLetterColor": True}
            ]
            cur_line_spacing = 0.02
            main_font_size = float(font_size_1)
        content_json_str = json.dumps({"styles": styles, "text": item["text"]}, ensure_ascii=False)
        text_material_entry = {
            "add_type": 0, "alignment": 1, "background_alpha": 1.0, "background_color": "#000000",
            "background_height": 0.14, "background_horizontal_offset": 0.0, "background_round_radius": 0.0,
            "background_style": 0, "background_vertical_offset": 0.0, "background_width": 0.14,
            "base_content": "", "bold_width": 0.0, "border_alpha": 1.0, "border_color": "#000000",
            "border_width": 0.08, "caption_template_info": {"category_id": "", "category_name": "", "effect_id": "", "is_new": False, "path": "", "request_id": "", "resource_id": "", "resource_name": "", "source_platform": 0},
            "check_flag": 15, "combo_info": {"text_templates": []}, "content": content_json_str,
            "fixed_height": -1.0, "fixed_width": -1.0, "font_category_id": "", "font_category_name": "",
            "font_id": "", "font_name": "", "font_path": "/Applications/VideoFusion-macOS.app/Contents/Resources/Font/SystemFont/zh-hans.ttf",
            "font_resource_id": "", "font_size": main_font_size, "font_source_platform": 0, "font_team_id": "",
            "font_title": "none", "font_url": "", "fonts": [], "force_apply_line_max_width": False,
            "global_alpha": 1.0, "group_id": "", "has_shadow": False, "id": text_id, "initial_scale": 1.0,
            "inner_padding": -1.0, "is_rich_text": False, "italic_degree": 0, "ktv_color": "", "language": "",
            "layer_weight": 1, "letter_spacing": 0.0, "line_feed": 1, "line_max_width": 0.82,
            "line_spacing": cur_line_spacing, "multi_language_current": "none", "name": "", "original_size": [],
            "preset_category": "", "preset_category_id": "", "preset_has_set_alignment": True, "preset_id": "",
            "preset_index": 0, "preset_name": "", "recognize_task_id": "", "recognize_type": 0, "relevance_segment": [],
            "shadow_alpha": 0.9, "shadow_angle": -45.0, "shadow_color": "", "shadow_distance": 5.0,
            "shadow_point": {"x": 0.6363961030678928, "y": -0.6363961030678927}, "shadow_smoothing": 0.45,
            "shape_clip_x": False, "shape_clip_y": False, "source_from": "", "style_name": "", "sub_type": 0,
            "subtitle_keywords": None, "subtitle_template_original_fontsize": 0.0, "text_alpha": 1.0, "text_color": "#ffffff",
            "text_curve": None, "text_preset_resource_id": "", "text_size": 30, "text_to_audio_ids": [], "tts_auto_update": False,
            "type": "text", "typesetting": 0, "underline": False, "underline_offset": 0.22, "underline_width": 0.05,
            "use_effect_default_color": True, "words": {"end_time": [], "start_time": [], "text": []}
        }
        data.setdefault("materials", {}).setdefault("texts", []).append(text_material_entry)
        anim_entry = {"animations": [], "id": anim_id, "multi_language_current": "none", "type": "sticker_animation"}
        data.setdefault("materials", {}).setdefault("material_animations", []).append(anim_entry)
        seg_entry = {
            "caption_info": None, "cartoon": False,
            "clip": {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False}, "rotation": 0.0, "scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}},
            "common_keyframes": [], "enable_adjust": False, "enable_color_correct_adjust": False,
            "enable_color_curves": True, "enable_color_match_adjust": False, "enable_color_wheels": True,
            "enable_lut": False, "enable_smart_color_adjust": False,
            "extra_material_refs": [anim_id], "group_id": "", "hdr_settings": None,
            "id": seg_id, "intensifies_audio": False, "is_placeholder": False, "is_tone_modify": False,
            "keyframe_refs": [], "last_nonzero_volume": 1.0, "material_id": text_id, "render_index": 14500,
            "responsive_layout": {"enable": False, "horizontal_pos_layout": 0, "size_layout": 0, "target_follow": "", "vertical_pos_layout": 0},
            "reverse": False, "source_timerange": None, "speed": 1.0,
            "target_timerange": {"duration": dur_us, "start": item["start"]},
            "template_id": "", "template_scene": "default", "track_attribute": 0, "track_render_index": 2,
            "uniform_scale": {"on": True, "value": 1.0}, "visible": True, "volume": 1.0
        }
        new_text_segments.append(seg_entry)

    new_track = {
        "attribute": 0, "flag": 0, "id": str(uuid.uuid4()).upper(),
        "is_default_name": True, "name": "Audio Titles",
        "segments": new_text_segments, "type": "text"
    }
    data["tracks"].append(new_track)
    with open(draft_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return f"🎵 音频标题轨创建成功！\n- 新增 {len(new_text_segments)} 个标题卡片\n- 自动备份: {os.path.basename(backup_path)}"

# ==========================================
# 4. WebUI 界面构建
# ==========================================
cfg = load_config()
initial_projects = scan_jianying_projects(cfg.get("base_drafts_dir", ""))
saved_proj = str(cfg.get("last_selected_project", ""))
initial_proj_value = saved_proj if saved_proj in initial_projects else (initial_projects[0] if initial_projects else None)
init_y, init_size, init_scale, init_stroke = inspect_draft_aspect_ratio(cfg.get("base_drafts_dir", ""), initial_proj_value)

with gr.Blocks(title="智绘声影2.0+剪映自动视频工作台") as demo:
    gr.Markdown("# 🎙️ 智绘声影2.0+剪映自动视频工作台")
    
    with gr.Tabs():
        # ========================================================
        # 板块一：文本与媒体处理中心
        # ========================================================
        with gr.TabItem("✂️ 文本与媒体处理中心"):
            gr.Markdown("💡 **使用提示**：支持 Windows/Mac 复制的带引号完整文件路径，直接粘贴即可自动解析！")
            
            # --- 1. SRT 时长注入 ---
            gr.Markdown("### 📌 1. SRT 时间轴注入提示词时长 (ComfyUI 专用)")
            with gr.Row():
                with gr.Column(scale=1):
                    srt_path_in = gr.Textbox(label="SRT 文件路径 (支持带双引号路径粘贴)", placeholder="例如: \"F:\\CF\\01.srt\" 或 /Users/.../01.srt")
                    srt_time_in = gr.File(label="或者点击上传/拖入 SRT 文件", file_types=[".srt"])
                    prompt_path_in = gr.Textbox(label="提示词 TXT 路径 (支持带双引号路径粘贴)", placeholder="例如: \"F:\\CF\\prompt.txt\"")
                    prompt_txt_in = gr.File(label="或者点击上传/拖入 TXT 文本", file_types=[".txt"])
                    with gr.Row():
                        fps_select = gr.Dropdown(choices=["16", "24", "25", "30", "50", "60"], value="25", label="帧率 (FPS)")
                        unit_select = gr.Radio(choices=["帧数 (如 560f)", "秒数 (如 22.4s)"], value="帧数 (如 560f)", label="时长标记单位")
                    time_mult = gr.Slider(minimum=1.0, maximum=1.3, value=1.2, step=0.01, label="安全时长冗余系数 (默认 1.2x)")
                    origin_chk_1 = gr.Checkbox(value=True, label="在原目录生成 (通过路径输入有效，拖入上传则输出到 outputs/)")
                    with gr.Row():
                        inject_btn = gr.Button("⚡ 开始计算并注入", variant="primary", scale=2)
                        inject_open_btn = gr.Button("📂 打开生成目录", scale=1)
                with gr.Column(scale=1):
                    inject_log = gr.Textbox(label="比对与校验日志", lines=4)
                    inject_preview = gr.Textbox(label="生成文本内容预览 (可直接点击全选复制)", lines=6)
                    inject_out = gr.File(label="浏览器下载备用")
                    inject_saved_path = gr.State("")

            inject_btn.click(
                core_inject_srt_duration_to_prompts,
                inputs=[srt_path_in, srt_time_in, prompt_path_in, prompt_txt_in, fps_select, unit_select, time_mult, origin_chk_1],
                outputs=[inject_log, inject_preview, inject_out, inject_saved_path]
            )
            inject_open_btn.click(open_folder_in_explorer, inputs=[inject_saved_path], outputs=[])

            gr.Markdown("---")
            # --- 2. 字幕映射 ---
            gr.Markdown("### 📌 2. 字幕按字数映射对齐 (SRT + TXT)")
            with gr.Row():
                with gr.Column(scale=1):
                    srt_m_path = gr.Textbox(label="原始 SRT 文件路径 (支持带双引号路径粘贴)", placeholder="例如: \"F:\\CF\\source.srt\"")
                    srt_in = gr.File(label="或者点击上传/拖入 SRT 文件", file_types=[".srt"])
                    txt_m_path = gr.Textbox(label="校对 TXT 文件路径 (支持带双引号路径粘贴)", placeholder="例如: \"F:\\CF\\target.txt\"")
                    txt_in = gr.File(label="或者点击上传/拖入 TXT 文件", file_types=[".txt"])
                    origin_chk_2 = gr.Checkbox(value=True, label="在原目录生成 (通过路径输入有效，拖入上传则输出到 outputs/)")
                    with gr.Row():
                        merge_btn = gr.Button("🔄 开始映射对齐", variant="primary", scale=2)
                        merge_open_btn = gr.Button("📂 打开生成目录", scale=1)
                with gr.Column(scale=1):
                    merge_log = gr.Textbox(label="对齐统计日志", lines=4)
                    merge_preview = gr.Textbox(label="生成 SRT 字幕预览 (可直接点击全选复制)", lines=6)
                    merge_out = gr.File(label="浏览器下载备用")
                    merge_saved_path = gr.State("")

            merge_btn.click(
                core_merge_srt, 
                inputs=[srt_m_path, srt_in, txt_m_path, txt_in, origin_chk_2], 
                outputs=[merge_log, merge_preview, merge_out, merge_saved_path]
            )
            merge_open_btn.click(open_folder_in_explorer, inputs=[merge_saved_path], outputs=[])

            gr.Markdown("---")
            with gr.Row():
                # --- 3. 文本清洗 ---
                with gr.Column(variant="panel", scale=1):
                    gr.Markdown("### 📌 3. 文本符号清洗 (TTS 配音专用)")
                    clean_path_in = gr.Textbox(label="文稿 TXT 路径 (支持带双引号路径粘贴)", placeholder="例如: \"F:\\CF\\text.txt\"")
                    clean_in = gr.File(label="或点击上传/拖入文稿 TXT", file_types=[".txt"])
                    origin_chk_3 = gr.Checkbox(value=True, label="在原目录生成")
                    with gr.Row():
                        clean_btn = gr.Button("🧹 清洗标点符号", variant="primary", scale=2)
                        clean_open_btn = gr.Button("📂 打开所在目录", scale=1)
                    clean_log = gr.Textbox(label="清洗统计", lines=3)
                    clean_preview = gr.Textbox(label="清洗结果预览", lines=5)
                    clean_out = gr.File(label="浏览器下载备用")
                    clean_saved_path = gr.State("")

                    clean_btn.click(
                        core_process_text_no_marks, 
                        inputs=[clean_path_in, clean_in, origin_chk_3], 
                        outputs=[clean_log, clean_preview, clean_out, clean_saved_path]
                    )
                    clean_open_btn.click(open_folder_in_explorer, inputs=[clean_saved_path], outputs=[])

                # --- 4. 媒体文件智能整理 ---
                with gr.Column(variant="panel", scale=1):
                    gr.Markdown("### 📌 4. 媒体文件整理与去重备份 (留最新)")
                    gr.Markdown("💡 **安全规则**：仅对出现类似/冲突同名的一组文件做处理；**无竞争的独一份文件（如 02、03）绝对不挪动，安全保留！**")
                    media_folder_in = gr.Textbox(
                        label="待整理文件夹路径 (支持带双引号路径粘贴)", 
                        placeholder="例如: \"F:\\CF\\Resource\" 或 /Users/xxx/Documents/Resource"
                    )
                    with gr.Row():
                        media_filter_radio = gr.Radio(
                            choices=[
                                ("保留全部大类", "all"),
                                ("仅保留音频 (audio)", "audio"),
                                ("仅保留视频 (video)", "video"),
                                ("仅保留图片 (image)", "image"),
                                ("仅保留文档 (doc)", "doc")
                            ],
                            value="all",
                            label="🎯 目标保留文件类型"
                        )
                    media_mode_radio = gr.Radio(
                        choices=[
                            "选项A: 同扩展名清洗（同名txt只留最新，不影响jpg/mp3等）",
                            "选项B: 同大类清洗（同属audio/video/image/doc只留1个最新）",
                            "选项C: 全局唯一占位（不管格式类型，该名称全目录只留1个最新）"
                        ],
                        value="选项C: 全局唯一占位（不管格式类型，该名称全目录只留1个最新）",
                        label="去重策略规则"
                    )
                    with gr.Row():
                        clean_media_btn = gr.Button("🗂️ 执行媒体整理归档", variant="primary", scale=2)
                        clean_media_open_btn = gr.Button("📂 打开备份所在目录", scale=1)
                    media_clean_log = gr.Textbox(label="整理执行日志", lines=8)
                    media_backup_dir_state = gr.State("")

                    clean_media_btn.click(
                        core_clean_media_folder,
                        inputs=[media_folder_in, media_mode_radio, media_filter_radio],
                        outputs=[media_clean_log, media_backup_dir_state]
                    )
                    clean_media_open_btn.click(open_folder_in_explorer, inputs=[media_backup_dir_state], outputs=[])

        # ========================================================
        # 板块二：剪映工程自动化处理中心
        # ========================================================
        with gr.TabItem("🎬 剪映工程自动化处理中心"):
            with gr.Accordion("📁 剪映草稿工程定位 (全局配置自动保存)", open=True):
                with gr.Row():
                    draft_path_input = gr.Textbox(
                        value=cfg.get("base_drafts_dir", ""),
                        label="剪映草稿根目录 (支持带双引号路径粘贴)",
                        placeholder="例如: C:\\Users\\xxx\\AppData\\Local\\JianyingPro\\User Data\\Projects\\com.lveditor.draft",
                        scale=4
                    )
                    refresh_btn = gr.Button("🔄 刷新项目列表", scale=1)
                project_dropdown = gr.Dropdown(
                    choices=initial_projects,
                    value=initial_proj_value,
                    label="当前选择的剪映草稿工程",
                    interactive=True
                )

            with gr.Row():
                # 功能 1：图文/视频自动吸附
                with gr.Column(variant="panel"):
                    gr.Markdown("#### 1. 🖼️ 图文/视频自动吸附字幕")
                    gr.Markdown("💡 **严格 1:1 分镜**：无论延展多少倍，主轨道素材片段数量严格不变！")
                    video_mode = gr.Radio(
                        choices=[
                            ("模式D: 0.8x降速 + PingPong[素材数1:1]", "stretch_08_pingpong"),
                            ("模式C: 1.0x原速 + PingPong[素材数1:1]", "pingpong_1x"),
                            ("模式B: 强制原速循环复制 (产生多段分裂片段)", "loop_copy"),
                            ("模式A: 强制纯降速填满", "slow_down")
                        ],
                        value="stretch_08_pingpong",
                        label="视频填充策略"
                    )
                    snap_audio_chk = gr.Checkbox(value=True, label="🎵 音频断点自动截断（杜绝跨句越界）")
                    align_btn = gr.Button("⚡ 执行素材对齐字幕", variant="primary")
                    # 固定高度 11 行，超出在框内滚动，不撑长页面
                    align_result = gr.Textbox(label="执行日志", lines=11, max_lines=11, autoscroll=True)
                    align_btn.click(
                        core_align_media_logic, 
                        inputs=[draft_path_input, project_dropdown, video_mode, snap_audio_chk], 
                        outputs=[align_result]
                    )
                # 功能 2：批量随机运镜 (仅图片)
                with gr.Column(variant="panel"):
                    gr.Markdown("#### 2. ✨ 批量随机运镜 (仅图片)")
                    gr.Markdown("动静分离处理，自动跳过原生视频；自动生成推拉摇移关键帧。")
                    with gr.Row():
                        zoom_min = gr.Number(value=1.2, label="缩放小值", precision=2)
                        zoom_max = gr.Number(value=1.2, label="缩放大值", precision=2)
                        pan_mag = gr.Number(value=0.12, label="位移幅度", precision=2)
                    blur_bg_chk = gr.Checkbox(value=True, label="🖼️ 开启高斯模糊背景填充 (防黑边)")
                    kf_btn = gr.Button("✨ 生成随机运镜关键帧", variant="primary")
                    # 左右等高，同样固定 11 行
                    kf_result = gr.Textbox(label="运镜日志", lines=11, max_lines=11, autoscroll=True)
                    kf_btn.click(
                        core_add_keyframes_only_logic, 
                        inputs=[draft_path_input, project_dropdown, zoom_min, zoom_max, pan_mag, blur_bg_chk], 
                        outputs=[kf_result]
                    )

            with gr.Row():
                # 功能 3：字幕效果处理（独立板块）
                with gr.Column(variant="panel"):
                    gr.Markdown("#### 3. 💬 字幕效果与样式处理")
                    gr.Markdown("强制应用【白底黑框】、居中对齐、精准调整 Y 轴安全区、缩放与描边粗细。")
                    with gr.Row():
                        sub_y_slider = gr.Slider(minimum=-900, maximum=900, value=init_y, step=10, label="↕️ 上下位置 Y (像素: 负数靠下 / 正数靠上)")
                        sub_size_slider = gr.Slider(minimum=3.0, maximum=25.0, value=init_size, step=0.5, label="🔤 字号大小")
                    with gr.Row():
                        sub_scale_slider = gr.Slider(minimum=50, maximum=200, value=init_scale, step=1, label="🔍 缩放百分比 (如 115%)")
                        sub_stroke_slider = gr.Slider(minimum=0, maximum=100, value=init_stroke, step=1, label="🖊️ 描边粗细 (如 30)")
                    sub_btn = gr.Button("💬 一键应用字幕样式与位置", variant="primary")
                    sub_result = gr.Textbox(label="字幕处理日志", lines=4)
                    sub_btn.click(
                        core_subtitle_styling_logic,
                        inputs=[draft_path_input, project_dropdown, sub_y_slider, sub_size_slider, sub_scale_slider, sub_stroke_slider],
                        outputs=[sub_result]
                    )

                # 功能 4：视频素材声音管理
                with gr.Column(variant="panel"):
                    gr.Markdown("#### 4. 🔊 视频素材声音管理")
                    gr.Markdown("一键解决导入视频自带杂音干扰的问题。")
                    audio_action = gr.Radio(
                        choices=[
                            ("彻底删除音频 (主轨视频静音去除声音)", "delete_only"),
                            ("仅分离音频 (提取至新音轨，主轨静音)", "extract_only")
                        ],
                        value="delete_only",
                        label="操作类型"
                    )
                    v_audio_btn = gr.Button("⚡ 执行声音处理", variant="primary")
                    v_audio_result = gr.Textbox(label="处理日志", lines=4)
                    v_audio_btn.click(
                        core_manage_video_audio_logic, 
                        inputs=[draft_path_input, project_dropdown, audio_action], 
                        outputs=[v_audio_result]
                    )

            # 功能 5：音频名生成标题卡片
            with gr.Column(variant="panel"):
                gr.Markdown("#### 5. 🎵 音频名生成标题卡片")
                gr.Markdown("提取音频文件名，在新文本轨道生成居中对齐卡片。")
                with gr.Row():
                    split_char = gr.Textbox(value=".", label="起始截取符", scale=1)
                    title_dur = gr.Number(value=3.0, label="时长(秒)", scale=1)
                    f_size1 = gr.Number(value=12, label="首行字号", scale=1)
                    f_size2 = gr.Number(value=9, label="次行字号", scale=1)
                    l_space = gr.Number(value=-0.23, label="行间距", scale=1)
                title_btn = gr.Button("🚀 提取并生成标题轨", variant="primary")
                title_result = gr.Textbox(label="生成日志", lines=3)
                title_btn.click(
                    core_generate_audio_title_track,
                    inputs=[draft_path_input, project_dropdown, split_char, f_size1, f_size2, l_space, title_dur],
                    outputs=[title_result]
                )

            def refresh_project_list(path):
                clean_path = normalize_path(path)
                projs = scan_jianying_projects(clean_path)
                cur_cfg = load_config()
                last_p = str(cur_cfg.get("last_selected_project", ""))
                chosen = last_p if last_p in projs else (projs[0] if projs else None)
                save_config({"base_drafts_dir": clean_path, "last_selected_project": chosen or ""})
                rec_y, rec_size, rec_scale, rec_stroke = inspect_draft_aspect_ratio(clean_path, chosen)
                return gr.update(choices=projs, value=chosen), rec_y, rec_size, rec_scale, rec_stroke

            def on_proj_change(path, proj):
                clean_path = normalize_path(path)
                if proj is not None:
                    save_config({"base_drafts_dir": clean_path, "last_selected_project": str(proj)})
                rec_y, rec_size, rec_scale, rec_stroke = inspect_draft_aspect_ratio(clean_path, proj)
                return rec_y, rec_size, rec_scale, rec_stroke

            draft_path_input.change(refresh_project_list, inputs=[draft_path_input], outputs=[project_dropdown, sub_y_slider, sub_size_slider, sub_scale_slider, sub_stroke_slider])
            refresh_btn.click(refresh_project_list, inputs=[draft_path_input], outputs=[project_dropdown, sub_y_slider, sub_size_slider, sub_scale_slider, sub_stroke_slider])
            project_dropdown.change(on_proj_change, inputs=[draft_path_input, project_dropdown], outputs=[sub_y_slider, sub_size_slider, sub_scale_slider, sub_stroke_slider])

# ==========================================
# 5. 启动入口
# ==========================================
if __name__ == "__main__":
    port = 7860
    if sys.platform == "win32":
        allowed_list = [f"{d}:\\" for d in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{d}:\\")]
    else:
        allowed_list = ["/"]
        
    webbrowser.open(f"http://127.0.0.1:{port}")
    demo.launch(server_name="127.0.0.1", server_port=port, allowed_paths=allowed_list, inbrowser=False)