#!/usr/bin/env python3
"""Loopback-only viewer for raw science products read back from Yamcs."""

from __future__ import annotations

from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import csv
import hashlib
import io
import json
from urllib import error, parse, request
import threading
from typing import Any

from pulse_analysis import parse_pulses


DEFAULT_URL = "http://127.0.0.1:8090"
DEFAULT_INSTANCE = "fprime-project"
DEFAULT_BUCKET = "fprimeFilesIn"
RECEIPT_EVENT = "GroundScienceReceiptVerified"
MAX_RAW_BYTES = 1024 * 1024
MAX_RECEIPTS = 20
HTTP_TIMEOUT_S = 5.0


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def parse_count_csv(raw: bytes) -> dict[str, Any]:
    """Summarize the simulator's CSV counts as count-frequency bins."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("science product is not UTF-8 CSV") from exc
    rows = csv.DictReader(io.StringIO(text, newline=""))
    if not rows.fieldnames or not {"t_s", "counts", "flag"}.issubset(rows.fieldnames):
        raise ValueError("science CSV must contain t_s,counts,flag columns")
    frequencies: Counter[int] = Counter()
    total_counts = 0
    window_count = 0
    flags: Counter[str] = Counter()
    for row in rows:
        if window_count >= 100_000:
            raise ValueError("science CSV exceeds the viewer's 100000-row limit")
        try:
            float(row["t_s"])
            count = int(row["counts"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid t_s/counts value at CSV row {window_count + 2}") from exc
        if count < 0:
            raise ValueError("science count values must be nonnegative")
        frequencies[count] += 1
        total_counts += count
        flags[(row["flag"] or "").strip() or "BG"] += 1
        window_count += 1
    if not window_count:
        raise ValueError("science CSV contains no data rows")
    return {
        "windows": window_count,
        "totalCounts": total_counts,
        "frequencies": {str(value): frequencies[value] for value in sorted(frequencies)},
        "flagFrequencies": dict(sorted(flags.items())),
        "label": "Simulated count-frequency (not a detector-energy histogram)",
    }


def _page_html() -> bytes:
    return r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Neutron-2 Ground Science Viewer</title><style>
:root{color-scheme:light dark;font:16px system-ui,sans-serif}body{max-width:1000px;margin:2rem auto;padding:0 1rem;background:#101820;color:#edf3f7}
h1{margin-bottom:.25rem}.muted{color:#aab9c5}.card{background:#1c2a35;border:1px solid #344958;border-radius:12px;padding:1rem;margin:1rem 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:.75rem}.metric{background:#14212a;padding:.7rem;border-radius:8px;overflow-wrap:anywhere}
dt{color:#aab9c5;font-size:.85rem}dd{margin:.2rem 0 0;font-weight:600;overflow-wrap:anywhere}a{color:#72d1ff}.barrow{display:grid;grid-template-columns:5rem 1fr 3rem;gap:.5rem;align-items:center;margin:.35rem 0}
.bar{height:1rem;background:#3286b5;border-radius:4px;min-width:2px}.error{color:#ff9a8a;white-space:pre-wrap}
.simulated{border:1px solid #e5ad48;background:#42351d;color:#ffe0a0;padding:.55rem .7rem;border-radius:7px;font-weight:700;display:inline-block}
.plot-wrap{overflow-x:auto}.plot{width:100%;min-width:620px;height:auto;background:#13202a;border-radius:8px}.plot-card{margin-top:1.25rem}.plot-caption{color:#aab9c5}.wave-controls{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;margin:.6rem 0}select{font:inherit;padding:.35rem;color:inherit;background:#14212a;border:1px solid #526978;border-radius:5px}
</style></head><body>
<h1>Neutron-2 Ground Science</h1>
<p class="muted">Products shown here are fetched from Yamcs and checked against their ground receipt. Pulse products are simulated; their charge axis is ADC-sample area, not energy.</p>
<div id="status" class="muted">Reading verified products from Yamcs…</div><main id="products"></main>
<script>
const statusNode=document.getElementById('status'), root=document.getElementById('products'), SVG_NS='http://www.w3.org/2000/svg';
function metric(card,label,value){const box=document.createElement('div');box.className='metric';const dt=document.createElement('dt');dt.textContent=label;const dd=document.createElement('dd');dd.textContent=String(value);box.append(dt,dd);card.append(box)}
function svgNode(name,attrs={}){const node=document.createElementNS(SVG_NS,name);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,String(value));return node}
function svgText(svg,x,y,text,attrs={}){const node=svgNode('text',{x,y,...attrs});node.textContent=String(text);svg.append(node);return node}
function plotSection(card,title,caption){const section=document.createElement('section');section.className='plot-card';const heading=document.createElement('h3');heading.textContent=title;section.append(heading);if(caption){const note=document.createElement('p');note.className='plot-caption';note.textContent=caption;section.append(note)}const wrap=document.createElement('div');wrap.className='plot-wrap';section.append(wrap);card.append(section);return wrap}
function makeSvg(wrap,width,height,label){const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':label,class:'plot'});wrap.append(svg);return svg}
function drawWaveform(wrap,wave){wrap.replaceChildren();if(!wave){const note=document.createElement('p');note.className='muted';note.textContent='No pulse events in this product.';wrap.append(note);return}const width=900,height=350,left=72,right=20,top=22,bottom=62,plotW=width-left-right,plotH=height-top-bottom;const svg=makeSvg(wrap,width,height,`Waveform event ${wave.eventId}, ADC versus time from event start in nanoseconds`);const times=wave.sampleTimesNs,first=times[0],last=times[times.length-1];
svg.append(svgNode('line',{x1:left,y1:top,x2:left,y2:top+plotH,stroke:'#aab9c5'}),svgNode('line',{x1:left,y1:top+plotH,x2:left+plotW,y2:top+plotH,stroke:'#aab9c5'}));for(let tick=0;tick<=4;tick++){const y=top+plotH-tick*plotH/4,value=Math.round(4095*tick/4);svg.append(svgNode('line',{x1:left-5,y1:y,x2:left+plotW,y2:y,stroke:'#344958','stroke-width':1}));svgText(svg,left-10,y+4,value,{'text-anchor':'end',fill:'#aab9c5','font-size':12})}
const makePath=(values,color)=>{const d=values.map((v,i)=>{const x=left+(times[i]-first)/(last-first||1)*plotW,y=top+plotH-Math.max(0,Math.min(4095,v))/4095*plotH;return `${i?'L':'M'}${x.toFixed(2)},${y.toFixed(2)}`}).join(' ');svg.append(svgNode('path',{d,fill:'none',stroke:color,'stroke-width':2}))};makePath(wave.rawSamples,'#55c6ff');makePath(wave.baselineCorrectedSamples,'#ffc45c');svgText(svg,left+plotW/2,height-18,'Time from pulse start (ns)',{'text-anchor':'middle',fill:'#edf3f7','font-size':14});const yLabel=svgText(svg,18,top+plotH/2,'ADC value (12-bit)',{'text-anchor':'middle',fill:'#edf3f7','font-size':14});yLabel.setAttribute('transform',`rotate(-90 18 ${top+plotH/2})`);svgText(svg,left,top+plotH+21,first,{'text-anchor':'middle',fill:'#aab9c5','font-size':12});svgText(svg,left+plotW,top+plotH+21,last,{'text-anchor':'middle',fill:'#aab9c5','font-size':12});svg.append(svgNode('line',{x1:left+12,y1:top+14,x2:left+38,y2:top+14,stroke:'#55c6ff','stroke-width':3}));svgText(svg,left+44,top+18,'Raw ADC',{fill:'#edf3f7','font-size':12});svg.append(svgNode('line',{x1:left+130,y1:top+14,x2:left+156,y2:top+14,stroke:'#ffc45c','stroke-width':3}));svgText(svg,left+162,top+18,'Baseline-corrected ADC',{fill:'#edf3f7','font-size':12});svgText(svg,width-right,top+18,`event ${wave.eventId} · ${wave.timestampNs} ns · channel ${wave.channel} · baseline ${wave.baseline} ADC`,{'text-anchor':'end',fill:'#aab9c5','font-size':12})}
function renderSpectrum(wrap,spectrum){const width=900,height=330,left=70,right=20,top=20,bottom=66,plotW=width-left-right,plotH=height-top-bottom,svg=makeSvg(wrap,width,height,'Integrated charge spectrum in ADC-sample area');const counts=spectrum.counts,max=Math.max(1,...counts),slot=plotW/counts.length;svg.append(svgNode('line',{x1:left,y1:top,x2:left,y2:top+plotH,stroke:'#aab9c5'}),svgNode('line',{x1:left,y1:top+plotH,x2:left+plotW,y2:top+plotH,stroke:'#aab9c5'}));counts.forEach((n,i)=>{const bh=n/max*(plotH-8),x=left+i*slot+1,y=top+plotH-bh;svg.append(svgNode('rect',{x,y,width:Math.max(1,slot-2),height:bh,rx:2,fill:'#45a3cf'}))});svgText(svg,left+plotW/2,height-19,spectrum.xLabel,{'text-anchor':'middle',fill:'#edf3f7','font-size':14});const yl=svgText(svg,18,top+plotH/2,'Events',{'text-anchor':'middle',fill:'#edf3f7','font-size':14});yl.setAttribute('transform',`rotate(-90 18 ${top+plotH/2})`);svgText(svg,left,top+plotH+22,spectrum.minimum,{'text-anchor':'middle',fill:'#aab9c5','font-size':12});svgText(svg,left+plotW,top+plotH+22,spectrum.maximum,{'text-anchor':'middle',fill:'#aab9c5','font-size':12});svgText(svg,left,top+12,`peak bin count ${max}`,{fill:'#aab9c5','font-size':12})}
function renderPsd(wrap,density){const counts=density.counts,cols=density.chargeBinCount,rows=density.psdBinCount,max=Math.max(1,...counts.flat()),cell=14,left=90,top=28,width=760,height=550,gridW=cols*cell,gridH=rows*cell,svg=makeSvg(wrap,width,height,'Pulse PSD density heatmap; charge in ADC-sample area and ratio from zero to one');for(let yb=0;yb<rows;yb++)for(let xb=0;xb<cols;xb++){const n=counts[yb][xb],t=n/max,r=Math.round(20+235*t),g=Math.round(42+145*t),b=Math.round(58+30*t),y=top+(rows-1-yb)*cell;svg.append(svgNode('rect',{x:left+xb*cell,y,width:cell,height:cell,fill:`rgb(${r},${g},${b})`,stroke:'#1c2a35','stroke-width':.6}))}svg.append(svgNode('rect',{x:left,y:top,width:gridW,height:gridH,fill:'none',stroke:'#aab9c5'}));svgText(svg,left+gridW/2,top+gridH+34,density.xLabel,{'text-anchor':'middle',fill:'#edf3f7','font-size':14});const yl=svgText(svg,25,top+gridH/2,density.yLabel,{'text-anchor':'middle',fill:'#edf3f7','font-size':14});yl.setAttribute('transform',`rotate(-90 25 ${top+gridH/2})`);svgText(svg,left,top+gridH+17,density.chargeMinimum,{'text-anchor':'middle',fill:'#aab9c5','font-size':11});svgText(svg,left+gridW,top+gridH+17,density.chargeMaximum,{'text-anchor':'middle',fill:'#aab9c5','font-size':11});svgText(svg,left-8,top+gridH,0,{'text-anchor':'end',fill:'#aab9c5','font-size':11});svgText(svg,left-8,top+10,1,{'text-anchor':'end',fill:'#aab9c5','font-size':11});svgText(svg,left+gridW+18,top+16,'events / bin',{fill:'#aab9c5','font-size':11});svgText(svg,left+gridW+18,top+36,`0 … ${max}`,{fill:'#edf3f7','font-size':11})}
function renderPulse(card,p){const s=p.science,banner=document.createElement('p');banner.className='simulated';banner.textContent=`SIMULATED · ${s.schema} · ${s.eventCount} events`;card.append(banner);const grid=document.createElement('dl');grid.className='grid';metric(grid,'Duration (s)',s.durationSeconds);metric(grid,'Seed',s.seed);metric(grid,'Sample interval (ns)',s.sampleIntervalNs);metric(grid,'ADC resolution',`${s.adcBits}-bit`);metric(grid,'Event count',s.eventCount);card.append(grid);const waveWrap=plotSection(card,'Waveform','Raw ADC and baseline-corrected ADC versus time from pulse start in nanoseconds.');const controls=document.createElement('div');controls.className='wave-controls';const label=document.createElement('label');label.textContent='Event waveform ';const select=document.createElement('select');select.setAttribute('aria-label','Select waveform event');for(const w of s.waveforms){const option=document.createElement('option');option.value=String(w.eventId);option.textContent=`event ${w.eventId} · ${w.timestampNs} ns`;select.append(option)}label.append(select);waveWrap.before(controls);controls.append(label);const activeWave=()=>s.waveforms.find(w=>String(w.eventId)===select.value);select.addEventListener('change',()=>drawWaveform(waveWrap,activeWave()));drawWaveform(waveWrap,activeWave());const spectrumWrap=plotSection(card,'Integrated charge spectrum','ADC-sample area; no conversion to keV or other energy units.');renderSpectrum(spectrumWrap,s.chargeSpectrum);const densityWrap=plotSection(card,'PSD density','Event counts per bin. No detector classification threshold is applied.');renderPsd(densityWrap,s.psdDensity)}
function renderCsv(card,p){const title=document.createElement('p');title.className='muted';title.textContent=p.histogram.label;card.append(title);const bins=Object.entries(p.histogram.frequencies),max=Math.max(1,...bins.map(([,n])=>n));for(const [count,n] of bins){const row=document.createElement('div');row.className='barrow';const label=document.createElement('span');label.textContent=count;const bar=document.createElement('div');bar.className='bar';bar.style.width=`${Math.max(1,100*n/max)}%`;bar.setAttribute('aria-label',`${n} windows with ${count} counts`);const value=document.createElement('span');value.textContent=String(n);row.append(label,bar,value);card.append(row)}const summary=document.createElement('p');summary.textContent=`${p.histogram.windows} windows · ${p.histogram.totalCounts} total counts`;card.append(summary)}
function render(p){const card=document.createElement('section');card.className='card';const h=document.createElement('h2');h.textContent=`Product ${p.productId} · transfer ${p.transferId}`;card.append(h);const grid=document.createElement('dl');grid.className='grid';metric(grid,'Run',p.runId);metric(grid,'Raw object',p.objectName);metric(grid,'Bytes',p.bytes);metric(grid,'SHA-256',p.readbackSha256);metric(grid,'CRC-16/CCITT',p.crc16CcittHex);card.append(grid);const link=document.createElement('a');link.href=p.rawUrl;link.textContent='Download raw Yamcs object';link.download=p.objectName;card.append(link);if(p.scienceType==='pulses'&&p.science)renderPulse(card,p);else renderCsv(card,p);root.append(card)}
fetch('/api/products').then(r=>{if(!r.ok)throw new Error(`Yamcs query returned HTTP ${r.status}`);return r.json()}).then(data=>{const products=data.products||[],errors=data.errors||[];statusNode.className=errors.length?'error':'muted';statusNode.textContent=products.length?`${products.length} verified product(s) read from Yamcs.`:'No verified ground receipts for this run yet.';if(errors.length)statusNode.textContent+=`\n${errors.length} receipt(s) skipped:\n`+errors.map(e=>`${e.receiptObject}: ${e.error}`).join('\n');products.forEach(render)}).catch(e=>{statusNode.className='error';statusNode.textContent=`Could not load Yamcs products: ${e}`});
</script></body></html>""".encode("utf-8")


