import json
import requests
import re
import urllib.request
from urllib.parse import urlparse
import socket
import time

def is_url_valid(url):
    """Check if a URL is valid and reachable."""
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.getcode() == 200
    except (urllib.error.URLError, socket.timeout):
        return False

def parse_m3u(content):
    """Parse M3U content into a list of entries."""
    entries = []
    current_entry = None
    lines = content.splitlines()
    
    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF'):
            current_entry = {'extinf': line}
        elif line and not line.startswith('#') and current_entry:
            current_entry['url'] = line
            entries.append(current_entry)
            current_entry = None
    
    return entries

def fetch_source(source):
    """Fetch and parse content from a source URL."""
    url = source['url']
    try:
        headers = {'User-Agent': source.get('UA', [''])[0]}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        content = response.text
        
        if url.endswith('.m3u'):
            return parse_m3u(content)
        else:  # Assume TXT is similar to M3U for simplicity
            return parse_m3u(content)  # Adjust parsing if TXT format differs
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return []

def filter_entry(entry, groups, channels, keywords):
    """Check if an entry matches any group, channel, or keyword."""
    extinf = entry.get('extinf', '').lower()
    return (
        any(g.lower() in extinf for g in groups) or
        any(c.lower() in extinf for c in channels) or
        any(k.lower() in extinf for k in keywords)
    )

def merge_similar_channels(entries):
    """Merge entries with identical URLs, combining their EXTINF metadata."""
    url_to_entry = {}
    for entry in entries:
        url = entry['url']
        if url in url_to_entry:
            existing = url_to_entry[url]
            existing['extinf'] = f"{existing['extinf']}, {entry['extinf'].split(',', 1)[1]}"
        else:
            url_to_entry[url] = entry
    return list(url_to_entry.values())

def main():
    # Read config.json
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    all_entries = []
    for source in config.get('sources', []):
        print(f"Processing source: {source['url']}")
        entries = fetch_source(source)
        
        # Filter entries based on groups, channels, and keywords
        filtered_entries = [
            entry for entry in entries
            if filter_entry(entry, source.get('groups', []), source.get('channels', []), source.get('keywords', []))
        ]
        
        # Validate URLs if enabled
        if config.get('check_urls', False):
            valid_entries = []
            for entry in filtered_entries:
                if is_url_valid(entry['url']):
                    valid_entries.append(entry)
                else:
                    print(f"Skipping invalid URL: {entry['url']}")
            filtered_entries = valid_entries
        
        all_entries.extend(filtered_entries)
    
    # Merge similar channels if enabled
    if config.get('merge_similar_channels', False):
        all_entries = merge_similar_channels(all_entries)
    
    # Write to output.m3u
    output_file = config.get('output', 'output.m3u')
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U\n')
        for entry in all_entries:
            f.write(f"{entry['extinf']}\n{entry['url']}\n")
    
    print(f"Generated {output_file} with {len(all_entries)} entries")

if __name__ == '__main__':
    main()