import json
import requests
import re
from pathlib import Path
from datetime import datetime

# 读取配置
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

output_lines = []
invalid_links = []
kept_channels = []

def fetch_content(url, ua=None):
    headers = {}
    if ua:
        headers["User-Agent"] = ua
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.text

def is_url_line(line: str) -> bool:
    # 支持常见播放协议：http, https, rtmp, rtsp, mms, udp
    return bool(re.match(r'^\s*(https?|rtmp|rtsp|mms|udp)://', (line or "").strip(), re.I))

def check_url(url: str, ua: str | None = None) -> bool:
    """尽量可靠地检测 URL 是否可用：
       - 优先尝试 HEAD（带 UA）
       - 如果 HEAD 返回 405/403 或抛错，回退到 GET (stream=True)
       - 返回 True 表示检测通过（status_code < 400），否则 False
    """
    headers = {}
    if ua:
        headers["User-Agent"] = ua
    try:
        r = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
        if r.status_code < 400:
            return True
        # 某些服务器对 HEAD 不支持（405）或拒绝（403），尝试 GET
        if r.status_code in (403, 405):
            r2 = requests.get(url, headers=headers, timeout=10, stream=True, allow_redirects=True)
            return r2.status_code < 400
        return False
    except requests.RequestException:
        # HEAD 失败时尝试 GET（有些服务器只允许 GET）
        try:
            r = requests.get(url, headers=headers, timeout=10, stream=True, allow_redirects=True)
            return r.status_code < 400
        except Exception:
            return False

# 处理每个源
for source in config.get("sources", []):
    # UA 可能在 config 里是列表，取第一个作为默认 UA
    ua_default = None
    if isinstance(source.get("UA"), list) and source.get("UA"):
        ua_default = source.get("UA")[0]
    elif isinstance(source.get("UA"), str):
        ua_default = source.get("UA")

    content = fetch_content(source["url"], ua=ua_default)
    lines = content.splitlines()

    group_filters = set(source.get("groups", []))
    channel_filters = set(source.get("channels", []))
    keyword_filters = source.get("keywords", [])

    keep_channel = False
    channel_lines = []
    current_name = ""
    current_group = ""

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if line.strip().upper().startswith("#EXTINF"):
            # 如果之前有缓存的频道并且需要保留 → 写入
            if keep_channel and channel_lines:
                output_lines.extend(channel_lines)
                kept_channels.append(current_name)

            # 开始新的频道段
            channel_lines = [line]
            keep_channel = False
            current_name = ""
            current_group = ""

            # 提取组名和频道名
            group_match = re.search(r'group-title="([^"]+)"', line, re.I)
            name_match = re.search(r',(.+)', line)
            current_group = group_match.group(1) if group_match else ""
            current_name = name_match.group(1).strip() if name_match else ""

            # 判断是否保留该频道
            if current_group in group_filters or current_name in channel_filters or any(k in current_name for k in keyword_filters):
                keep_channel = True

        else:
            # 如果当前频道被标记为保留，则把后续所有相关行都保留下来（包括 url、#EXTVLCOPT 等）
            if keep_channel:
                if is_url_line(line):
                    raw_url = line.strip()
                    # 先做检测（检测时用原始 URL，不附加 |User-Agent=）
                    ok = True
                    if config.get("check_urls", False):
                        ok = check_url(raw_url, ua=ua_default)
                        if not ok:
                            # 记录为无效（但不从输出中删除）
                            invalid_links.append(f"{current_name}: {raw_url}")

                    # 最终写入时，如果需要补 UA，就补；（补完再写入）
                    final_url = raw_url
                    if "|User-Agent=" not in final_url and ua_default:
                        final_url = f"{final_url}|User-Agent={ua_default}"

                    channel_lines.append(final_url)
                else:
                    # 其他行（例如 #EXTVLCOPT、注释、空行等）也全部保留
                    channel_lines.append(line)

    # 最后一个频道如果需要保留 → 写入
    if keep_channel and channel_lines:
        output_lines.extend(channel_lines)
        kept_channels.append(current_name)

# 在最前面加上 M3U 头（如果尚未存在）
if not output_lines or not output_lines[0].strip().upper().startswith("#EXTM3U"):
    output_lines.insert(0, "#EXTM3U")

# 写入输出文件
output_path = Path(config.get("output", "output.m3u"))
output_path.write_text("\n".join(output_lines), encoding="utf-8")

# 生成日志 — 更准确地统计保留的频道数，并列出频道清单和可疑链接
log_path = Path("output.log")
with log_path.open("w", encoding="utf-8") as log:
    log.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    log.write(f"共输出频道: {len(kept_channels)}\n\n")
    if kept_channels:
        log.write("已保留频道清单:\n")
        for ch in kept_channels:
            log.write(f"- {ch}\n")
        log.write("\n")
    log.write(f"被检测为可疑/无效的链接: {len(invalid_links)}\n")
    if invalid_links:
        log.write("以下链接检测失败（但已写入输出）：\n")
        for item in invalid_links:
            log.write(f"{item}\n")

print(f"✅ 生成完成: {output_path}，共 {len(kept_channels)} 个频道（详情见 output.log）")
print(f"📄 日志: {log_path}，记录了 {len(invalid_links)} 个可疑链接")
