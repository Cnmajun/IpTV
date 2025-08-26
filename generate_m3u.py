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

def fetch_content(url, ua=None):
    headers = {}
    if ua:
        headers["User-Agent"] = ua
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.text

def check_url(url):
    try:
        r = requests.head(url, timeout=10, allow_redirects=True)
        return r.status_code == 200
    except Exception:
        return False

# 处理每个源
for source in config["sources"]:
    ua_default = source.get("UA", [None])[0]  # 默认 UA
    content = fetch_content(source["url"], ua=ua_default)

    lines = content.splitlines()

    group_filters = set(source.get("groups", []))
    channel_filters = set(source.get("channels", []))
    keyword_filters = source.get("keywords", [])

    keep_channel = False
    channel_lines = []

    for line in lines:
        if line.startswith("#EXTINF"):
            # 如果之前有缓存的频道并且需要保留 → 写入
            if keep_channel and channel_lines:
                output_lines.extend(channel_lines)

            # 开始新的频道段
            channel_lines = [line]
            keep_channel = False

            # 提取组名和频道名
            group_match = re.search(r'group-title="([^"]+)"', line)
            name_match = re.search(r',(.+)', line)
            group = group_match.group(1) if group_match else ""
            name = name_match.group(1).strip() if name_match else ""

            # 判断是否保留该频道
            if group in group_filters or name in channel_filters or any(k in name for k in keyword_filters):
                keep_channel = True

        else:
            # 普通行（可能是 URL 或其他）
            if line.startswith("http") and keep_channel:
                url = line.strip()
                if config.get("check_urls", False):
                    if not check_url(url):
                        invalid_links.append(f"{name}: {url}")
                        continue
                if "|User-Agent=" not in url and ua_default:
                    url = f"{url}|User-Agent={ua_default}"
                channel_lines.append(url)
            elif keep_channel:
                channel_lines.append(line)

    # 最后一个频道如果需要保留 → 写入
    if keep_channel and channel_lines:
        output_lines.extend(channel_lines)

# 在最前面加上 M3U 头
output_lines.insert(0, "#EXTM3U")

# 写入输出文件
output_path = Path(config["output"])
output_path.write_text("\n".join(output_lines), encoding="utf-8")

# 生成日志
log_path = Path("output.log")
with log_path.open("w", encoding="utf-8") as log:
    log.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    log.write(f"共输出频道: {output_lines.count('#EXTINF')}\n")
    log.write(f"无效链接: {len(invalid_links)}\n\n")
    if invalid_links:
        log.write("以下链接检测失败:\n")
        for item in invalid_links:
            log.write(f"{item}\n")

print(f"✅ 生成完成: {output_path}，共 {output_lines.count('#EXTINF')} 个频道")
print(f"📄 日志: {log_path}，记录了 {len(invalid_links)} 个无效链接")
