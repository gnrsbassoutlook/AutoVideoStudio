#!/usr/bin/env python3
import sys
import os
import re
import subprocess

def get_video_duration(ffprobe_path, video_path):
    """优先读取容器层时长，兜底视频流时长"""
    cmd_format = [
        ffprobe_path,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    result_fmt = subprocess.run(cmd_format, capture_output=True, text=True, timeout=30)
    dur_str = result_fmt.stdout.strip()
    if dur_str:
        return float(dur_str)

    cmd_stream = [
        ffprobe_path,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    result_stm = subprocess.run(cmd_stream, capture_output=True, text=True, timeout=30)
    dur_str2 = result_stm.stdout.strip()
    if dur_str2:
        return float(dur_str2)

    print(f"[debug] format stderr:{result_fmt.stderr}\nstream stderr:{result_stm.stderr}")
    return None


def get_next_sequence_number(out_dir, base_name, ext):
    """扫描目录，获取下一个接续序号，比如已有_010，则返回11；无文件返回1"""
    max_exist = 0
    pattern = re.compile(rf"^{re.escape(base_name)}_(\d{{3}}){re.escape(ext)}$")
    for fname in os.listdir(out_dir):
        match = pattern.match(fname)
        if match:
            num = int(match.group(1))
            if num > max_exist:
                max_exist = num
    return max_exist + 1


def split_video(ffmpeg_path, ffprobe_path, input_file, offset_start, seg_duration, max_segments):
    base_dir = os.path.dirname(input_file)
    base_name, ext = os.path.splitext(os.path.basename(input_file))
    total_dur = get_video_duration(ffprobe_path, input_file)
    if total_dur is None:
        print(f"⚠️ 无法读取视频时长：{input_file}，跳过")
        return

    print(f"\n📹 文件：{os.path.basename(input_file)} | 总时长 {total_dur:.2f}秒")

    # 校验起始偏移
    if offset_start >= total_dur:
        print(f"❌ 起始截取时间 {offset_start:.2f}秒 大于等于视频总时长 {total_dur:.2f}秒，该文件跳过！")
        return

    remain_total = total_dur - offset_start
    max_cut_total = seg_duration * max_segments
    actual_cut_total = min(max_cut_total, remain_total)
    real_seg_count = int(actual_cut_total // seg_duration)

    if real_seg_count <= 0:
        print(f"⚠️ 从{offset_start:.2f}秒开始后，剩余视频不足以切出完整1段，跳过该文件")
        return

    # 获取接续起始编号
    start_seq = get_next_sequence_number(base_dir, base_name, ext)
    print(f"ℹ️ 检测旧片段，本次输出从 {start_seq:03d} 号开始")
    print(f"✂️ 从{offset_start:.2f}秒开始截取，单段{seg_duration}秒，最多切{max_segments}段，实际输出{real_seg_count}段")

    for idx in range(real_seg_count):
        clip_start = offset_start + idx * seg_duration
        seq_num = start_seq + idx
        out_filename = f"{base_name}_{seq_num:03d}{ext}"
        out_path = os.path.join(base_dir, out_filename)

        # ======== 重编码模式（默认启用，片段可拖拽预览）========
        cmd = [
            ffmpeg_path,
            "-ss", f"{clip_start:.3f}",
            "-i", input_file,
            "-t", f"{seg_duration:.3f}",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-y", out_path
        ]

        # ---- 如果想要极速流复制，注释上面cmd，启用下面这组（片段无法拖拽预览）
        # cmd = [
        #     ffmpeg_path,
        #     "-i", input_file,
        #     "-ss", f"{clip_start:.3f}",
        #     "-t", f"{seg_duration:.3f}",
        #     "-c", "copy",
        #     "-y", out_path
        # ]

        print(f"▶ 生成 {out_filename} 起始{clip_start:.2f}s")
        try:
            subprocess.run(cmd, capture_output=True, timeout=180)
        except Exception as e:
            print(f"❌ 片段{idx+1}处理异常，跳过：{e}")
    print(f"✅ {os.path.basename(input_file)} 处理完成\n")


def main():
    ffmpeg_candidates = ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "ffmpeg"]
    ffprobe_candidates = ["/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe", "ffprobe"]

    ffmpeg_bin = None
    for p in ffmpeg_candidates:
        try:
            subprocess.run([p, "-version"], capture_output=True)
            ffmpeg_bin = p
            break
        except Exception:
            continue
    if not ffmpeg_bin:
        print("错误：未找到ffmpeg，请先执行 brew install ffmpeg")
        input("按回车退出...")
        return

    ffprobe_bin = None
    for p in ffprobe_candidates:
        try:
            subprocess.run([p, "-version"], capture_output=True)
            ffprobe_bin = p
            break
        except Exception:
            continue
    if not ffprobe_bin:
        print("错误：未找到ffprobe，ffmpeg安装异常")
        input("按回车退出...")
        return

    files = [f for f in sys.argv[1:] if os.path.isfile(f) and f.lower().endswith(".mp4")]
    if not files:
        print("==== 使用说明 ====")
        print("Mac不能直接双击脚本！")
        print("终端用法：python3 脚本路径 mp4路径")
        print("1.把py拖进终端，空格，再把mp4拖进终端，回车运行")
        input("\n按回车退出...")
        return

    # 用户全局参数：所有拖入文件共用一套起始、段长、段数
    while True:
        try:
            offset_start = float(input("\n请输入【开始截取的起始秒数】：").strip())
            if offset_start >= 0:
                break
            else:
                print("起始时间不能为负数，请重新输入！")
        except ValueError:
            print("请输入有效的数字！")

    while True:
        try:
            seg_sec = float(input("请输入每段切分时长(秒)：").strip())
            if seg_sec > 0:
                break
        except ValueError:
            print("请输入有效的数字！")

    while True:
        try:
            max_num = int(input("请输入最多切多少段：").strip())
            if max_num > 0:
                break
        except ValueError:
            print("请输入有效的整数！")

    for f in files:
        split_video(ffmpeg_bin, ffprobe_bin, f, offset_start, seg_sec, max_num)

    print("\n🎉 全部任务结束！")
    input("\n按回车关闭窗口...")


if __name__ == "__main__":
    main()
