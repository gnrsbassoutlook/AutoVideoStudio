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
import random
import shutil
import string
import datetime
import subprocess
import webbrowser
import tempfile
from pathlib import Path
import gradio as gr

# ==========================================
# 0. 本地持久化配置管理与跨平台工具
# ==========================================
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_config.json")

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
    clean_path = str(file_or_dir_path).strip("'\"")
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

def resolve_input_path(path_str, file_obj):
    """同时兼容：1. 手动/拖入真实文件路径; 2. 上传文件对象"""
    if path_str and path_str.strip():
        p = path_str.strip().strip("'\"").replace(r"\ ", " ")
        if os.path.exists(p):
            return p
    if file_obj is not None:
        return file_obj.name
    return None

def determine_out_path(source_file_path: str, suffix: str, ext: str, save_in_origin: bool) -> str:
    """根据是否在原目录生成的勾选框决定保存路径"""
    p = Path(source_file_path).resolve()
    target_ext = ext if ext else p.suffix
    if not target_ext.startswith('.'):
        target_ext = '.' + target_ext
    filename = f"{p.stem}{suffix}{target_ext}"
    
    if save_in_origin:
        out_path = p.parent / filename
    else:
        out_path = Path(tempfile.gettempdir()) / filename
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
    filepath = resolve_input_path(path_str, file_obj)
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
    out_path = determine_out_path(filepath, "_No_Marks", ".txt", save_in_origin)
    with open(out_path, 'w', encoding='utf-8-sig') as f:
        f.write(output_content)
    
    loc_msg = f"原目录: {out_path}" if save_in_origin else f"临时缓存: {out_path}"
    log = f"处理完成！原始行数: {line_count} | 移除空行: {blank_lines} | 保留行数: {len(processed_lines)}\n💾 文件已生成至 [{loc_msg}]"
    return log, output_content, out_path, out_path

def core_merge_srt(srt_path_str, srt_file_obj, txt_path_str, txt_file_obj, save_in_origin):
    srt_p = resolve_input_path(srt_path_str, srt_file_obj)
    txt_p = resolve_input_path(txt_path_str, txt_file_obj)
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
    out_path = determine_out_path(srt_p, "_merged", ".srt", save_in_origin)
    with io.open(out_path, 'w', encoding='utf-8-sig') as f:
        f.write(output_content)

    loc_msg = f"原SRT目录: {out_path}" if save_in_origin else f"临时缓存: {out_path}"
    log = f"映射完成！共生成 {len(final_entries)} 条字幕。\n字符统计: 源SRT({src_chars}) vs 目标TXT({tgt_chars})\n💾 文件已生成至 [{loc_msg}]"
    return log, output_content, out_path, out_path

def core_inject_srt_duration_to_prompts(srt_path_str, srt_file_obj, txt_path_str, txt_file_obj, fps_str, time_unit, multiplier, save_in_origin):
    srt_p = resolve_input_path(srt_path_str, srt_file_obj)
    txt_p = resolve_input_path(txt_path_str, txt_file_obj)
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
    out_path = determine_out_path(txt_p, "_with_duration", ".txt", save_in_origin)
    with open(out_path, 'w', encoding='utf-8-sig') as f:
        f.write(output_content)

    log_lines.append(f"🎉 处理完成！已成功注入 {process_len} 个分镜的时长参数（系数: {mult}x）。")
    loc_msg = f"原TXT目录: {out_path}" if save_in_origin else f"临时缓存: {out_path}"
    log_lines.append(f"💾 文件已生成至 [{loc_msg}]")
    return "\n".join(log_lines), output_content, out_path, out_path

# ==========================================
# 2. 媒体文件智能整理与去重备份核心算法
# ==========================================
MEDIA_CATEGORY_EXTENSIONS = {
    'doc': {'txt', 'doc', 'docx', 'md', 'json', 'py', 'pdf'},
    'image': {'jpg', 'jpeg', 'png', 'psd', 'tiff'},
    'audio': {'wav', 'mp3', 'wma', 'm4a', 'flac', 'ogg'},
    'video': {'mp4', 'mov', 'm4v', 'mkv', 'avi'}
}

