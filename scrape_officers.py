#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
隐名三国 武将DB 爬虫 (https://tka-officer.plotrick.com)

爬取全部武将数据，每名武将输出一条 JSON 记录，字段包含：
    - id            武将 id
    - name          选定语言的名称
    - names         全部语言名称 (ko/en/ja/zh-CN/zh-TW)
    - stats         能力值(统率/武力/智力/政治/魅力/野心/义理/名望)，每项为 [min, max] 区间
    - birth_year    出生年份 (整数)
    - death_year    死亡年份 (整数或 [起, 止] 区间)
    - hometown_id   地方区域标识 (数字)
    - hometown      故乡名称 (页面渲染的地名文本)
    - liked         喜欢的武将 id 列表
    - hated         厌恶的武将 id 列表

数据来源:
    - 列表页  /{locale}                 -> 全部武将的基础数据 (含能力值/年份/地方)
    - 详情页  /{locale}/officers/{id}    -> liked / hated (列表页不含此两项)

用法示例:
    python3 scrape_officers.py                 # 全量爬取, 输出 officers.jsonl + officers.json
    python3 scrape_officers.py --limit 5       # 只爬前 5 名(调试)
    python3 scrape_officers.py --resume        # 断点续爬
    python3 scrape_officers.py --locale en     # 换语言
"""

import argparse
import json
import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://tka-officer.plotrick.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# HTTP: 优先使用 requests, 否则回退到标准库 urllib
# ---------------------------------------------------------------------------
try:
    import requests

    _SESSION = requests.Session()
    _SESSION.headers.update({"User-Agent": USER_AGENT})

    def http_get(url, timeout=30):
        resp = _SESSION.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.text

except ImportError:  # 回退方案
    from urllib.request import Request, urlopen

    def http_get(url, timeout=30):
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
# 列表页 flight 载荷里的扁平武将对象(引号被转义成 \")，以 hometown_id 结尾
_OFFICER_RE = re.compile(
    r'\{\\"id\\":(?P<id>\d+),'
    r'\\"name\\":\{.*?\},'
    r'\\"stats\\":\{.*?\},'
    r'\\"birth_year\\":.*?,'
    r'\\"death_year\\":.*?,'
    r'\\"hometown_id\\":\\"[^"]*?\\"\}'
)

# 详情页中的 liked / hated 数组
_LIKED_RE = re.compile(r'\\"liked\\":(\[[0-9,]*\])')
_HATED_RE = re.compile(r'\\"hated\\":(\[[0-9,]*\])')

# 详情页渲染后的元信息行形如: 出生: 162 | 死亡: 219~229 | 故乡: 蓟
# 故乡名称是该块最后一个文本节点(紧接 SuggestionForm 区域之前), 与语言无关
_HOMETOWN_RE = re.compile(
    r'<!-- -->([^<>]*)</div></section><section class="SuggestionForm'
)


def _unescape_json(raw):
    """把 flight 载荷里的转义反斜杠去掉后再 json.loads。"""
    return json.loads(raw.replace('\\"', '"'))


def fetch_list(locale):
    """抓列表页, 返回 {id: base_record} 字典。"""
    url = "{}/{}".format(BASE_URL, locale)
    html = http_get(url)
    officers = {}
    for m in _OFFICER_RE.finditer(html):
        obj = _unescape_json(m.group(0))
        officers[obj["id"]] = obj
    if not officers:
        raise RuntimeError("未能从列表页解析到任何武将数据, 页面结构可能已变化: " + url)
    return officers


def fetch_detail(officer_id, locale, retries, delay):
    """抓详情页, 返回 (liked, hated, hometown)。失败时抛出最后一次异常。"""
    url = "{}/{}/officers/{}".format(BASE_URL, locale, officer_id)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            html = http_get(url)
            liked_m = _LIKED_RE.search(html)
            hated_m = _HATED_RE.search(html)
            home_m = _HOMETOWN_RE.search(html)
            liked = json.loads(liked_m.group(1).replace("\\", "")) if liked_m else []
            hated = json.loads(hated_m.group(1).replace("\\", "")) if hated_m else []
            hometown = home_m.group(1).strip() if home_m else ""
            return liked, hated, hometown
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries:
                time.sleep(delay * attempt)
    raise last_err


# ---------------------------------------------------------------------------
# 组装记录
# ---------------------------------------------------------------------------
def build_record(base, locale, liked, hated, hometown):
    names = base.get("name", {})
    return {
        "id": base["id"],
        "name": names.get(locale) or names.get("zh-CN") or names.get("en"),
        "names": names,
        "stats": base.get("stats", {}),
        "birth_year": base.get("birth_year"),
        "death_year": base.get("death_year"),
        "hometown_id": base.get("hometown_id"),
        "hometown": hometown,
        "liked": liked,
        "hated": hated,
    }


# ---------------------------------------------------------------------------
# 输出 / 断点续爬
# ---------------------------------------------------------------------------
def load_done_ids(jsonl_path):
    done = set()
    if os.path.exists(jsonl_path):
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line)["id"])
                except Exception:  # noqa: BLE001
                    pass
    return done


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="隐名三国 武将DB 爬虫")
    parser.add_argument("--locale", default="zh-CN",
                        help="语言 (zh-CN/zh-TW/en/ja/ko), 默认 zh-CN")
    parser.add_argument("--out", default="officers.jsonl",
                        help="JSONL 输出路径, 默认 officers.jsonl")
    parser.add_argument("--concurrency", type=int, default=8,
                        help="并发线程数, 默认 8")
    parser.add_argument("--delay", type=float, default=0.1,
                        help="每次请求前的礼貌间隔(秒), 默认 0.1")
    parser.add_argument("--retries", type=int, default=3,
                        help="详情页失败重试次数, 默认 3")
    parser.add_argument("--limit", type=int, default=0,
                        help="仅爬取前 N 名(调试用), 0 表示全部")
    parser.add_argument("--resume", action="store_true",
                        help="断点续爬: 跳过已在 JSONL 中的武将")
    args = parser.parse_args()

    jsonl_path = args.out
    json_path = os.path.splitext(jsonl_path)[0] + ".json"
    failed_path = "failed.txt"

    print("[1/3] 抓取武将列表 ...")
    base_map = fetch_list(args.locale)
    all_ids = sorted(base_map.keys())
    if args.limit > 0:
        all_ids = all_ids[: args.limit]
    print("      列表共 {} 名武将".format(len(all_ids)))

    done_ids = load_done_ids(jsonl_path) if args.resume else set()
    todo_ids = [i for i in all_ids if i not in done_ids]
    if done_ids:
        print("      续爬: 已完成 {} 名, 待爬 {} 名".format(len(done_ids), len(todo_ids)))

    print("[2/3] 抓取详情(喜欢/厌恶) ...")
    write_lock = threading.Lock()
    progress = {"done": 0, "fail": 0}
    total = len(todo_ids)
    failed_ids = []

    delay = args.delay

    def worker(oid):
        if delay:
            time.sleep(delay)
        liked, hated, hometown = fetch_detail(oid, args.locale, args.retries, delay)
        return build_record(base_map[oid], args.locale, liked, hated, hometown)

    # 追加模式写 jsonl (支持续爬)
    with open(jsonl_path, "a", encoding="utf-8") as jf:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            future_map = {pool.submit(worker, oid): oid for oid in todo_ids}
            for fut in as_completed(future_map):
                oid = future_map[fut]
                try:
                    record = fut.result()
                    with write_lock:
                        jf.write(json.dumps(record, ensure_ascii=False) + "\n")
                        jf.flush()
                        progress["done"] += 1
                except Exception as e:  # noqa: BLE001
                    progress["fail"] += 1
                    failed_ids.append(oid)
                    sys.stderr.write("  [失败] id={} {}\n".format(oid, e))
                completed = progress["done"] + progress["fail"]
                if completed % 25 == 0 or completed == total:
                    print("      进度 {}/{} (成功 {}, 失败 {})".format(
                        completed, total, progress["done"], progress["fail"]))

    if failed_ids:
        with open(failed_path, "w", encoding="utf-8") as ff:
            ff.write("\n".join(str(i) for i in sorted(failed_ids)))
        print("      失败 {} 名, 已写入 {}".format(len(failed_ids), failed_path))

    # 汇总生成 officers.json (数组), 按 id 去重排序
    print("[3/3] 汇总生成 {} ...".format(json_path))
    records = {}
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            records[rec["id"]] = rec
    ordered = [records[i] for i in sorted(records.keys())]
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)

    # 同步生成 officers.js, 供 index.html 以 file:// 直接打开时加载
    js_path = os.path.splitext(jsonl_path)[0] + ".js"
    with open(js_path, "w", encoding="utf-8") as f:
        f.write("// 本文件由 officers.json 自动生成, 供 file:// 直接打开 index.html 使用\n")
        f.write("window.OFFICERS_DATA = ")
        json.dump(ordered, f, ensure_ascii=False)
        f.write(";\n")

    print("完成: 共 {} 条 -> {} / {} / {}".format(
        len(ordered), jsonl_path, json_path, js_path))


if __name__ == "__main__":
    main()
