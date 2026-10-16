"""Explicit localhost-only MOCK broker/producer for exercising the full MQTT path.

Run with platform_backend/.venv/bin/python scripts/mqtt_demo.py. It never sends
to external brokers or uses a real NODE identity. Requires backend [dev] extras.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time

from amqtt.broker import Broker
from paho.mqtt.publish import single
from geohazard_platform.demo import SCENARIOS, fixture_payload


async def run(port: int, scenario: str):
    broker = Broker({
        "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
        "sys_interval": 0,
    })
    await broker.start()
    topic = "zhifang/v2/MOCK-LAB/MOCK-NODE-01/telemetry"
    print(f"MOCK Broker: 127.0.0.1:{port}\n站点 MOCK-LAB，来源 MOCK，Topic {topic}\n在平台连接配置中添加后即可选择 MOCK-NODE-01。Ctrl+C 停止。", flush=True)
    state = {"sensors": SCENARIOS[scenario], "boot_id": int(time.time()*1000), "seq": 0, "elapsed_seconds": 0}
    try:
        while True:
            state["seq"] += 1
            state["elapsed_seconds"] += 2
            payload=fixture_payload(state)
            payload.update(site_id="MOCK-LAB",device_id="MOCK-NODE-01")
            payload["experiment"]["run_id"]="LOCAL-MQTT-MOCK"
            payload["system"]["mqtt_up"]=True
            await asyncio.to_thread(single,topic,json.dumps(payload),hostname="127.0.0.1",port=port,qos=0)
            await asyncio.sleep(2)
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,default=18883)
    parser.add_argument("--scenario",choices=list(SCENARIOS),default="C")
    args=parser.parse_args()
    if not 1024<=args.port<=65535:
        parser.error("port must be 1024..65535")
    logging.basicConfig(level=logging.ERROR)
    try:
        asyncio.run(run(args.port,args.scenario))
    except KeyboardInterrupt:
        pass