EXT_TO_CATEGORY = {}
for cat, exts in MEDIA_CATEGORY_EXTENSIONS.items():
    for ext in exts:
        EXT_TO_CATEGORY[ext] = cat

def clean_media_base_name(stem: str) -> str:
    """循环剥离末尾的副本/序号特征：如 _0001, _1, -1, (1), _(1), 空格2, 副本 等"""
    pattern = r'(_\d+|-\d+|\s+\d+|_\(\d+\)|\(\d+\)|\[\d+\]|[-_\s]*副本|\(副本\))$'
    cur = stem
    while True:
        new_cur = re.sub(pattern, '', cur, flags=re.IGNORECASE).strip()
        if new_cur == cur or not new_cur:
            break
        cur = new_cur
    return cur if cur else stem

def get_unique_target_path(target_folder: Path, filename: str) -> Path:
    """若目标归档文件夹已存在同名文件，自动追加序号避免覆盖"""
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

def core_clean_media_folder(folder_path_str, mode_choice):
    """
    清理媒体文件夹：在待处理文件夹同级建立 doc_backup, image_backup, audio_backup, video_backup
    """
    if not folder_path_str or not folder_path_str.strip():
        return "请先输入或拖入需要整理的文件夹路径！", ""
    
    clean_p = folder_path_str.strip().strip("'\"").replace(r"\ ", " ")
    directory = Path(clean_p).expanduser().resolve()
    if not directory.exists() or not directory.is_dir():
        return f"❌ 错误: 路径不存在或不是文件夹: {clean_p}", ""

    # 同级备份父目录
    parent_dir = directory.parent

    # 扫描该目录下的所有非隐藏单文件
    file_list = []
    try:
        for item in directory.iterdir():
            if item.is_dir() or item.name.startswith('.'):
                continue
            ext = item.suffix.lstrip('.').lower()
            cat = EXT_TO_CATEGORY.get(ext, 'other')
            base_name = clean_media_base_name(item.stem)
            mtime = item.stat().st_mtime
            file_list.append({
                'path': item, 'filename': item.name, 'stem': item.stem,
                'base_name': base_name, 'ext': ext, 'category': cat, 'mtime': mtime
            })
    except Exception as e:
        return f"扫描文件夹出错: {e}", ""

    if not file_list:
        return "💡 该目录中没有可处理的文件！", str(parent_dir)

    # 分组策略
    groups = {}
    for f in file_list:
        if mode_choice.startswith("A"):
            # 选项A：基准名 + 扩展名 (如: 01.钢琴.txt 与 01.钢琴-1.txt 归为一组)
            key = (f['base_name'], f['ext'])
        elif mode_choice.startswith("B"):
            # 选项B：基准名 + 大类别 (如: 01.钢琴.mp3 与 01.钢琴.wav 归为一组)
            key = (f['base_name'], f['category'])
        else:
            # 选项C：基准名占位 (如: 01.钢琴的所有类型归为一组)
            key = f['base_name']
        groups.setdefault(key, []).append(f)

    to_keep = []
    to_archive = []

    for key, group_files in groups.items():
        # 按修改时间降序排序（最新修改的文件排在最前面）
        group_files.sort(key=lambda x: x['mtime'], reverse=True)
        to_keep.append(group_files[0])
        if len(group_files) > 1:
            for old_file in group_files[1:]:
                to_archive.append(old_file)

    if not to_archive:
        return f"🎉 扫描完毕！共检查 {len(file_list)} 个文件，均为最新唯一文件，无需清洗归档。", str(parent_dir)

    # 执行移动到同级备份文件夹中
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

    summary_log = [
        f"✅ 媒体清洗完成！",
        f"📊 原始文件总数: {len(file_list)} | 🟢 原地保留最新: {len(to_keep)} | 📦 移动归档: {success_count}",
        f"📁 备份文件已自动分发至同级备份目录: {parent_dir}",
        "-" * 45,
        "【归档详情列表】:"
    ] + log_details

    return "\n".join(summary_log), str(parent_dir)

