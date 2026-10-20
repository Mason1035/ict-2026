"""FastAPI composition root: durable ingestion, configurable MQTT and vision.

One local process owns the demo scheduler and MQTT clients. External device
traffic enters through configured MQTT, never the explicit MOCK injection API.
"""
from __future__ import annotations

from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4
import asyncio
import json
import secrets
import sys
import time

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from . import __version__, tinyquake
from .settings import Settings, REPO_ROOT
from .database import Database, utc_now
from .telemetry import IngestionError, ingest_telemetry, validate_telemetry
from .connectors import ConnectorError, MQTTManager, list_connectors, get_connector, save_connector, delete_connector, test_connector
from .vision import VisionService, VisionError
from .demo import BackendDemo, SITE, DEVICE
from .dashboard import latest, history, normalize_time_filter


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ConnectorInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["mqtt", "http_json"] = "mqtt"
    source: Literal["MOCK", "REAL"] = "MOCK"
    enabled: StrictBool = False
    config: dict[str, Any]


class TestInjection(StrictModel):
    payload: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)


class ScenarioInput(StrictModel):
    scenario: Literal["A", "B", "C", "D"]


class DemoControl(StrictModel):
    running: StrictBool


class Roi(StrictModel):
    x: int = Field(ge=0, strict=True)
    y: int = Field(ge=0, strict=True)
    width: int = Field(gt=0, strict=True)
    height: int = Field(gt=0, strict=True)


class AnalysisInput(StrictModel):
    evidence_id: str
    reference_id: str | None = None
    roi: Roi | None = None