class _LocalViewerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, service):
        self.service = service
        super().__init__(address, handler)


class LocalScienceViewer:
    """Serve a minimal ground browser, bound to loopback only."""

    def __init__(self, run_id: str, host: str = "127.0.0.1", port: int = 8063,
                 yamcs_url: str = DEFAULT_URL, instance: str = DEFAULT_INSTANCE,
                 bucket: str = DEFAULT_BUCKET) -> None:
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("science viewer may only bind to loopback")
        self.run_id = run_id
        self.host = host
        self.port = port
        self.yamcs_url = yamcs_url.rstrip("/")
        self.instance = instance
        self.bucket = bucket
        self.server = _LocalViewerServer((host, port), self._handler_class(), self)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       name="n2-science-viewer", daemon=True)
        self._started = False

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        if not self._started:
            self._started = True
            self.thread.start()

    def close(self) -> None:
        if self._started:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=0.5)
            self._started = False
        else:
            self.server.server_close()

    def _get_bytes(self, path: str, maximum: int) -> bytes:
        url = self.yamcs_url + "/api" + path
        with request.urlopen(url, timeout=HTTP_TIMEOUT_S) as response:
            data = response.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError("Yamcs object exceeds the viewer's size limit")
        return data

    def _events(self) -> list[dict]:
        query = parse.urlencode({"q": RECEIPT_EVENT, "limit": 100, "order": "desc"})
        data = json.loads(self._get_bytes(f"/archive/{parse.quote(self.instance, safe='')}/events?{query}", 2 * 1024 * 1024))
        events = data.get("events", data.get("event", []))
        return [event for event in events if event.get("type") == RECEIPT_EVENT
                and event.get("extra", {}).get("runId") == self.run_id]

    def _read_verified_raw(self, receipt_name: str) -> tuple[dict, bytes]:
        if (not receipt_name.startswith("n2-science-") or not receipt_name.endswith(".bin.receipt.json")
                or "/" in receipt_name or "\\" in receipt_name):
            raise ValueError("invalid receipt object name")
        receipt_path = (f"/storage/buckets/{parse.quote(self.bucket, safe='')}/objects/"
                        f"{parse.quote(receipt_name, safe='')}?instance={parse.quote(self.instance, safe='')}")
        receipt_bytes = self._get_bytes(receipt_path, 64 * 1024)
        manifest = json.loads(receipt_bytes)
        if manifest.get("verifiedGroundReceipt") is not True or manifest.get("runId") != self.run_id:
            raise ValueError("Yamcs receipt manifest is not verified for this local run")
        object_name = manifest.get("objectName")
        if (not isinstance(object_name, str) or not object_name.startswith("n2-science-")
                or not object_name.endswith(".bin") or "/" in object_name or "\\" in object_name):
            raise ValueError("receipt contains an invalid raw object name")
        raw_path = (f"/storage/buckets/{parse.quote(self.bucket, safe='')}/objects/"
                    f"{parse.quote(object_name, safe='')}?instance={parse.quote(self.instance, safe='')}")
        raw = self._get_bytes(raw_path, MAX_RAW_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        crc = crc16_ccitt(raw)
        if (len(raw) != int(manifest.get("bytes", -1))
                or digest != manifest.get("sha256")
                or crc != int(manifest.get("crc16Ccitt", -1))):
            raise ValueError("Yamcs raw object fails the receipt's byte/hash/CRC checks")
        if (manifest.get("productId") is None or manifest.get("transferId") is None
                or not isinstance(manifest.get("packetCount"), int)):
            raise ValueError("receipt omits its product transfer identity")
        product = dict(manifest)
        product.update({
            "receiptObject": receipt_name,
            "readbackSha256": digest,
            "readbackBytes": len(raw),
            "readbackCrc16Ccitt": crc,
            "crc16CcittHex": f"0x{crc:04X}",
        })
        return product, raw

    def _read_product(self, receipt_name: str) -> tuple[dict, bytes]:
        product, raw = self._read_verified_raw(receipt_name)
        if raw.lstrip().startswith(b"{"):
            science = parse_pulses(raw)
            product.update({"scienceType": science["scienceType"], "science": science})
        else:
            product["histogram"] = parse_count_csv(raw)
        return product, raw

    def _products_with_errors(self) -> tuple[list[dict], list[dict[str, str]]]:
        result = []
        errors = []
        for event in self._events()[:MAX_RECEIPTS]:
            receipt_name = event.get("extra", {}).get("receiptObject")
            if not isinstance(receipt_name, str):
                continue
            try:
                product, _ = self._read_product(receipt_name)
            except (error.HTTPError, error.URLError, TimeoutError, OSError, ValueError, KeyError,
                    TypeError, json.JSONDecodeError) as exc:
                print(f"[science-viewer] skipped receipt {receipt_name}: {exc}", flush=True)
                errors.append({"receiptObject": receipt_name[:200], "error": str(exc)[:240]})
                continue
            if str(product.get("productId")) != str(event.get("extra", {}).get("productId")):
                errors.append({"receiptObject": receipt_name[:200], "error": "product ID does not match receipt event"})
                continue
            extras = event.get("extra", {})
            if (str(product.get("transferId")) != str(extras.get("transferId"))
                    or product.get("objectName") != extras.get("objectName")
                    or product.get("receiptObject") != extras.get("receiptObject")
                    or product.get("sha256") != extras.get("sha256")
                    or str(product.get("bytes")) != str(extras.get("bytes"))
                    or str(product.get("crc16Ccitt")) != str(extras.get("crc16Ccitt"))):
                errors.append({"receiptObject": receipt_name[:200], "error": "receipt does not match ground receipt event"})
                continue
            product["rawUrl"] = "/api/products/" + parse.quote(receipt_name, safe="") + "/raw"
            product["receiptUrl"] = "/api/products/" + parse.quote(receipt_name, safe="") + "/receipt"
            result.append(product)
        return result, errors

    def products(self) -> list[dict]:
        """Preserve the original list API for local clients."""
        return self._products_with_errors()[0]

    def product_listing(self) -> dict[str, list]:
        products, errors = self._products_with_errors()
        return {"products": products, "errors": errors}

    def _handler_class(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                split = parse.urlsplit(self.path)
                try:
                    if split.path == "/":
                        self._send(200, _page_html(), "text/html; charset=utf-8")
                    elif split.path == "/api/products":
                        self._json(200, service.product_listing())
                    elif split.path == "/api/product":
                        receipt = parse.parse_qs(split.query).get("receipt", [""])[0]
                        product = next((p for p in service.products() if p["receiptObject"] == receipt), None)
                        if product is None:
                            self._json(404, {"error": "verified Yamcs receipt not found for this run"})
                        else:
                            self._json(200, product)
                    elif split.path.startswith("/api/products/"):
                        suffix = split.path[len("/api/products/"):]
                        if suffix.endswith("/raw"):
                            receipt = parse.unquote(suffix[:-4])
                            product, raw = service._read_verified_raw(receipt)
                            self._send(200, raw, "application/octet-stream", product["objectName"])
                        elif suffix.endswith("/receipt"):
                            receipt = parse.unquote(suffix[:-8])
                            product, _ = service._read_verified_raw(receipt)
                            receipt_path = (f"/storage/buckets/{parse.quote(service.bucket, safe='')}/objects/"
                                            f"{parse.quote(receipt, safe='')}?instance={parse.quote(service.instance, safe='')}")
                            manifest = service._get_bytes(receipt_path, 64 * 1024)
                            self._send(200, manifest, "application/json; charset=utf-8", receipt)
                        else:
                            receipt = parse.unquote(suffix)
                            product = next((p for p in service.products() if p["receiptObject"] == receipt), None)
                            if product is None:
                                self._json(404, {"error": "verified Yamcs receipt not found for this run"})
                            else:
                                self._json(200, product)
                    else:
                        self._json(404, {"error": "not found"})
                except (error.HTTPError, error.URLError, TimeoutError, OSError) as exc:
                    self._json(502, {"error": f"Yamcs request failed: {exc}"})
                except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                    self._json(422, {"error": str(exc)})

            def _json(self, status: int, value: Any) -> None:
                self._send(status, (json.dumps(value, sort_keys=True) + "\n").encode("utf-8"),
                           "application/json; charset=utf-8")

            def _send(self, status: int, body: bytes, content_type: str,
                      attachment_name: str | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                if attachment_name is not None:
                    clean_name = "".join(c for c in attachment_name if c.isalnum() or c in "._-")
                    self.send_header("Content-Disposition", f'attachment; filename="{clean_name}"')
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return

        return Handler
