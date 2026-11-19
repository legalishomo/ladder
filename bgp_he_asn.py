#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""爬取 bgp.he.net/country/<CC> 的 ASN 列表，输出 Shadowrocket 规则。

用法:
  python3 bgp_he_asn.py                      # 默认 US，输出 asn_US.list
  python3 bgp_he_asn.py -c CN -p DIRECT      # 中国 ASN，策略 DIRECT
  python3 bgp_he_asn.py -f plain             # 只输出 ASN 号码
  python3 bgp_he_asn.py -f csv               # asn,名称
  python3 bgp_he_asn.py --dump-html x.html   # 保存原始页面，解析不到时排查用

依赖: 无，只用标准库 (Python 3.9+)
"""
import argparse
import html
import os
import re
import sys
import time
import urllib.error
import urllib.request
import gzip

URL = "https://bgp.he.net/country/{cc}"
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)

ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
ASN_RE = re.compile(r'href="/AS(\d+)"', re.I)
TAG_RE = re.compile(r"<[^>]+>")


def fetch(cc, retries=5, timeout=60.0):
    url = URL.format(cc=cc.upper())
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip",
    }
    last = None
    for i in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last = "HTTP %d" % e.code
        except Exception as e:  # URLError / 超时 / 连接重置等
            last = repr(e)
        wait = min(2 ** i, 30)
        print("[retry %d/%d] %s，%ds 后重试" % (i, retries, last, wait),
              file=sys.stderr)
        time.sleep(wait)
    raise RuntimeError("请求失败: %s (%s)" % (url, last))


def parse(page):
    """返回 [(asn:int, name:str)]，去重并按 ASN 排序。"""
    found = {}
    for row in ROW_RE.findall(page):
        m = ASN_RE.search(row)
        if not m:
            continue
        asn = int(m.group(1))
        cells = CELL_RE.findall(row)
        name = ""
        if len(cells) >= 2:
            name = html.unescape(TAG_RE.sub("", cells[1])).strip()
        found.setdefault(asn, name)
    # 兜底：表格结构变了时，直接抓所有 /AS123 链接
    if not found:
        for a in ASN_RE.findall(page):
            found.setdefault(int(a), "")
    return sorted(found.items())


def render(items, fmt, policy, cc, resolve):
    if fmt == "plain":
        return "\n".join(str(a) for a, _ in items) + "\n"
    if fmt == "csv":
        return "asn,name\n" + "\n".join(
            '%d,"%s"' % (a, n.replace('"', "'")) for a, n in items) + "\n"
    suffix = "" if resolve else ",no-resolve"
    lines = [
        "# bgp.he.net/country/%s ASN list for Shadowrocket" % cc.upper(),
        "# generated: %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "# total: %d" % len(items),
    ]
    for a, _ in items:
        lines.append("IP-ASN,%d,%s%s" % (a, policy, suffix))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="爬取 bgp.he.net 国家 ASN 列表")
    ap.add_argument("-c", "--country", default="US", help="国家代码，默认 US")
    ap.add_argument("-p", "--policy", default="PROXY",
                    help="规则策略，默认 PROXY")
    ap.add_argument("-f", "--format", choices=["rule", "plain", "csv"],
                    default="rule", help="输出格式，默认 rule")
    ap.add_argument("-o", "--output", help="输出文件，默认 asn_<CC>.list")
    ap.add_argument("--resolve", action="store_true",
                    help="规则不加 no-resolve（默认加）")
    ap.add_argument("--dump-html", metavar="FILE", help="保存原始页面")
    args = ap.parse_args()

    cc = args.country.upper()
    page = fetch(cc)
    if args.dump_html:
        with open(args.dump_html, "w", encoding="utf-8") as f:
            f.write(page)

    items = parse(page)
    if not items:
        print("没有解析到任何 ASN，可能被拦截或页面结构变了；"
              "用 --dump-html 保存页面检查", file=sys.stderr)
        sys.exit(1)

    out = args.output or "asn_%s.list" % cc
    d = os.path.dirname(out)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(items, args.format, args.policy, cc, args.resolve))
    print("完成: %s 共 %d 个 ASN -> %s" % (cc, len(items), out))


if __name__ == "__main__":
    main()