class AckInput(StrictModel):
    note: str = Field(default="", max_length=500)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings.database_path)
    mqtt = MQTTManager(db)
    started = time.monotonic()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        db.initialize()
        app.state.db = db
        app.state.vision = VisionService(db, settings.media_dir)
        app.state.demo = BackendDemo(db, settings.demo_enabled)
        app.state.settings = settings
        if settings.demo_enabled and latest(db, device_id=DEVICE) is None:
            app.state.demo.sample()
        mqtt.start()

        async def clock():
            while True:
                await asyncio.sleep(settings.demo_interval)
                try:
                    await run_in_threadpool(app.state.demo.tick)
                except Exception:
                    # A failed demo producer does not stop real ingestion.
                    app.state.demo_error = "后端演示采样失败，请检查数据库状态"

        worker = asyncio.create_task(clock()) if settings.demo_enabled else None
        try:
            yield
        finally:
            if worker:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker
            await run_in_threadpool(mqtt.stop)
            db.close()

    app = FastAPI(title="智哨防灾 · 多模态平台 API", version=__version__, lifespan=lifespan,
                  description="Local software integration. MOCK and operational sources are isolated; OpenCV observations are uncalibrated.")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins),
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if not settings.api_token and request.client and request.client.host not in {"127.0.0.1", "::1", "localhost"}:
                return JSONResponse({"detail": "本地模式只接受 loopback 请求；远程部署需配置 API Token"}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin not in settings.allowed_origins:
                return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
            length = request.headers.get("content-length")
            if length:
                try:
                    if int(length) > 13 * 1024 * 1024:
                        return JSONResponse({"detail": "Request exceeds 13 MiB limit"}, status_code=413)
                except ValueError:
                    return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    async def authorize(request: Request):
        if settings.api_token:
            expected = f"Bearer {settings.api_token}"
            if not secrets.compare_digest(request.headers.get("authorization", "").encode("utf-8"), expected.encode("utf-8")):
                raise HTTPException(401, "需要有效的后端 API Token", headers={"WWW-Authenticate": "Bearer"})

    for exception_type in (IngestionError, ConnectorError, VisionError):
        async def handle_service_error(request, exc):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        app.add_exception_handler(exception_type, handle_service_error)

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(authorize)])

    def audit(kind, message, *, site_id=None, device_id=None, source="SYSTEM", details=None):
        with db.connection() as c:
            c.execute("INSERT INTO events(id,kind,message,site_id,device_id,source,details_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                      (str(uuid4()),kind,message,site_id,device_id,source,json.dumps(details or {},ensure_ascii=False),utc_now()))

    def filtered_rows(table, *, site_id=None, device_id=None, source=None, limit=100, before=None, after=None):
        # table names are internal constants; all user inputs remain parameters.
        where, args = [], []
        for name, value in (("site_id",site_id),("device_id",device_id),("source",source)):
            if value is not None:
                where.append(f"{name}=?")
                args.append(value)
        for op, value, field in (("<",before,"before"),(">=",after,"after")):
            if value is not None:
                try:
                    boundary = normalize_time_filter(value, field)
                except ValueError as exc:
                    raise HTTPException(422,str(exc)) from exc
                where.append(f"created_at{op}?")
                args.append(boundary)
        query = f"SELECT * FROM {table}" + (" WHERE "+" AND ".join(where) if where else "")
        with db.connection() as c:
            return [dict(r) for r in c.execute(query+" ORDER BY created_at DESC,id DESC LIMIT ?",(*args,limit)).fetchall()]

    @api.get("/health")
    def health():
        with db.connection() as c:
            c.execute("SELECT 1").fetchone()
            counts = {name:c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for name,table in (("telemetry","telemetry"),("alarms","alarms"),("evidence","vision_evidence"),("quarantine","quarantine"))}
        return {"status":"ok", "version":__version__, "uptime_seconds":round(time.monotonic()-started),
                "storage":{"durable":True,"engine":"sqlite_wal","node_cleanup_authorized":False},
                "auth_mode":"bearer" if settings.api_token else "local_loopback", "counts":counts,
                "demo":app.state.demo.state(),"mqtt":mqtt.statuses(), "demo_error":getattr(app.state,"demo_error",None),
                "capabilities":{"mqtt":"implemented", "http_device_ingress":"test_only", "lora_binary":"not_configured",
                    "vision":"opencv_baseline", "vision_score":"uncalibrated", "atlas_acl":"not_connected", "cloud":"not_connected"}}

    @api.get("/sites")
    def sites():
        with db.connection() as c:
            rows = c.execute("SELECT site_id,source,count(DISTINCT device_id) AS device_count FROM telemetry GROUP BY site_id,source").fetchall()
        return {"items":[dict(r) for r in rows]}

    def device_items(site_id=None, source=None):
        where, args = ["is_current=1"], []
        for name,value in (("site_id",site_id),("source",source)):
            if value is not None:
                where.append(f"{name}=?")
                args.append(value)
        with db.connection() as c:
            rows=c.execute("SELECT site_id,device_id,source,scope,received_at AS last_received_at FROM telemetry WHERE "+" AND ".join(where)+" ORDER BY site_id,device_id",args).fetchall()
        return {"items":[dict(r) for r in rows]}

    @api.get("/devices")
    def devices(site_id: str | None=None, source: Literal["REAL","MOCK"] | None=None):
        return device_items(site_id,source)

    @api.get("/sites/{site_id}/devices")
    def site_devices(site_id:str, source: Literal["REAL","MOCK"] | None=None):
        return device_items(site_id,source)

    @api.get("/devices/{device_id}/telemetry")
    def telemetry_history(device_id:str,site_id:str|None=None,source:Literal["REAL","MOCK"]|None=None,
                          limit:int=Query(120,ge=1,le=500),before:str|None=None,after:str|None=None,cursor:str|None=None):
        try:
            return history(db,device_id=device_id,site_id=site_id,source=source,limit=limit,before=before,after=after,cursor=cursor)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc

    @api.post("/ingest/test",status_code=201)
    def inject_test(body:TestInjection):
        if not settings.demo_enabled:
            raise HTTPException(403,"测试注入已禁用")
        if not str(body.payload.get("device_id","")).startswith(("MOCK-","DEMO-")):
            raise HTTPException(422,"测试入口仅接受独立 MOCK-/DEMO- 设备 ID；不会改写原始身份")
        return ingest_telemetry(db,body.payload,source="MOCK",scope="TEST_ONLY",transport="http_test",context=body.context)

    @api.get("/connectors")
    def connector_list():
        statuses={r["connector_id"]:r for r in mqtt.statuses()}
        return {"items":[{**r,"status":statuses.get(r["id"],{"state":"disabled","connected":False})} for r in list_connectors(db)]}

    @api.post("/connectors",status_code=201)
    def connector_create(body:ConnectorInput):
        row=save_connector(db,body.model_dump())
        mqtt.reload()
        audit("configuration","已创建连接器",details={"connector_id":row["id"],"version":row["version"]})
        return row

    @api.put("/connectors/{connector_id}")
    def connector_update(connector_id:str,body:ConnectorInput):
        row=save_connector(db,body.model_dump(),connector_id=connector_id)
        mqtt.reload()
        audit("configuration","已更新连接器",details={"connector_id":row["id"],"version":row["version"]})
        return row

    @api.delete("/connectors/{connector_id}")
    def connector_delete(connector_id:str):
        delete_connector(db,connector_id)
        mqtt.reload()
        audit("configuration","已删除连接器",details={"connector_id":connector_id})
        return {"deleted":True}

    @api.post("/connectors/{connector_id}/test")
    def connector_test(connector_id:str):
        return test_connector(db,connector_id,timeout=4)

    @api.get("/alarms")
    def alarm_list(site_id:str|None=None,device_id:str|None=None,source:Literal["REAL","MOCK"]|None=None,
                   limit:int=Query(100,ge=1,le=500),before:str|None=None,after:str|None=None):
        return {"items":filtered_rows("alarms",site_id=site_id,device_id=device_id,source=source,limit=limit,before=before,after=after)}

    @api.post("/alarms/{alarm_id}/ack")
    def acknowledge(alarm_id:str,body:AckInput|None=None):
        with db.connection() as c:
            row=c.execute("SELECT * FROM alarms WHERE id=?",(alarm_id,)).fetchone()
            if row is None:
                raise HTTPException(404,"告警不存在")
            if not row["acknowledged"]:
                c.execute("UPDATE alarms SET acknowledged=1,acknowledged_at=? WHERE id=?",(utc_now(),alarm_id))
                audit("alarm_acknowledged","人工确认仅表示已读，不解除设备风险",site_id=row["site_id"],device_id=row["device_id"],source=row["source"],details={"alarm_id":alarm_id,"note":body.note if body else ""})
            return dict(c.execute("SELECT * FROM alarms WHERE id=?",(alarm_id,)).fetchone())

    @api.get("/events")
    def events(site_id:str|None=None,device_id:str|None=None,source:Literal["REAL","MOCK"]|None=None,
               limit:int=Query(100,ge=1,le=500),before:str|None=None,after:str|None=None):
        return {"items":filtered_rows("events",site_id=site_id,device_id=device_id,source=source,limit=limit,before=before,after=after)}

    @api.get("/quarantine")
    def quarantine(limit:int=Query(50,ge=1,le=200)):
        # Raw rejected messages may contain sensitive device payloads, so only
        # summaries are exposed; broker credentials are never copied here.
        with db.connection() as c:
            rows=c.execute("SELECT id,source,transport,connector_id,topic,reason,created_at FROM quarantine ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
        return {"items":[dict(r) for r in rows]}

    @api.post("/evidence",status_code=201)
    async def upload(file:Annotated[UploadFile,File()],site_id:Annotated[str,Form()],
                     device_id:Annotated[str|None,Form()]=None,camera_id:Annotated[str,Form()]="UPLOAD-01",
                     source:Annotated[Literal["REAL","MOCK","SYNTHETIC"],Form()]="MOCK",
                     scope:Annotated[Literal["OPERATIONAL","TEST_ONLY"],Form()]="TEST_ONLY",
                     capture_time:Annotated[str|None,Form()]=None):
        content=bytearray()
        try:
            while chunk:=await file.read(1024*1024):
                content.extend(chunk)
                if len(content)>12*1024*1024:
                    raise HTTPException(413,"图片最大 12 MiB")
        finally:
            await file.close()
        evidence=await run_in_threadpool(app.state.vision.upload,bytes(content),file.filename or "image",site_id=site_id,
                                        device_id=device_id,camera_id=camera_id,source=source,scope=scope,capture_time=capture_time)
        audit("evidence_uploaded","已保存图像证据",site_id=site_id,device_id=device_id,source=source,details={"evidence_id":evidence["id"]})
        return evidence

    @api.get("/evidence")
    def evidence_list(site_id:str|None=None,device_id:str|None=None,source:Literal["REAL","MOCK","SYNTHETIC"]|None=None,
                      camera_id:str|None=None,limit:int=Query(50,ge=1,le=200),cursor:str|None=None):
        return app.state.vision.evidence_page(site_id,limit,device_id=device_id,source=source,camera_id=camera_id,cursor=cursor)

    @api.get("/evidence/{evidence_id}")
    def evidence_detail(evidence_id:str):
        return app.state.vision.get_evidence(evidence_id)

    @api.get("/evidence/{evidence_id}/file")
    def evidence_file(evidence_id:str):
        data=app.state.vision.get_evidence(evidence_id)
        return FileResponse(app.state.vision.file_path(evidence_id),media_type=data["content_type"],headers={"Cache-Control":"private, no-store"})

    @api.post("/vision/analyze")
    def analyze(body:AnalysisInput):
        result=app.state.vision.analyze(body.evidence_id,body.reference_id,body.roi.model_dump() if body.roi else None)
        audit("vision_analyzed","OpenCV 基线完成；危险评分未标定",site_id=result["site_id"],source=result["source"],details={"result_id":result["id"]})
        return result

    @api.get("/vision/results")
    def vision_results(site_id:str|None=None,device_id:str|None=None,source:Literal["REAL","MOCK","SYNTHETIC"]|None=None,
                       camera_id:str|None=None,limit:int=Query(50,ge=1,le=200),cursor:str|None=None):
        return app.state.vision.results_page(site_id,limit,device_id=device_id,source=source,camera_id=camera_id,cursor=cursor)

    @api.get("/vision/results/{result_id}")
    def vision_result(result_id:str):
        return app.state.vision.get_result(result_id)

    @api.get("/vision/results/{result_id}/overlay")
    def overlay(result_id:str):
        return FileResponse(app.state.vision.result_overlay_path(result_id),media_type="image/png",headers={"Cache-Control":"private, no-store"})

    def require_demo():
        if not settings.demo_enabled:
            raise HTTPException(403,"后端演示已禁用")

    @api.post("/demo/scenario")
    def demo_scenario(body:ScenarioInput):
        require_demo()
        return app.state.demo.scenario(body.scenario)

    @api.post("/demo/control")
    def demo_control(body:DemoControl):
        require_demo()
        return app.state.demo.control(body.running)

    @api.post("/demo/step")
    def demo_step():
        require_demo()
        return app.state.demo.sample(advance=True)

    @api.post("/demo/reset")
    def demo_reset():
        require_demo()
        return app.state.demo.reset()

    @api.post("/demo/vision-samples")
    def vision_samples():
        require_demo()
        import cv2
        import numpy as np
        y,x=np.indices((400,640))
        texture=((x*7+y*11)%27).astype(np.uint8)
        frame=np.zeros((400,640,3),dtype=np.uint8)
        frame[:]=[139,161,146]
        frame=np.clip(frame.astype(np.int16)+texture[:,:,None],0,255).astype(np.uint8)
        cv2.line(frame,(0,320),(639,80),(210,220,225),9)
        cv2.rectangle(frame,(200,130),(330,240),(70,95,80),-1)
        current=frame.copy()
        current[130:241,200:331]=[145,167,150]
        current[150:261,230:361]=frame[130:241,200:331]
        cv2.putText(frame,"MOCK reference",(18,33),cv2.FONT_HERSHEY_SIMPLEX,.7,(25,50,30),2)
        cv2.putText(current,"MOCK current",(18,33),cv2.FONT_HERSHEY_SIMPLEX,.7,(25,50,30),2)
        now=datetime.now(timezone.utc)
        rows=[]
        for label,pixels,stamp in (("reference",frame,now-timedelta(seconds=1)),("current",current,now)):
            encoded=cv2.imencode(".png",pixels)[1].tobytes()
            rows.append(app.state.vision.upload(encoded,f"MOCK-{label}.png",site_id=SITE,device_id=DEVICE,camera_id="DEMO-CAMERA",source="MOCK",scope="TEST_ONLY",capture_time=stamp.isoformat()))
        result=app.state.vision.analyze(rows[1]["id"],rows[0]["id"])
        audit("vision_analyzed","MOCK 图像示例已生成并分析",site_id=SITE,device_id=DEVICE,source="MOCK",details={"result_id":result["id"]})
        return {"reference":rows[0],"current":rows[1],"result":result}

    @api.get("/dashboard")
    def dashboard(site_id:str=SITE,device_id:str=DEVICE,source:Literal["REAL","MOCK"]="MOCK"):
        current=latest(db,device_id=device_id,site_id=site_id,source=source,freshness_seconds=settings.freshness_seconds)
        entries=history(db,device_id=device_id,site_id=site_id,source=source,limit=120)["items"]
        charts=[{"time":r["received_at"],"score":r["risk"]["final_score"],**r["sensors"]} for r in reversed(entries)]
        alarm_rows=filtered_rows("alarms",site_id=site_id,device_id=device_id,source=source)
        event_rows=filtered_rows("events",site_id=site_id,source=source,limit=80)
        evidence_page=app.state.vision.evidence_page(site_id,200,device_id=device_id,source=source)
        results_page=app.state.vision.results_page(site_id,200,device_id=device_id,source=source)
        evidence=evidence_page["items"]
        results=results_page["items"]
        with db.connection() as c:
            count=c.execute("SELECT count(*) FROM telemetry WHERE site_id=? AND device_id=? AND source=?",(site_id,device_id,source)).fetchone()[0]
            alarm_count=c.execute("SELECT count(*) FROM alarms WHERE site_id=? AND device_id=? AND source=?",(site_id,device_id,source)).fetchone()[0]
        return {"site_id":site_id,"device_id":device_id,"source":source,"scope":current["scope"] if current else None,
                "latest":current,"history":charts,"alarms":alarm_rows,"events":event_rows,
                "stats":{"telemetry_count":count,"alarm_count":alarm_count,"evidence_count":evidence_page["total"],"vision_result_count":results_page["total"]},
                "demo":app.state.demo.state(),"connectors":connector_list()["items"],
                "vision":{"evidence":evidence,"results":results,"latest_result":results[0] if results else None,
                          "evidence_next_cursor":evidence_page["next_cursor"],"results_next_cursor":results_page["next_cursor"]}}

    @api.get("/tinyquake/results")
    def tinyquake_results(site_id:str|None=None,device_id:str|None=None,sensor_id:str|None=None,
                          source:Literal["REAL","MOCK"]|None=None,limit:int=Query(50,ge=1,le=200),cursor:str|None=None):
        return tinyquake.listing(db,site_id=site_id,device_id=device_id,sensor_id=sensor_id,source=source,limit=limit,cursor=cursor)

    @api.get("/tinyquake/streams")
    def tinyquake_streams():
        return tinyquake.streams(db)

    @api.post("/tinyquake/test",status_code=201)
    def tinyquake_test(body:TestInjection):
        require_demo()
        if body.payload.get("input_source") != "REFERENCE" or not str(body.payload.get("device_id", "")).startswith("MOCK-"):
            raise HTTPException(422,"HTTP 测试只接受 MOCK- 设备的参考波形结果；实际板卡请走 MQTT")
        return tinyquake.ingest(db,body.payload,source="MOCK")

    @api.get("/risk-results")
    def risk_results(site_id:str=SITE,device_id:str=DEVICE,source:Literal["REAL","MOCK"]="MOCK"):
        row=latest(db,device_id=device_id,site_id=site_id,source=source,freshness_seconds=settings.freshness_seconds)
        return {"items":[{"source_message_id":row["id"],"source":source,**row["risk"]}] if row else []}

    @api.get("/algorithms/capabilities")
    def algorithms():
        return {"sensor":{"provider":"B.telemetry_v2_intake","formal_configuration":"NOT_CONFIGURED","entry":"evaluate_telemetry_v2","runtime":"FeatureRiskRuntime"},
                "vision":{"provider":"opencv_baseline","calibrated":False,"model_version":None},
                "fusion":{"mode":"sensor_only","vision_score":None,"reason":"No calibrated vision score; no complete multimodal-risk claim"},
                "atlas":{"status":"NOT_CONNECTED"},"cloud":{"status":"NOT_CONNECTED"}}

    @api.post("/algorithms/sensor/inspect")
    def inspect_sensor(body:TestInjection):
        errors=validate_telemetry(body.payload)
        if errors:
            raise HTTPException(422,{"message":"Telemetry validation failed","errors":errors})
        # Consume the project's current B entry through its documented module
        # root. No DRAFT configuration is silently promoted to CALIBRATED.
        path=str(REPO_ROOT/"algorithm"/"B_revised")
        if path not in sys.path:
            sys.path.insert(0,path)
        from telemetry_v2_intake.entry import evaluate_telemetry_v2
        return evaluate_telemetry_v2(body.payload,context={"source":"MOCK","scope":"TEST_ONLY"})

    app.include_router(api)
    dist=REPO_ROOT/"apps"/"geohazard-demo"/"dist"
    if (dist/"assets").exists():
        app.mount("/assets",StaticFiles(directory=dist/"assets"),name="assets")

    @app.get("/favicon.svg",include_in_schema=False)
    def favicon():
        return FileResponse(REPO_ROOT/"apps"/"geohazard-demo"/"public"/"favicon.svg",media_type="image/svg+xml")

    @app.get("/",include_in_schema=False)
    def index():
        if not (dist/"index.html").exists():
            return JSONResponse({"message":"API 已启动；请运行前端 npm run build，或使用 Vite 开发服务器","docs":"/docs"})
        return FileResponse(dist/"index.html",media_type="text/html",headers={"Cache-Control":"no-cache"})

    return app


app=create_app()