# ==========================================
# 3. 剪映草稿处理核心算法
# ==========================================
def scan_jianying_projects(draft_dir):
    if not draft_dir or not os.path.exists(draft_dir):
        return []
    try:
        folders = []
        for entry in os.listdir(draft_dir):
            full_path = os.path.join(draft_dir, entry)
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

def core_align_media_logic(draft_dir, project_name, video_mode="smart", min_speed_limit=0.6, snap_audio_boundary=True):
    """图文/视频轨道自动对齐（精准吸附全局音频最末尾 + 音频断点自动截断）"""
    if not draft_dir or not project_name:
        return "请选择剪映草稿目录和工程名称！"
    
    project_dir = os.path.join(draft_dir, str(project_name))
    draft_json_path = get_draft_json_file(project_dir)
    if not os.path.exists(draft_json_path):
        return f"未在选定工程中找到草稿文件: {project_dir}"

    backup_path = backup_draft_json(draft_json_path, "align_bak")
    with open(draft_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    tracks = data.get("tracks", [])
    video_track = next((t for t in tracks if t.get("type") == "video"), None)
    text_track = next((t for t in tracks if t.get("type") == "text"), None)

    if not video_track or not text_track:
        return "错误：草稿中必须同时包含至少一条【主视频/图片轨道】和一条【文本/字幕轨道】！"

    audio_segments_bounds = []
    max_project_end = 0
    for t in tracks:
        is_audio = (t.get("type") == "audio")
        for seg in t.get("segments", []):
            tg = seg.get("target_timerange", {})
            st = int(tg.get("start", 0))
            dt = int(tg.get("duration", 0))
            ed = st + dt
            if ed > max_project_end:
                max_project_end = ed
            if is_audio and dt > 0:
                audio_segments_bounds.append((st, ed))

    audio_segments_bounds.sort(key=lambda x: x[0])

    def find_audio_bound_for_time(t):
        for st, ed in audio_segments_bounds:
            if st <= t < ed:
                return st, ed
        return None, None

    mat_videos_dict = {v["id"]: v for v in data.get("materials", {}).get("videos", [])}
    mat_speeds_dict = {s["id"]: s for s in data.get("materials", {}).get("speeds", [])}

    v_segs = sorted(video_track.get("segments", []), key=lambda s: int(s.get("target_timerange", {}).get("start", 0)))
    t_segs = sorted(text_track.get("segments", []), key=lambda s: int(s.get("target_timerange", {}).get("start", 0)))

    num_pairs = min(len(v_segs), len(t_segs))
    if num_pairs == 0:
        return "未找到可对齐的片段！"

    curr_start = 0
    mod_count = 0
    new_video_segments = []

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

    for i in range(num_pairs):
        v = v_segs[i]
        mat_id = v.get("material_id")
        video_mat = mat_videos_dict.get(mat_id, {})
        mat_type = video_mat.get("type", "photo")
        raw_vid_dur = int(video_mat.get("duration", 3000000))

        if i < num_pairs - 1:
            next_t_start = int(t_segs[i+1].get("target_timerange", {}).get("start", curr_start))
            target_end = max(curr_start + 1, next_t_start)
        else:
            last_text_end = int(t_segs[i].get("target_timerange", {}).get("start", 0)) + int(t_segs[i].get("target_timerange", {}).get("duration", 1000000))
            final_target_end = max(max_project_end, last_text_end)
            target_end = max(curr_start + 1, final_target_end)

        if snap_audio_boundary and audio_segments_bounds:
            a_st, a_ed = find_audio_bound_for_time(curr_start)
            if a_ed is not None and target_end > a_ed:
                target_end = a_ed

        dur = max(1, target_end - curr_start)

        if mat_type == "photo":
            v["target_timerange"] = {"start": int(curr_start), "duration": int(dur)}
            v["source_timerange"] = {"start": 0, "duration": int(dur)}
            if "common_keyframes" in v and isinstance(v["common_keyframes"], list):
                for prop in v["common_keyframes"]:
                    kfs = prop.get("keyframe_list", [])
                    if kfs:
                        kfs[-1]["time_offset"] = int(dur)
            new_video_segments.append(v)
            curr_start += dur
            mod_count += 1
        else:
            if raw_vid_dur >= dur:
                v["target_timerange"] = {"start": int(curr_start), "duration": int(dur)}
                v["source_timerange"] = {"start": 0, "duration": int(dur)}
                set_speed_material(v, 1.0)
                new_video_segments.append(v)
                curr_start += dur
                mod_count += 1
            else:
                calc_speed = raw_vid_dur / dur
                if video_mode == "slow_down":
                    v["target_timerange"] = {"start": int(curr_start), "duration": int(dur)}
                    v["source_timerange"] = {"start": 0, "duration": int(raw_vid_dur)}
                    set_speed_material(v, calc_speed)
                    new_video_segments.append(v)
                    curr_start += dur
                    mod_count += 1
                elif video_mode == "loop_copy":
                    rem_dur = dur
                    while rem_dur > 0:
                        take_dur = min(rem_dur, raw_vid_dur)
                        clone_seg = json.loads(json.dumps(v))
                        clone_seg["id"] = str(uuid.uuid4()).upper()
                        clone_seg["target_timerange"] = {"start": int(curr_start), "duration": int(take_dur)}
                        clone_seg["source_timerange"] = {"start": 0, "duration": int(take_dur)}
                        set_speed_material(clone_seg, 1.0)
                        new_video_segments.append(clone_seg)
                        curr_start += take_dur
                        rem_dur -= take_dur
                        mod_count += 1
                elif video_mode == "smart":
                    threshold = float(min_speed_limit)
                    if calc_speed >= threshold:
                        v["target_timerange"] = {"start": int(curr_start), "duration": int(dur)}
                        v["source_timerange"] = {"start": 0, "duration": int(raw_vid_dur)}
                        set_speed_material(v, calc_speed)
                        new_video_segments.append(v)
                        curr_start += dur
                        mod_count += 1
                    else:
                        slow_speed = threshold
                        max_expanded_dur = int(raw_vid_dur / slow_speed)
                        rem_dur = dur
                        while rem_dur > 0:
                            cur_target_dur = min(rem_dur, max_expanded_dur)
                            cur_source_dur = int(cur_target_dur * slow_speed)
                            clone_seg = json.loads(json.dumps(v))
                            clone_seg["id"] = str(uuid.uuid4()).upper()
                            clone_seg["target_timerange"] = {"start": int(curr_start), "duration": int(cur_target_dur)}
                            clone_seg["source_timerange"] = {"start": 0, "duration": int(cur_source_dur)}
                            set_speed_material(clone_seg, slow_speed)
                            new_video_segments.append(clone_seg)
                            curr_start += cur_target_dur
                            rem_dur -= cur_target_dur
                            mod_count += 1

    if len(v_segs) > num_pairs:
        for i in range(num_pairs, len(v_segs)):
            v = v_segs[i]
            d = int(v.get("target_timerange", {}).get("duration", 1000000))
            v["target_timerange"]["start"] = int(curr_start)
            curr_start += d
            new_video_segments.append(v)
            mod_count += 1

    video_track["segments"] = new_video_segments
    data["duration"] = int(curr_start)

    with open(draft_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    snap_msg = "（已启用音频断点截断）" if snap_audio_boundary else ""
    return f"🎉 对齐成功！{snap_msg}\n- 处理片段数: {mod_count}\n- 末尾已自动吸附全工程终点: {curr_start/1000000:.2f}秒\n- 自动备份: {os.path.basename(backup_path)}"

def core_add_keyframes_logic(draft_dir, project_name, zoom_min, zoom_max, pan_mag, auto_blur_bg=True):
    if not draft_dir or not project_name:
        return "请选择剪映草稿目录和工程名称！"
    
    project_dir = os.path.join(draft_dir, str(project_name))
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
    return f"✨ 运镜添加成功！\n- 处理 {mod_count} 个图片片段 {bg_msg}\n- 自动跳过 {skipped_videos} 个原生视频\n- 自动备份: {os.path.basename(backup_path)}"

def core_manage_video_audio_logic(draft_dir, project_name, action_type):
    if not draft_dir or not project_name:
        return "请选择剪映草稿目录和工程名称！"

    project_dir = os.path.join(draft_dir, str(project_name))
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
    if not draft_dir or not project_name:
        return "请选择剪映草稿目录和工程名称！"
    
    project_dir = os.path.join(draft_dir, str(project_name))
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
            "preset_category": "", "preset_category_id": "", "preset_has_set_alignment": False, "preset_id": "",
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

with gr.Blocks(title="智绘声影2.0+剪映自动视频工作台") as demo:
    gr.Markdown("# 🎙️ 智绘声影2.0+剪映自动视频工作台")
    
    with gr.Tabs():
        # ========================================================
        # 板块一：文本与媒体处理中心
        # ========================================================
        with gr.TabItem("✂️ 文本与媒体处理中心"):
            gr.Markdown("💡 **使用提示**：从访达/资源管理器将文件或文件夹**直接拖入路径输入框**即可快速识别！")
            
            # --- 1. SRT 时长注入 ---
            gr.Markdown("### 📌 1. SRT 时间轴注入提示词时长 (ComfyUI 专用)")
            with gr.Row():
                with gr.Column(scale=1):
                    srt_path_in = gr.Textbox(label="SRT 文件路径 (可直接将文件拖拽至此)", placeholder="/Users/.../xxx.srt")
                    srt_time_in = gr.File(label="或者点击上传 SRT 文件", file_types=[".srt"])
                    prompt_path_in = gr.Textbox(label="提示词 TXT 路径 (可直接将文件拖拽至此)", placeholder="/Users/.../prompt.txt")
                    prompt_txt_in = gr.File(label="或者点击上传 TXT 文本", file_types=[".txt"])
                    with gr.Row():
                        fps_select = gr.Dropdown(choices=["16", "24", "25", "30", "50", "60"], value="25", label="帧率 (FPS)")
                        unit_select = gr.Radio(choices=["帧数 (如 560f)", "秒数 (如 22.4s)"], value="帧数 (如 560f)", label="时长标记单位")
                    time_mult = gr.Slider(minimum=1.0, maximum=1.3, value=1.02, step=0.01, label="安全时长冗余系数 (默认 1.02x)")
                    origin_chk_1 = gr.Checkbox(value=True, label="在原目录生成")
                    with gr.Row():
                        inject_btn = gr.Button("⚡ 开始计算并注入", variant="primary", scale=2)
                        inject_open_btn = gr.Button("📂 打开生成目录", scale=1)
                with gr.Column(scale=1):
                    inject_log = gr.Textbox(label="比对与校验日志", lines=4)
                    inject_preview = gr.Textbox(label="生成文本内容预览 (可直接点击全选复制)", lines=6)
                    inject_out = gr.File(label="浏览器下载备用 (Downloads 目录)")
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
                    srt_m_path = gr.Textbox(label="原始 SRT 文件路径 (拖入文件)", placeholder="/Users/.../source.srt")
                    srt_in = gr.File(label="或者点击上传 SRT 文件", file_types=[".srt"])
                    txt_m_path = gr.Textbox(label="校对 TXT 文件路径 (拖入文件)", placeholder="/Users/.../target.txt")
                    txt_in = gr.File(label="或者点击上传 TXT 文件", file_types=[".txt"])
                    origin_chk_2 = gr.Checkbox(value=True, label="在原目录生成")
                    with gr.Row():
                        merge_btn = gr.Button("🔄 开始映射对齐", variant="primary", scale=2)
                        merge_open_btn = gr.Button("📂 打开生成目录", scale=1)
                with gr.Column(scale=1):
                    merge_log = gr.Textbox(label="对齐统计日志", lines=4)
                    merge_preview = gr.Textbox(label="生成 SRT 字幕预览 (可直接点击全选复制)", lines=6)
                    merge_out = gr.File(label="浏览器下载备用 (Downloads 目录)")
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
                    clean_path_in = gr.Textbox(label="文稿 TXT 路径 (直接拖拽文件至此)", placeholder="/Users/.../text.txt")
                    clean_in = gr.File(label="或点击上传文稿 TXT", file_types=[".txt"])
                    origin_chk_3 = gr.Checkbox(value=True, label="在原目录生成")
                    with gr.Row():
                        clean_btn = gr.Button("🧹 清洗标点符号", variant="primary", scale=2)
                        clean_open_btn = gr.Button("📂 打开所在目录", scale=1)
                    clean_log = gr.Textbox(label="清洗统计", lines=3)
                    clean_preview = gr.Textbox(label="清洗结果预览", lines=5)
                    clean_out = gr.File(label="浏览器下载备用 (Downloads 目录)")
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
                    gr.Markdown("自动识别 `_0001`、`-(1)`、` 2`、`副本` 等后缀，将旧文件移至**同级备份目录**。")
                    media_folder_in = gr.Textbox(
                        label="待整理文件夹路径 (直接拖拽文件夹至此)", 
                        placeholder="例如: /Users/xxx/Documents/Resource 或 D:\\Project\\Resource"
                    )
                    media_mode_radio = gr.Radio(
                        choices=[
                            "选项A: 同扩展名清洗（同名txt只留最新，不影响jpg/mp3等）",
                            "选项B: 同大类清洗（同属audio/video/image/doc只留1个最新）",
                            "选项C: 全局唯一占位（不管格式类型，该名称全目录只留1个最新）"
                        ],
                        value="选项A: 同扩展名清洗（同名txt只留最新，不影响jpg/mp3等）",
                        label="清理规则"
                    )
                    with gr.Row():
                        clean_media_btn = gr.Button("🗂️ 执行媒体去重并移动备份", variant="primary", scale=2)
                        clean_media_open_btn = gr.Button("📂 打开备份所在目录", scale=1)
                    media_clean_log = gr.Textbox(label="整理执行日志", lines=9)
                    media_backup_dir_state = gr.State("")

                    clean_media_btn.click(
                        core_clean_media_folder,
                        inputs=[media_folder_in, media_mode_radio],
                        outputs=[media_clean_log, media_backup_dir_state]
                    )
                    clean_media_open_btn.click(open_folder_in_explorer, inputs=[media_backup_dir_state], outputs=[])

        # ========================================================
        # 板块二：剪映工程自动化处理
        # ========================================================
        with gr.TabItem("🎬 剪映工程自动化处理"):
            with gr.Accordion("📁 剪映草稿工程定位 (全局配置自动保存)", open=True):
                with gr.Row():
                    draft_path_input = gr.Textbox(
                        value=cfg.get("base_drafts_dir", ""),
                        label="剪映草稿根目录",
                        placeholder="例如: /Users/xxx/Movies/JianyingPro/User Data/Projects/com.lveditor.draft",
                        scale=4
                    )
                    refresh_btn = gr.Button("🔄 刷新项目列表", scale=1)
                project_dropdown = gr.Dropdown(
                    choices=initial_projects,
                    value=initial_proj_value,
                    label="当前选择的剪映草稿工程",
                    interactive=True
                )

            def refresh_project_list(path):
                projs = scan_jianying_projects(path)
                cur_cfg = load_config()
                last_p = str(cur_cfg.get("last_selected_project", ""))
                chosen = last_p if last_p in projs else (projs[0] if projs else None)
                save_config({"base_drafts_dir": path, "last_selected_project": chosen or ""})
                return gr.update(choices=projs, value=chosen)

            def on_proj_change(path, proj):
                if proj is not None:
                    save_config({"base_drafts_dir": path, "last_selected_project": str(proj)})

            draft_path_input.change(refresh_project_list, inputs=[draft_path_input], outputs=[project_dropdown])
            refresh_btn.click(refresh_project_list, inputs=[draft_path_input], outputs=[project_dropdown])
            project_dropdown.change(on_proj_change, inputs=[draft_path_input, project_dropdown], outputs=[])

            with gr.Row():
                # 功能 1：图文/视频自动吸附
                with gr.Column(variant="panel"):
                    gr.Markdown("#### 1. 🖼️ 图文/视频自动吸附字幕")
                    gr.Markdown("自动填满空隙，末尾吸附音频终点，杜绝黑屏。")
                    video_mode = gr.Radio(
                        choices=[
                            ("模式C: 智能降速+复制组合", "smart"),
                            ("模式A: 强制降速填满", "slow_down"),
                            ("模式B: 强制原速循环复制", "loop_copy")
                        ],
                        value="smart",
                        label="短视频填充策略"
                    )
                    min_speed = gr.Slider(minimum=0.2, maximum=0.9, value=0.6, step=0.05, label="模式C降速下限阈值 (如 0.6x)")
                    snap_audio_chk = gr.Checkbox(value=True, label="🎵 音频断点自动截断（上一素材截止于本音频尾部，下一素材从新音频头部开始）")
                    align_btn = gr.Button("⚡ 执行素材对齐字幕", variant="primary")
                    align_result = gr.Textbox(label="执行日志", lines=4)
                    align_btn.click(
                        core_align_media_logic, 
                        inputs=[draft_path_input, project_dropdown, video_mode, min_speed, snap_audio_chk], 
                        outputs=[align_result]
                    )

                # 功能 2：批量运镜
                with gr.Column(variant="panel"):
                    gr.Markdown("#### 2. ✨ 批量随机运镜 (仅图片)")
                    gr.Markdown("动静分离处理，自动跳过原生视频。")
                    with gr.Row():
                        zoom_min = gr.Number(value=1.2, label="缩放小值", precision=2)
                        zoom_max = gr.Number(value=1.2, label="缩放大值", precision=2)
                        pan_mag = gr.Number(value=0.12, label="位移幅度", precision=2)
                    blur_bg_chk = gr.Checkbox(value=True, label="🖼️ 开启高斯模糊背景填充 (防止黑边)")
                    kf_btn = gr.Button("✨ 生成随机运镜关键帧", variant="primary")
                    kf_result = gr.Textbox(label="运镜日志", lines=4)
                    kf_btn.click(
                        core_add_keyframes_logic, 
                        inputs=[draft_path_input, project_dropdown, zoom_min, zoom_max, pan_mag, blur_bg_chk], 
                        outputs=[kf_result]
                    )

            with gr.Row():
                # 功能 3：视频原声管理
                with gr.Column(variant="panel"):
                    gr.Markdown("#### 3. 🔊 视频素材声音管理")
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

                # 功能 4：音频名生成标题卡片
                with gr.Column(variant="panel"):
                    gr.Markdown("#### 4. 🎵 音频名生成标题卡片")
                    gr.Markdown("提取音频文件名，在新文本轨道生成居中对齐卡片。")
                    with gr.Row():
                        split_char = gr.Textbox(value=".", label="起始截取符", scale=1)
                        title_dur = gr.Number(value=3.0, label="时长(秒)", scale=1)
                    with gr.Row():
                        f_size1 = gr.Number(value=12, label="首行字号", scale=1)
                        f_size2 = gr.Number(value=9, label="次行字号", scale=1)
                        l_space = gr.Number(value=-0.23, label="行间距", scale=1)
                    title_btn = gr.Button("🚀 提取并生成标题轨", variant="primary")
                    title_result = gr.Textbox(label="生成日志", lines=4)
                    title_btn.click(
                        core_generate_audio_title_track,
                        inputs=[draft_path_input, project_dropdown, split_char, f_size1, f_size2, l_space, title_dur],
                        outputs=[title_result]
                    )

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