import json
import requests
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import os
import sys

# 读取配置
try:
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
except Exception as e:
    print(f"❌ 配置文件 config.json 打开失败: {e}")
    sys.exit(1)

output_lines = []
invalid_links = []
kept_channels = []
source_logs = []  # 每个源的说明日志

def fetch_content(url, ua=None):
    headers = {}
    if ua:
        headers["User-Agent"] = ua
    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"⚠️ 获取 {url} 失败: {e}")
        return ""

def is_url_line(line: str) -> bool:
    return bool(re.match(r'^\s*(https?|rtmp|rtsp|mms|udp)://', (line or "").strip(), re.I))

def check_url(url: str, ua: str | None = None) -> bool:
    headers = {}
    if ua:
        headers["User-Agent"] = ua
    try:
        r = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
        if r.status_code < 400:
            return True
        if r.status_code in (403, 405):
            r2 = requests.get(url, headers=headers, timeout=10, stream=True, allow_redirects=True)
            return r2.status_code < 400
        return False
    except Exception:
        return False

def parse_txt_content(content: str, ua_default: str | None, url: str):
    """把 txt 文件内容转换成标准 m3u 段落，group-title 用文件名"""
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path) or "TXT"
    group_name = os.path.splitext(filename)[0] or "TXT"

    lines = content.splitlines()
    m3u_segments = []
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        if "," in line:
            parts = line.split(",", 1)
            if len(parts) == 2:
                name, url_line = parts[0].strip(), parts[1].strip()
            else:
                name, url_line = f"{group_name}_Channel_{idx+1}", line.strip()
        else:
            name, url_line = f"{group_name}_Channel_{idx+1}", line.strip()
        if not url_line:
            continue
        if "|User-Agent=" not in url_line and ua_default:
            url_line = f"{url_line}|User-Agent={ua_default}"
        m3u_segments.append(f'#EXTINF:-1 group-title="{group_name}", {name}')
        m3u_segments.append(url_line)
    return "\n".join(m3u_segments)

# 处理每个源
for idx, source in enumerate(config.get("sources", []), start=1):
    ua_default = None
    if isinstance(source.get("UA"), list) and source.get("UA"):
        ua_default = source["UA"][0]
    elif isinstance(source.get("UA"), str):
        ua_default = source["UA"]

    url = source.get("url", "")
    if not url:
        continue

    content = fetch_content(url, ua=ua_default)
    if not content.strip():
        continue

    # 判断是不是 m3u
    if content.strip().upper().startswith("#EXTM3U"):
        lines = content.splitlines()
    else:
        converted = parse_txt_content(content, ua_default, url)
        lines = ["#EXTM3U"] + converted.splitlines()

    # 取配置里的筛选条件（允许缺失或为 null）
    raw_groups = source.get("groups") or []
    raw_channels = source.get("channels") or []
    raw_keywords = source.get("keywords") or []

    if isinstance(raw_groups, str):
        raw_groups = [raw_groups]
    if isinstance(raw_channels, str):
        raw_channels = [raw_channels]
    if isinstance(raw_keywords, str):
        raw_keywords = [raw_keywords]

    group_filters = {g.lower() for g in raw_groups}
    channel_filters = {c.lower() for c in raw_channels}
    keyword_filters = [k.lower() for k in raw_keywords]

    # 日志：记录该源的筛选条件
    if group_filters or channel_filters or keyword_filters:
        source_logs.append(
            f"源 {idx} ({url}) 使用的筛选条件: groups={list(group_filters)}, channels={list(channel_filters)}, keywords={keyword_filters}"
        )
    else:
        source_logs.append(f"源 {idx} ({url}) 未配置筛选条件 → 全量导出")

    keep_channel = False
    channel_lines = []
    current_name = ""
    current_group = ""

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if line.strip().upper().startswith("#EXTINF"):
            if keep_channel and channel_lines:
                output_lines.extend(channel_lines)
                kept_channels.append(current_name)

            channel_lines = [line]
            keep_channel = False
            current_name = ""
            current_group = ""

            group_match = re.search(r'group-title="([^"]+)"', line, re.I)
            name_match = re.search(r',(.+)', line)
            current_group = group_match.group(1) if group_match else ""
            current_name = name_match.group(1).strip() if name_match else ""

            if (not group_filters and not channel_filters and not keyword_filters) or \
               (current_group.lower() in group_filters or 
                current_name.lower() in channel_filters or 
                any(k in current_name.lower() for k in keyword_filters)):
                keep_channel = True

        else:
            if keep_channel:
                if is_url_line(line):
                    raw_url = line.strip()
                    if not raw_url:
                        continue
                    if config.get("check_urls", False) and not check_url(raw_url, ua=ua_default):
                        invalid_links.append(f"{current_name}: {raw_url}")
                    final_url = raw_url
                    if "|User-Agent=" not in final_url and ua_default:
                        final_url = f"{final_url}|User-Agent={ua_default}"
                    channel_lines.append(final_url)
                else:
                    channel_lines.append(line)

    if keep_channel and channel_lines:
        output_lines.extend(channel_lines)
        kept_channels.append(current_name)

if not output_lines or not output_lines[0].strip().upper().startswith("#EXTM3U"):
    output_lines.insert(0, "#EXTM3U")

# 确保输出目录存在
output_path = Path(config.get("output", "output.m3u"))
output_path.parent.mkdir(parents=True, exist_ok=True)

output_path.write_text("\n".join(output_lines), encoding="utf-8")

# 写日志
log_path = Path("output.log")
with log_path.open("w", encoding="utf-8") as log:
    log.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    for s in source_logs:
        log.write(s + "\n")
    log.write("\n")
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
