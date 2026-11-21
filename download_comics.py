#!/usr/bin/env python3
import os
import sys
import re
import html
import io
import json
import glob
import urllib.request
from PIL import Image, ImageDraw

TARGET_WIDTH = 480

# Base directory for all webcomic folders
BASE_OUTPUT_DIR = os.path.expanduser("~/Pictures/webcomics")

# Separator requirements: 50px gap at bottom, 4px black line (doubled from 2px), 50px gap
PAD_TOP = 50
LINE_WIDTH = 4
PAD_BOTTOM = 50
FOOTER_HEIGHT = PAD_TOP + LINE_WIDTH + PAD_BOTTOM  # 104 px

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0'
}

def clean_directory(directory, range_start=None, range_end=None):
    os.makedirs(directory, exist_ok=True)
    if range_start is None or range_start <= 1:
        # Full clean when downloading starting from #1
        for f in glob.glob(os.path.join(directory, "*.jpg")):
            try:
                os.remove(f)
            except OSError:
                pass
    else:
        # Range-specific clean: only delete existing files within the target index range
        for f in glob.glob(os.path.join(directory, "*.jpg")):
            basename = os.path.basename(f)
            m = re.search(r'_(\d{3,})(?:_|\.jpg)', basename)
            if m:
                idx = int(m.group(1))
                if range_start <= idx <= range_end:
                    try:
                        os.remove(f)
                    except OSError:
                        pass

def fetch_url(url, extra_headers=None):
    h = dict(DEFAULT_HEADERS)
    if extra_headers:
        h.update(extra_headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()

def apply_thermal_formatting(img):
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        img = img.convert('RGBA')
        bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img).convert('RGB')
    else:
        img = img.convert('RGB')

    # If long horizontally, rotate 90 degrees (270 deg)
    if img.width > img.height:
        img = img.rotate(270, expand=True)

    # Scale strictly to 480px width
    scale = TARGET_WIDTH / img.width
    new_w = TARGET_WIDTH
    new_h = max(1, int(img.height * scale))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    gray = resized.convert('L')

    # 50px white gap + 4px black line + 50px white gap
    canvas = Image.new('L', (TARGET_WIDTH, new_h + FOOTER_HEIGHT), color=255)
    canvas.paste(gray, (0, 0))
    draw = ImageDraw.Draw(canvas)
    line_y = new_h + PAD_TOP
    draw.line([(0, line_y), (TARGET_WIDTH - 1, line_y)], fill=0, width=LINE_WIDTH)
    return canvas

def parse_range(raw_text):
    text = raw_text.strip().lower()
    if not text:
        return 1, 50

    # Strip prefixes like 'from ' or 'between '
    text = re.sub(r'^(?:from|between)\s+', '', text).strip()

    # Pattern: "start, count" or "start + count"
    m_plus = re.match(r'^(\d+)\s*(?:\+|\,)\s*(\d+)$', text)
    if m_plus:
        start = int(m_plus.group(1))
        count = int(m_plus.group(2))
        return start, count

    # Pattern: "start to end", "start-end", "start..end", "start end", "start:end"
    m_range = re.match(r'^(\d+)\s*(?:to|-|\.\.|:|\s)\s*(\d+)$', text)
    if m_range:
        a = int(m_range.group(1))
        b = int(m_range.group(2))
        start = min(a, b)
        end = max(a, b)
        if start == 1:
            count = end  # e.g. 1 to 50 -> 50 images (#1 to #50)
        else:
            count = end - start  # e.g. 51 to 68 -> 17 images (#51 to #67)
        return start, count

    # Pattern: single number count
    if text.isdigit():
        return 1, int(text)

    raise ValueError(f"Could not parse range from '{raw_text}'")

def get_range_selection():
    # If passed as command line argument(s)
    if len(sys.argv) > 1:
        arg_str = " ".join(sys.argv[1:])
        try:
            start_num, count = parse_range(arg_str)
            return start_num, count
        except ValueError as e:
            print(f"Error parsing CLI arguments: {e}")
            print("Falling back to interactive prompt.\n")

    # Interactive prompt
    while True:
        try:
            prompt = "Enter range of images to download (e.g. 51 to 68, 1-50) [default: 1-50]: "
            user_input = input(prompt).strip()
            return parse_range(user_input)
        except ValueError as e:
            print(f"Invalid input: {e}. Example formats: '51 to 68', '51-68', '1-50', or '50'.\n")
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)

