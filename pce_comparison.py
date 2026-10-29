"""Adjacent PCE comparisons from the same BEA release and its linked workbook."""
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse
from cpi_release import MONTH, MONTHS, previous_period
from macro_result_display import finite

KEYS = ("monthly", "core_monthly", "annual", "core_annual")
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def inline_previous(text, year, month, current):
    previous_month = previous_period(year, month)[1]
    pattern = (r"Personal Income and Related Measures\s*\[Percent change from preceding month\]\s*"
               r"("+MONTH+r")\s+("+MONTH+r").{0,650}?PCE price index\s+([-+]?\d+\.\d+)\s+([-+]?\d+\.\d+)"
               r"\s+PCE price index,? excluding food and energy\s+([-+]?\d+\.\d+)\s+([-+]?\d+\.\d+)")
    m = re.search(pattern, text, re.I)
    if not m or MONTHS[m[1].lower()] != previous_month or MONTHS[m[2].lower()] != month:
        return {}
    if abs(float(m[4])-current["monthly"])>.001 or abs(float(m[6])-current["core_monthly"])>.001:
        raise ValueError("PCE主文與月增率表不一致")
    return {"monthly": float(m[3]), "core_monthly": float(m[5])}


def workbook_previous(payload, year, month, current):
    """Only exact adjacent-month pairs in Historical Comparisons are eligible."""
    z = zipfile.ZipFile(io.BytesIO(payload))
    if sum(x.file_size for x in z.infolist()) > 8_000_000:
        raise ValueError("PCE比較表過大")
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        strings = ["".join(x.itertext()) for x in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si",NS)]
    results = {}
    prior = "%04dM%02d" % previous_period(year,month)
    current_heading = f"{next(k for k,v in MONTHS.items() if v==month)} {year} personal income and outlays"
    for name in z.namelist():
        if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
            continue
        rows = []
        for row in ET.fromstring(z.read(name)).findall(".//m:row", NS):
            values = {}
            for cell in row.findall("m:c", NS):
                value = cell.find("m:v", NS)
                if cell.get("t") == "inlineStr":
                    text = "".join(cell.find("m:is",NS).itertext())
                elif value is not None:
                    text = strings[int(value.text)] if cell.get("t")=="s" else value.text
                else:
                    continue
                values[re.sub(r"\d","",cell.get("r",""))] = str(text).strip()
            rows.append(values)
        heading = " ".join(v for row in rows[:6] for v in row.values()).lower()
        if current_heading not in heading or "historical comparisons" not in heading:
            continue
        active, kind = False, None
        for row in rows:
            label = row.get("A","").strip().lower()
            if label == "chain-type price indexes":
                active = True; continue
            if not active:
                continue
            if label == "percent change from preceding month:":
                kind = "monthly"; continue
            if label == "percent change from month one year ago:":
                kind = "annual"; continue
            if label not in {"pce","pce, excluding food and energy"} or not kind:
                continue
            key = ("core_" if "excluding" in label else "")+kind
            try:
                actual = float(row["B"])
                if not finite(actual) or abs(actual-current[key])>.001:
                    raise ValueError("PCE主文與比較表本次不一致")
                matched = [float(row[b]) for a,b in (("C","D"),("E","F"),("G","H")) if row.get(a)==prior]
                if matched and (not all(finite(x) for x in matched) or len(set(matched))!=1):
                    raise ValueError("PCE比較表前月衝突")
            except (KeyError, TypeError):
                continue
            if matched:
                if key in results and results[key]!=matched[0]:
                    raise ValueError("PCE比較表重複數值衝突")
                results[key] = matched[0]
    return results


def enrich(item, fetch_text, fetch_bytes):
    url = item.get("url","")
    parsed = urlparse(url)
    # Do not follow a redirected source, guessed archive, API, or unrelated workbook.
    if parsed.scheme!="https" or parsed.hostname!="www.bea.gov" or not re.fullmatch(
            r"/news/20\d{2}/personal-income-and-outlays-[a-z]+-20\d{2}", parsed.path):
        return item
    try:
        from macro_result_integrity import clean, pce_values
        raw = fetch_text(url)
        result = dict(item,summary=clean(raw))
        year,month,current,missing = pce_values(result)
        if missing:
            return item
        prior = inline_previous(clean(raw),year,month,current)
        sources = [url]
        for target in re.findall(r'href\s*=\s*["\x27]([^"\x27]+)["\x27]', raw, re.I):
            target = urljoin(url,target)
            link = urlparse(target)
            if (link.scheme!="https" or link.hostname!="www.bea.gov"
                    or not re.fullmatch(r"/sites/default/files/20\d{2}-\d{2}/pi\d{4}-hist\.xlsx",link.path)):
                continue
            # The file's reference month/year must match this actual release.
            if link.path.rsplit("/",1)[-1] != f"pi{month:02d}{year%100:02d}-hist.xlsx":
                continue
            try:
                extra = workbook_previous(fetch_bytes(target),year,month,current)
            except (OSError, zipfile.BadZipFile, ET.ParseError):
                break
            for key,value in extra.items():
                if key in prior and abs(prior[key]-value)>.001:
                    raise ValueError("PCE兩張附表前值不一致")
                prior[key] = value
            sources.append(target)
            break
        return dict(result,pce_previous=prior,pce_previous_period="%04d/%02d"%previous_period(year,month),
                    pce_source_urls=sources)
    except ValueError as exc:
        return dict(item,pce_comparison_error=str(exc))
    except Exception:
        return item  # Main confirmed values stay usable; no invented comparison.

