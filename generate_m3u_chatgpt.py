import json
import requests
import re
from pathlib import Path
from datetime import datetime

# 读取配置
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

channels_map = {}
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

# 提取分辨率（URL 或名字里包含 1080p/720/480 等）
def extract_resolution(text):
    match = re.search(r'(\d{3,4})[pi]', text.lower())
    if match:
        return int(match.group(1))
    return 0

for source in config["sources"]:
    ua_default = source.get("UA", [None])[0]  # 只用第一个 UA
    content = fetch_content(source["url"], ua=ua_default)

    lines = content.splitlines()

    group_filters = set(source.get("groups", []))
    channel_filters = set(source.get("channels", []))
    keyword_filters = source.get("keywords", [])

    current_group = None
    keep_channel = False
    channel_name = None

    for line in lines:
        if line.startswith("#EXTINF"):
            # 提取组名、频道名
            group_match = re.search(r'group-title="([^"]+)"', line)
            name_match = re.search(r',(.+)', line)
            group = group_match.group(1) if group_match else ""
            name = name_match.group(1).strip() if name_match else ""

            current_group = group
            channel_name = name
            keep_channel = False

            # 规则匹配
            if group in group_filters:
                keep_channel = True
            if name in channel_filters:
                keep_channel = True
            if any(k in name for k in keyword_filters):
                keep_channel = True

            if keep_channel:
                if channel_name not in channels_map:
                    channels_map[channel_name] = {"extinf": line, "urls": []}

        elif line.startswith("http") and keep_channel:
            url = line.strip()

            # 检查链接是否有效
            if config.get("check_urls", False):
                if not check_url(url):
                    invalid_links.append(f"{channel_name}: {url}")
                    continue

            # UA 处理逻辑：如果没有 UA，就加上配置里的 UA
            if "|User-Agent=" not in url and ua_default:
                url = f"{url}|User-Agent={ua_default}"

            if channel_name:
                res = extract_resolution(url)
                channels_map[channel_name]["urls"].append((res, url))

# 生成 m3u
output_lines.append("#EXTM3U")
for name, data in channels_map.items():
    urls_sorted = sorted(data["urls"], key=lambda x: x[0], reverse=True)
    urls_limited = [u for _, u in urls_sorted[:3]]  # 最多 3 个链接

    output_lines.append(data["extinf"])
    output_lines.extend(urls_limited)

output_path = Path(config["output"])
output_path.write_text("\n".join(output_lines), encoding="utf-8")

# 生成日志
log_path = Path("output.log")
with log_path.open("w", encoding="utf-8") as log:
    log.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    log.write(f"共筛选频道: {len(channels_map)}\n")
    log.write(f"无效链接: {len(invalid_links)}\n\n")
    if invalid_links:
        log.write("以下链接检测失败:\n")
        for item in invalid_links:
            log.write(f"{item}\n")

print(f"✅ 生成完成: {output_path}，共 {len(channels_map)} 个频道")
print(f"📄 日志: {log_path}，记录了 {len(invalid_links)} 个无效链接")