# =====================================================================
# 1. XKCD
# =====================================================================
def process_xkcd(start_num, count):
    skip_count = start_num - 1
    end_num = start_num + count - 1
    out_dir = os.path.join(BASE_OUTPUT_DIR, "xkcd_comics")
    clean_directory(out_dir, start_num, end_num)
    print("\n================== Processing XKCD ==================")

    info = json.loads(fetch_url("https://xkcd.com/info.0.json").decode('utf-8'))
    latest = info.get('num', 3327)

    curr = latest
    valid_seen = 0
    downloaded = 0

    while downloaded < count and curr > 0:
        c_url = f"https://xkcd.com/{curr}/info.0.json"
        curr -= 1
        try:
            c_info = json.loads(fetch_url(c_url).decode('utf-8'))
            img_u = c_info.get('img')
            num = c_info.get('num')
            title = c_info.get('title', '')
            if not img_u or not (img_u.endswith('.png') or img_u.endswith('.jpg')):
                continue

            valid_seen += 1
            if valid_seen < start_num:
                continue

            raw = fetch_url(img_u)
            im = Image.open(io.BytesIO(raw))
            formatted = apply_thermal_formatting(im)

            out_name = f"xkcd_{valid_seen:03d}_{num}.jpg"
            out_path = os.path.join(out_dir, out_name)
            formatted.save(out_path, format='JPEG', quality=92)
            downloaded += 1
            print(f"[XKCD {downloaded}/{count}] #{num} (comic #{valid_seen}) ({title}) -> {out_name} ({formatted.size})")
        except Exception:
            continue

