"""ESP32 serial JSON -> loopback MQTT -> platform; never generates inference.

The local broker listens ONLY on 127.0.0.1. Stop other serial monitors before
running. GEOHAZARD_API_TOKEN supplies an optional local platform Bearer token.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MODEL_SHA256="0e1eb00a920ae3daaec7cf142ef8a54373fe1b93b472350e7048b8ae0c1ff1f1"


def result_from_line(line:bytes, source:str):
    if not line.startswith(b"TINYQUAKE_RESULT "):
        return None
    raw=line[len(b"TINYQUAKE_RESULT "):].strip()
    if len(raw)>262144:
        raise ValueError("串口结果过大")
    value=json.loads(raw)
    if not isinstance(value,dict): raise ValueError("串口结果必须是 JSON 对象")
    if value.get("schema")!="zhifang.tinyquake.result.v1" or value.get("model_sha256")!=MODEL_SHA256:
        raise ValueError("串口结果不是已评估的 CNN17")
    if source=="REAL" and value.get("input_source")!="SENSOR":
        raise ValueError("参考波形不能标记 REAL；请使用默认 MOCK")
    for key in ("site_id","device_id","sensor_id"):
        text=value.get(key)
        if not isinstance(text,str) or not text or len(text)>128 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in text):
            raise ValueError("无效的 Topic 身份")
    topic=f"zhifang/experimental/tinyquake/v1/{value['site_id']}/{value['device_id']}/{value['sensor_id']}/result"
    return value,topic,raw


def platform_request(base, path, body=None, method="GET"):
    headers={"Content-Type":"application/json"}
    token=os.environ.get("GEOHAZARD_API_TOKEN")
    if token: headers["Authorization"]="Bearer "+token
    request=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
    with urlopen(request,timeout=10) as response:
        return json.load(response)


def configure(base,site,source,port):
    rows=platform_request(base,"/connectors")["items"]
    body={"name":f"TinyQuake USB {port} {site} {source}","kind":"mqtt","source":source,"enabled":True,
          "config":{"host":"127.0.0.1","port":port,"site_id":site,"payload_format":"tinyquake_v1"}}
    existing=next((row for row in rows if row["name"]==body["name"]),None)
    if existing:
        saved=platform_request(base,"/connectors/"+existing["id"],body,"PUT")
    else:
        saved=platform_request(base,"/connectors",body,"POST")
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        rows=platform_request(base,"/connectors")["items"]
        if any(row["id"]==saved["id"] and row.get("status",{}).get("connected") for row in rows):
            return
        time.sleep(.1)
    raise OSError("平台 MQTT 订阅未就绪")


async def run(args):
    # Imports remain optional so --help and protocol tests do not need a serial
    # driver. No serial port is opened until the operator explicitly runs this.
    from amqtt.broker import Broker
    from paho.mqtt.publish import single
    import serial
    broker=Broker({"listeners":{"default":{"type":"tcp","bind":f"127.0.0.1:{args.broker_port}"}},
                   "plugins":{"amqtt.plugins.authentication.AnonymousAuthPlugin":{"allow_anonymous":True}},"sys_interval":0})
    configured=set()
    await broker.start()
    try:
        with serial.Serial(args.port,args.baud,timeout=1) as device:
            print(f"USB {args.port} → 本机 MQTT 127.0.0.1:{args.broker_port} → 平台。等待实际串口结果；Ctrl+C 停止。",flush=True)
            while True:
                line=await asyncio.to_thread(device.readline,262145)
                if not line: continue
                try:
                    result=result_from_line(line,args.source)
                    if result is None: continue
                    value,topic,raw=result
                    site=value["site_id"]
                    if site not in configured:
                        await asyncio.to_thread(configure,args.api,site,args.source,args.broker_port)
                        configured.add(site)
                    await asyncio.to_thread(single,topic,raw,hostname="127.0.0.1",port=args.broker_port,qos=0,retain=False)
                    print(f"已转发 {value['device_id']}/{value['sensor_id']} boot={value['boot_id']} seq={value['seq']} {value['input_source']}；保存结果以平台为准",flush=True)
                except (ValueError,TypeError,KeyError,HTTPError,URLError,OSError) as exc:
                    print(f"本条未转发：{type(exc).__name__}。检查串口格式、平台服务、API Token 或连接配置。",flush=True)
    finally:
        await broker.shutdown()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",required=True,help="ESP32 数据 USB 串口，例如 /dev/cu.usbmodem...")
    parser.add_argument("--baud",type=int,default=115200)
    parser.add_argument("--broker-port",type=int,default=18884)
    parser.add_argument("--api",default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--source",choices=["MOCK","REAL"],default="MOCK")
    args=parser.parse_args()
    args.api=args.api.rstrip("/")
    url=urlsplit(args.api)
    if url.scheme!="http" or url.hostname not in {"127.0.0.1","localhost","::1"} or url.username or url.password or url.query or url.fragment:
        parser.error("USB 桥仅允许本机 HTTP 平台地址，认证使用 GEOHAZARD_API_TOKEN")
    if not 1024<=args.broker_port<=65535: parser.error("broker-port 必须是 1024..65535")
    logging.basicConfig(level=logging.ERROR)
    try: asyncio.run(run(args))
    except KeyboardInterrupt: print("USB 桥已停止，平台保留历史；连接器可在页面停用。")


if __name__=="__main__": main()