# =====================================================================
# 2. Sarah Andersen
# =====================================================================
def process_sarah_andersen(start_num, count):
    skip_count = start_num - 1
    end_num = start_num + count - 1
    out_dir = os.path.join(BASE_OUTPUT_DIR, "sarah_andersen_comics")
    clean_directory(out_dir, start_num, end_num)
    print("\n================== Processing Sarah Andersen ==================")

    episodes = []
    seen = set()
    page = 1
    needed_total = end_num
    max_pages = max(10, (needed_total // 10) + 5)

    while len(episodes) < needed_total and page <= max_pages:
        u = f"https://www.webtoons.com/en/canvas/sarahs-scribbles/list?title_no=50260&page={page}"
        try:
            content = fetch_url(u, {'Referer': 'https://www.webtoons.com/'}).decode('utf-8')
            matches = re.findall(r'href=[\"\'](https://www\.webtoons\.com/en/canvas/sarahs-scribbles/[^/]+/viewer\?[^\"\']+)[\"\']', content)
            if not matches:
                break
            for ep in matches:
                ep_c = html.unescape(ep)
                if ep_c not in seen:
                    seen.add(ep_c)
                    episodes.append(ep_c)
                    if len(episodes) >= needed_total:
                        break
            page += 1
        except Exception:
            break

    downloaded = 0
    for idx, ep in enumerate(episodes):
        comic_num = idx + 1
        if comic_num < start_num:
            continue
        if downloaded >= count:
            break
        try:
            ep_html = fetch_url(ep, {'Referer': 'https://www.webtoons.com/'}).decode('utf-8')
            t_match = re.search(r'<h1 class="subj_episode"[^>]*>([^<]+)</h1>', ep_html)
            title = t_match.group(1).strip() if t_match else f"Ep_{comic_num}"

            img_urls = re.findall(r'class=[\"\']_images[\"\'][^>]*data-url=[\"\']([^\"\']+)[\"\']', ep_html)
            if not img_urls:
                img_urls = re.findall(r'data-url=[\"\'](https://[^\s\"\']+\.(?:jpg|png|jpeg)[^\s\"\']*)[\"\']', ep_html)
            valid = [html.unescape(x) for x in img_urls if 'webtoon' in x or 'pstatic' in x]
            if not valid:
                continue

            pil_slices = []
            for img_u in valid:
                b = fetch_url(img_u, {'Referer': 'https://www.webtoons.com/'})
                pil_slices.append(Image.open(io.BytesIO(b)))

            if len(pil_slices) == 1:
                combined = pil_slices[0]
            else:
                tot_h = sum(im.height for im in pil_slices)
                max_w = max(im.width for im in pil_slices)
                stitched = Image.new('RGB', (max_w, tot_h), (255, 255, 255))
                y_off = 0
                for im in pil_slices:
                    stitched.paste(im, ((max_w - im.width) // 2, y_off))
                    y_off += im.height
                combined = stitched

            formatted = apply_thermal_formatting(combined)
            out_name = f"sarah_andersen_{comic_num:03d}.jpg"
            out_path = os.path.join(out_dir, out_name)
            formatted.save(out_path, format='JPEG', quality=92)
            downloaded += 1
            print(f"[Sarah Andersen {downloaded}/{count}] (comic #{comic_num}) {title} -> {out_name} ({formatted.size})")
        except Exception:
            continue

# =====================================================================
# 3. Loading Artist
# =====================================================================
def process_loading_artist(start_num, count):
    skip_count = start_num - 1
    end_num = start_num + count - 1
    out_dir = os.path.join(BASE_OUTPUT_DIR, "loading_artist_comics")
    clean_directory(out_dir, start_num, end_num)
    print("\n================== Processing Loading Artist ==================")

    sitemap_xml = fetch_url("https://loadingartist.com/sitemap.xml").decode('utf-8')
    comic_urls = re.findall(r'<loc>(https://loadingartist\.com/comic/[^<]+)</loc>', sitemap_xml)

    valid_seen = 0
    downloaded = 0
    for url in comic_urls:
        if downloaded >= count:
            break
        slug = url.strip('/').split('/')[-1]
        try:
            page_html = fetch_url(url).decode('utf-8')
            matches = re.findall(rf'(/comic/{re.escape(slug)}/{re.escape(slug)}[^\s\"\'><]*\.(?:jpg|png|webp))', page_html)
            valid = [x for x in matches if 'thumb' not in x]
            if not valid:
                continue

            valid_seen += 1
            if valid_seen < start_num:
                continue

            jpgs = [x for x in valid if x.endswith('.jpg') or x.endswith('.png')]
            best_rel = jpgs[-1] if jpgs else valid[-1]
            img_u = "https://loadingartist.com" + best_rel

            raw = fetch_url(img_u)
            im = Image.open(io.BytesIO(raw))
            formatted = apply_thermal_formatting(im)

            out_name = f"loading_artist_{valid_seen:03d}_{slug}.jpg"
            out_path = os.path.join(out_dir, out_name)
            formatted.save(out_path, format='JPEG', quality=92)
            downloaded += 1
            print(f"[Loading Artist {downloaded}/{count}] (comic #{valid_seen}) {slug} -> {out_name} ({formatted.size})")
        except Exception:
            continue

# =====================================================================
# 4. War and Peas
# =====================================================================
def process_war_and_peas(start_num, count):
    skip_count = start_num - 1
    end_num = start_num + count - 1
    out_dir = os.path.join(BASE_OUTPUT_DIR, "war_and_peas_comics")
    clean_directory(out_dir, start_num, end_num)
    print("\n================== Processing War and Peas ==================")

    needed_total = end_num
    max_pages = max(6, (needed_total // 20) + 5)
    valid_seen = 0
    downloaded = 0
    page = 1

    while downloaded < count and page <= max_pages:
        api_url = f"https://warandpeas.com/wp-json/wp/v2/posts?per_page=20&page={page}"
        try:
            resp = fetch_url(api_url).decode('utf-8')
            posts = json.loads(resp)
        except Exception as e:
            print(f"Error fetching WP API page {page}: {e}")
            break

        if not posts:
            break

        for p in posts:
            if downloaded >= count:
                break
            title = p.get('title', {}).get('rendered', f"comic_{valid_seen+1}")
            slug = p.get('slug', f"comic_{valid_seen+1}")
            content = p.get('content', {}).get('rendered', '')

            # Extract comic image
            imgs = re.findall(r'<img[^>]+src=[\"\']([^\"\']+\.(?:jpg|png|jpeg))[\"\']', content)
            valid = [i for i in imgs if 'war-and-peas' not in i.lower() and 'profile' not in i.lower() and 'header' not in i.lower() and 'logo' not in i.lower()]
            if not valid and imgs:
                valid = [i for i in imgs if 'uploads' in i]

            if not valid:
                continue

            valid_seen += 1
            if valid_seen < start_num:
                continue

            img_url = valid[0]
            try:
                raw = fetch_url(img_url)
                im = Image.open(io.BytesIO(raw))
                formatted = apply_thermal_formatting(im)

                out_name = f"war_and_peas_{valid_seen:03d}_{slug}.jpg"
                out_path = os.path.join(out_dir, out_name)
                formatted.save(out_path, format='JPEG', quality=92)
                downloaded += 1
                clean_title = html.unescape(title)
                print(f"[War and Peas {downloaded}/{count}] (comic #{valid_seen}) {clean_title} -> {out_name} ({formatted.size})")
            except Exception as e:
                print(f"Error downloading {img_url}: {e}")
                continue

        page += 1

def main():
    start_num, count = get_range_selection()
    skip_count = start_num - 1
    end_num = start_num + count - 1

    print("\n" + "=" * 60)
    print(f"CONFIGURED RANGE:")
    print(f"  • Ignore/Skip: First {skip_count} images on each site")
    print(f"  • Download:    Next {count} images (items #{start_num} to #{end_num})")
    print("=" * 60)

    process_xkcd(start_num, count)
    process_sarah_andersen(start_num, count)
    process_loading_artist(start_num, count)
    process_war_and_peas(start_num, count)

    print("\n" + "=" * 60)
    print(f"ALL 4 COMIC SERIES PROCESSED SUCCESSFULLY!")
    print(f"Downloaded comics #{start_num} to #{end_num} ({count} images each).")
    print("=" * 60)

if __name__ == "__main__":
    main()
