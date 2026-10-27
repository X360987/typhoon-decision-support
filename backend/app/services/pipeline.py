"""Clean -> map -> aggregate -> detect, per event, as one versioned analysis run.

All stages of a run share one transaction. Outputs (metrics, anomalies, evidence,
suggestions) are tagged with a new ``data_version``; the event's active-version
pointer is switched only after every stage succeeded. A failure rolls back the
run and keeps the previous version serving. Working tables (clean / region /
suspension mapping) are rebuilt per event and are not referenced by evidence,
which points at the immutable raw tables instead.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.domain.anomaly_rules import MetricPoint, run_all_detectors, summarize_tasks
from app.domain.geo import attribute_provinces
from app.domain.sentiment import get_sentiment_model
from app.domain.stats import safe_ratio
from app.domain.train_mapping import RegionHourHit, Stop, SuspensionInput, map_suspension
from app.models import (
    Account,
    ActiveVersion,
    AnalysisRun,
    Anomaly,
    AnomalyEvidence,
    Dataset,
    Event,
    MetricRegistry,
    ProvinceHourMetric,
    Suggestion,
    SuspensionRegionHour,
    TrainStop,
    TrainSuspension,
    WeiboClean,
    WeiboRaw,
    WeiboRegion,
)
from app.services.rules_loader import load_rules

NATIONAL = "ALL"
OFFICIAL_VERIFY_KEYWORDS = ("机构", "政府", "政务", "官方", "蓝V")
PERSONAL_VERIFY_KEYWORDS = ("个人", "黄V", "红V", "橙V")


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def _max_or_none(values: list[datetime | None], floor: datetime) -> datetime | None:
    """Availability of an aggregate: unknown if any input is unknown, never earlier than ``floor``."""
    if any(v is None for v in values):
        return None
    return max([floor, *values])  # type: ignore[list-item]


_PHONE = re.compile(r"(?<!\d)(1\d{2})\d{4}(\d{4})(?!\d)")
_IDNO = re.compile(r"(?<!\d)(\d{6})\d{8}(\d{3}[\dXx])(?!\d)")


def mask_text(text: str | None) -> str:
    if not text:
        return ""
    return _IDNO.sub(r"\1********\2", _PHONE.sub(r"\1****\2", text))


def mask_user(user_id: str | None) -> str:
    if not user_id:
        return ""
    if user_id.startswith("SIM-"):
        return user_id
    return user_id[:2] + "***" + user_id[-2:] if len(user_id) > 4 else "***"


def effective_available_at(raw: WeiboRaw) -> datetime | None:
    """Trusted arrival time; an arrival earlier than publication is not trusted."""
    if raw.available_at is None or raw.published_at is None:
        return None
    if raw.available_at < raw.published_at:
        return None
    return raw.available_at


def classify_account(raw: WeiboRaw, acc: Account | None, unverified_default: str) -> tuple[str, str]:
    if acc:
        return acc.account_class, "checklist"
    vt = str(raw.verify_type or "")
    if vt and any(k in vt for k in OFFICIAL_VERIFY_KEYWORDS):
        return "official", "verify_type"
    if vt and any(k in vt for k in PERSONAL_VERIFY_KEYWORDS):
        return "personal", "verify_type"
    return unverified_default, "unclassified"


def clean_weibo(db: Session, dataset_id: str, event_id: int) -> dict[str, Any]:
    rules = load_rules()
    unverified_default = rules.get("accounts", {}).get("unverified_default", "unknown")
    sentiment = get_sentiment_model()
    accounts = {a.user_id: a for a in db.query(Account).filter(Account.dataset_id == dataset_id).all()}
    raws = db.query(WeiboRaw).filter(WeiboRaw.dataset_id == dataset_id, WeiboRaw.event_id == event_id).all()
    clean_ids = [
        c.id
        for c in db.query(WeiboClean.id).filter(WeiboClean.dataset_id == dataset_id, WeiboClean.event_id == event_id)
    ]
    if clean_ids:
        db.execute(delete(WeiboRegion).where(WeiboRegion.weibo_clean_id.in_(clean_ids)))
    db.execute(delete(WeiboClean).where(WeiboClean.dataset_id == dataset_id, WeiboClean.event_id == event_id))
    db.flush()

    cleaned = 0
    unknown_region = 0
    classes: dict[str, int] = defaultdict(int)
    untrusted_arrival = 0
    for raw in raws:
        if raw.published_at is None:
            continue
        acc = accounts.get(raw.user_id)
        account_class, basis = classify_account(raw, acc, unverified_default)
        classes[account_class] += 1
        avail = effective_available_at(raw)
        if avail is None:
            untrusted_arrival += 1
        sent = sentiment.classify(raw.content or "")
        interaction = (raw.reposts or 0) + (raw.comments or 0) + (raw.likes or 0)
        topics = [t for t in (raw.topics or "").replace("，", ",").split("#") if t.strip()]
        wc = WeiboClean(
            dataset_id=dataset_id,
            event_id=raw.event_id,
            weibo_raw_id=raw.id,
            user_id=raw.user_id,
            account_class=account_class,
            published_at=raw.published_at,
            available_at=avail,
            hour_bj=_floor_hour(raw.published_at),
            sentiment_label=sent.label,
            sentiment_score=sent.score,
            sentiment_model_version=sent.model_version,
            interaction=interaction,
            is_help_request=sent.is_help_request,
            topics=topics,
            publisher_home_province=acc.home_province if acc else None,
            quality_flags={"account_basis": basis, "arrival_trusted": avail is not None},
        )
        db.add(wc)
        db.flush()
        attrs = attribute_provinces(raw.content, raw.publish_location, raw.ip)
        if not attrs:
            unknown_region += 1
        for code, method in attrs:
            db.add(
                WeiboRegion(
                    dataset_id=dataset_id,
                    event_id=raw.event_id,
                    weibo_clean_id=wc.id,
                    province_code=code,
                    attribution_method=method,
                    is_unique_count=True,
                )
            )
        cleaned += 1
    db.flush()
    return {
        "cleaned": cleaned,
        "unknown_region": unknown_region,
        "account_classes": dict(classes),
        "untrusted_arrival": untrusted_arrival,
    }


def map_suspensions(db: Session, dataset_id: str, event_id: int) -> dict[str, Any]:
    ds = db.get(Dataset, dataset_id)
    is_demo = bool(ds and ds.data_mode == "demo")
    stops = [
        Stop(
            train_code=s.train_code,
            stop_order=s.stop_order,
            station_name=s.station_name,
            province_code=s.province_code,
            arrive_time=s.arrive_time,
            depart_time=s.depart_time,
            timetable_version=s.timetable_version,
            valid_from=s.valid_from,
            valid_to=s.valid_to,
        )
        for s in db.query(TrainStop).filter(TrainStop.dataset_id == dataset_id).all()
    ]
    db.execute(
        delete(SuspensionRegionHour).where(
            SuspensionRegionHour.dataset_id == dataset_id, SuspensionRegionHour.event_id == event_id
        )
    )
    db.flush()
    sus_list = (
        db.query(TrainSuspension)
        .filter(TrainSuspension.dataset_id == dataset_id, TrainSuspension.event_id == event_id)
        .all()
    )
    mapped = 0
    pending: list[dict[str, Any]] = []
    for sus in sus_list:
        payload = sus.raw_payload if isinstance(sus.raw_payload, dict) else {}
        result = map_suspension(
            SuspensionInput(
                suspension_id=sus.id,
                train_code=sus.train_code,
                suspension_date=sus.suspension_date,
                segment_start=sus.segment_start,
                segment_end=sus.segment_end,
                timetable_version=payload.get("timetable_version"),
            ),
            stops,
        )
        hits = list(result.hits)
        if result.status != "mapped":
            pending.append(
                {"suspension_id": sus.id, "record_no": sus.record_no, "train_code": sus.train_code, "reason": result.reason}
            )
        force_p = payload.get("force_province") if is_demo else None
        if force_p:
            hour = _floor_hour(sus.suspension_date)
            match = next((h for h in hits if h.province_code == force_p and h.hour_bj == hour), None)
            if match is None:
                hits.append(
                    RegionHourHit(
                        suspension_id=sus.id,
                        province_code=force_p,
                        hour_bj=hour,
                        train_code=sus.train_code,
                        estimate_basis="seed_force_province",
                        run_key=result.run_key,
                        stations=[],
                    )
                )
        for hit in hits:
            db.add(
                SuspensionRegionHour(
                    dataset_id=dataset_id,
                    event_id=event_id,
                    suspension_id=hit.suspension_id,
                    province_code=hit.province_code,
                    hour_bj=hit.hour_bj,
                    train_code=hit.train_code,
                    estimate_basis=hit.estimate_basis,
                    run_key=hit.run_key or result.run_key,
                    stations=hit.stations,
                    available_at=sus.known_at,
                )
            )
            mapped += 1
    db.flush()
    return {"mapped_rows": mapped, "pending_review": pending}


def aggregate_metrics(db: Session, dataset_id: str, event_id: int, version: str) -> dict[str, Any]:
    now = datetime.utcnow()
    ev = db.get(Event, event_id)
    org_covered = {
        a.home_province
        for a in db.query(Account).filter(Account.dataset_id == dataset_id, Account.account_class == "official")
        if a.home_province
    }
    rows = (
        db.query(WeiboClean, WeiboRegion)
        .join(WeiboRegion, WeiboRegion.weibo_clean_id == WeiboClean.id)
        .filter(WeiboClean.dataset_id == dataset_id, WeiboClean.event_id == event_id)
        .all()
    )
    for wc, wr in rows:
        if wc.account_class == "official":
            org_covered.add(wr.province_code)

    def new_bucket() -> dict[str, Any]:
        return {
            "personal": set(),
            "official": set(),
            "unknown": set(),
            "neg": 0,
            "classified": 0,
            "sent_sum": 0.0,
            "sent_n": 0,
            "interaction": 0,
            "help": 0,
            "avail": [],
        }

    buckets: dict[tuple[str, datetime], dict[str, Any]] = defaultdict(new_bucket)
    national: dict[datetime, dict[str, Any]] = defaultdict(new_bucket)
    first_official: dict[str, datetime] = {}

    def add_post(b: dict[str, Any], wc: WeiboClean) -> None:
        b["avail"].append(wc.available_at)
        if wc.account_class == "personal":
            if wc.id in b["personal"]:
                return
            b["personal"].add(wc.id)
            b["interaction"] += wc.interaction
            if wc.is_help_request:
                b["help"] += 1
            if wc.sentiment_label in ("negative", "neutral", "positive"):
                b["classified"] += 1
                if wc.sentiment_label == "negative":
                    b["neg"] += 1
                if wc.sentiment_score is not None:
                    b["sent_sum"] += wc.sentiment_score
                    b["sent_n"] += 1
        elif wc.account_class == "official":
            b["official"].add(wc.id)
        else:
            b["unknown"].add(wc.id)

    for wc, wr in rows:
        add_post(buckets[(wr.province_code, wc.hour_bj)], wc)
        add_post(national[wc.hour_bj], wc)
        if wc.account_class == "official":
            if wr.province_code not in first_official or wc.published_at < first_official[wr.province_code]:
                first_official[wr.province_code] = wc.published_at

    written = 0

    def add_metric(province, hour, metric_id, value, sample_size=None, coverage=None, quality="ok", avail=None):
        nonlocal written
        db.add(
            ProvinceHourMetric(
                dataset_id=dataset_id,
                event_id=event_id,
                province_code=province,
                hour_bj=hour,
                metric_id=metric_id,
                value=value,
                sample_size=sample_size,
                coverage=coverage,
                quality_status=quality,
                version=version,
                available_at=avail,
                computed_at=now,
            )
        )
        written += 1

    def write_social(province: str, hour: datetime, b: dict[str, Any], official_ok: bool) -> None:
        avail = _max_or_none(b["avail"], hour + timedelta(hours=1))
        personal = len(b["personal"])
        add_metric(province, hour, "personal_weibo_count", float(personal), personal, avail=avail)
        ratio = safe_ratio(float(b["neg"]), float(b["classified"]) if b["classified"] else None)
        q = "ok" if b["classified"] > 0 else "insufficient"
        add_metric(
            province,
            hour,
            "negative_ratio",
            ratio,
            sample_size=b["classified"],
            coverage=None if personal == 0 else b["classified"] / personal,
            quality=q,
            avail=avail,
        )
        sent_mean = safe_ratio(b["sent_sum"], float(b["sent_n"]) if b["sent_n"] else None)
        add_metric(province, hour, "sentiment_mean", sent_mean, b["sent_n"], quality=q, avail=avail)
        add_metric(province, hour, "interaction_sum", float(b["interaction"]), personal, avail=avail)
        add_metric(province, hour, "help_request_count", float(b["help"]), personal, avail=avail)
        add_metric(province, hour, "unknown_account_count", float(len(b["unknown"])), len(b["unknown"]), avail=avail)
        if official_ok:
            n_off = len(b["official"])
            add_metric(province, hour, "official_weibo_count", float(n_off), n_off, avail=avail)
            add_metric(province, hour, "official_region_mentions", float(n_off), n_off, avail=avail)

    for (province, hour), b in buckets.items():
        write_social(province, hour, b, province in org_covered)
        first = first_official.get(province)
        if ev and first and first <= hour + timedelta(hours=1):
            hours = (first - ev.start_time).total_seconds() / 3600.0
            add_metric(province, hour, "first_response_hours", hours, 1, avail=_max_or_none(b["avail"], hour + timedelta(hours=1)))
    for hour, b in national.items():
        write_social(NATIONAL, hour, b, bool(org_covered))

    srows = (
        db.query(SuspensionRegionHour)
        .filter(SuspensionRegionHour.dataset_id == dataset_id, SuspensionRegionHour.event_id == event_id)
        .all()
    )

    def new_phys() -> dict[str, Any]:
        return {"runs": set(), "suspensions": set(), "stations": set(), "avail": []}

    phys: dict[tuple[str, datetime], dict[str, Any]] = defaultdict(new_phys)
    phys_nat: dict[datetime, dict[str, Any]] = defaultdict(new_phys)
    for r in srows:
        for b in (phys[(r.province_code, r.hour_bj)], phys_nat[r.hour_bj]):
            b["runs"].add(r.run_key or f"{r.train_code}|{r.suspension_id}")
            b["suspensions"].add(r.suspension_id)
            for st in r.stations or []:
                b["stations"].add(st)
            b["avail"].append(r.available_at)

    def write_phys(province: str, hour: datetime, b: dict[str, Any]) -> None:
        avail = _max_or_none(b["avail"], hour)
        add_metric(province, hour, "affected_trains", float(len(b["runs"])), len(b["runs"]), avail=avail)
        add_metric(province, hour, "suspension_events", float(len(b["suspensions"])), len(b["suspensions"]), avail=avail)
        add_metric(
            province,
            hour,
            "affected_stations",
            float(len(b["stations"])),
            len(b["stations"]),
            quality="ok" if b["stations"] else "insufficient",
            avail=avail,
        )

    for (province, hour), b in phys.items():
        write_phys(province, hour, b)
    for hour, b in phys_nat.items():
        write_phys(NATIONAL, hour, b)
    db.flush()
    return {"metrics_written": written, "org_covered_provinces": sorted(org_covered)}


def _raw_evidence(db: Session, dataset_id: str, event_id: int, cand, limit: int = 3) -> list[dict[str, Any]]:
    """Link candidates to raw posts / suspension notices in the same province-hour."""
    out: list[dict[str, Any]] = []
    hour = cand.hour_bj
    dims = set(cand.dimensions)
    if dims & {"social", "organizational"}:
        q = (
            db.query(WeiboClean, WeiboRaw)
            .join(WeiboRegion, WeiboRegion.weibo_clean_id == WeiboClean.id)
            .join(WeiboRaw, WeiboRaw.id == WeiboClean.weibo_raw_id)
            .filter(
                WeiboClean.dataset_id == dataset_id,
                WeiboClean.event_id == event_id,
                WeiboRegion.province_code == cand.province_code,
                WeiboClean.hour_bj == hour,
            )
        )
        wanted = []
        if "social" in dims:
            wanted.append("personal")
        if "organizational" in dims:
            wanted.append("official")
        for cls in wanted:
            rows = q.filter(WeiboClean.account_class == cls).order_by(WeiboClean.published_at).limit(limit).all()
            for wc, raw in rows:
                if cls == "personal" and cand.anomaly_type == "negative_ratio_spike" and wc.sentiment_label != "negative":
                    continue
                out.append(
                    {
                        "evidence_type": "raw_weibo" if cls == "personal" else "raw_official",
                        "ref_table": "weibo_raw",
                        "ref_id": raw.id,
                        "summary": mask_text(raw.content)[:120],
                        "payload": {"account_class": cls, "source_id": raw.source_id},
                    }
                )
    if "physical" in dims:
        rows = (
            db.query(SuspensionRegionHour, TrainSuspension)
            .join(TrainSuspension, TrainSuspension.id == SuspensionRegionHour.suspension_id)
            .filter(
                SuspensionRegionHour.dataset_id == dataset_id,
                SuspensionRegionHour.event_id == event_id,
                SuspensionRegionHour.province_code == cand.province_code,
                SuspensionRegionHour.hour_bj == hour,
            )
            .limit(limit)
            .all()
        )
        for srh, sus in rows:
            out.append(
                {
                    "evidence_type": "suspension_notice",
                    "ref_table": "train_suspension",
                    "ref_id": sus.id,
                    "summary": mask_text(sus.evidence_text or sus.scope or sus.train_code)[:120],
                    "payload": {"train_code": sus.train_code, "run_key": srh.run_key, "basis": srh.estimate_basis},
                }
            )
    return out


def run_anomaly_detection(db: Session, dataset_id: str, event_id: int, version: str) -> dict[str, Any]:
    rules = load_rules()
    rule_version = rules.get("version", "rules-v1")
    now = datetime.utcnow()
    min_samples = int(rules.get("single", {}).get("min_samples", 6))
    meta = {r.id: r.dimension for r in db.query(MetricRegistry).all()}
    metrics = (
        db.query(ProvinceHourMetric)
        .filter(
            ProvinceHourMetric.dataset_id == dataset_id,
            ProvinceHourMetric.event_id == event_id,
            ProvinceHourMetric.version == version,
            ProvinceHourMetric.province_code != NATIONAL,
        )
        .all()
    )
    dim_points: dict[str, list[MetricPoint]] = {"social": [], "organizational": [], "physical": []}
    for m in metrics:
        dim = meta.get(m.metric_id)
        if dim in dim_points:
            dim_points[dim].append(
                MetricPoint(
                    province_code=m.province_code,
                    hour_bj=m.hour_bj,
                    metric_id=m.metric_id,
                    value=m.value,
                    sample_size=m.sample_size,
                    available_at=m.available_at,
                )
            )
    cands = run_all_detectors(dim_points, rules)
    created = 0
    for c in cands:
        a = Anomaly(
            dataset_id=dataset_id,
            event_id=event_id,
            analysis_scope=c.analysis_scope,
            dimensions=c.dimensions,
            dims_key="," + ",".join(sorted(c.dimensions)) + ",",
            anomaly_type=c.anomaly_type,
            province_code=c.province_code,
            hour_bj=c.hour_bj,
            nature=c.nature,
            score=c.score,
            baseline=c.baseline,
            threshold=c.threshold,
            quality_status=c.quality_status,
            rule_version=rule_version,
            group_key=c.group_key,
            explanation=c.explanation,
            data_version=version,
            available_at=c.available_at,
            decided_at=now,
            requires_future_window=c.requires_future_window,
        )
        db.add(a)
        db.flush()
        for ev in [*c.evidences, *_raw_evidence(db, dataset_id, event_id, c)]:
            db.add(
                AnomalyEvidence(
                    anomaly_id=a.id,
                    evidence_type=ev.get("evidence_type", "metric"),
                    ref_table=ev.get("ref_table"),
                    ref_id=str(ev.get("ref_id")) if ev.get("ref_id") is not None else None,
                    summary=ev.get("summary", ""),
                    payload=ev.get("payload"),
                )
            )
        for s in rules.get("suggestions", []):
            scopes = s.get("trigger_scopes", [])
            dims = set(s.get("dimensions", []))
            if c.analysis_scope in scopes and (not dims or dims.intersection(c.dimensions)):
                if s.get("nature") == "prediction" and c.nature != "prediction":
                    continue
                db.add(
                    Suggestion(
                        dataset_id=dataset_id,
                        event_id=event_id,
                        anomaly_id=a.id,
                        suggestion_code=s["id"],
                        text=s["text"],
                        trigger_reason=c.explanation or c.anomaly_type,
                        review_status="pending",
                        data_version=version,
                    )
                )
        created += 1
    db.flush()
    return {
        "anomalies": created,
        "rule_version": rule_version,
        "tasks": summarize_tasks(dim_points, cands, min_samples),
    }


def get_active_version(db: Session, dataset_id: str, event_id: int) -> str:
    row = db.get(ActiveVersion, (dataset_id, event_id))
    return row.data_version if row else "v1"


def run_event_pipeline(
    db: Session,
    dataset_id: str,
    event_id: int,
    trigger: str = "manual",
    fail_at: str | None = None,
) -> dict[str, Any]:
    """Recompute one event into a new data_version and switch to it only on full success.

    ``fail_at`` names a stage at which to raise; used by tests to prove atomicity.
    """
    rules = load_rules()
    run = AnalysisRun(
        dataset_id=dataset_id,
        event_id=event_id,
        status="running",
        rule_version=rules.get("version", "rules-v1"),
        trigger=trigger,
    )
    db.add(run)
    db.commit()
    run_id = run.id
    version = f"r{run_id}"
    previous = get_active_version(db, dataset_id, event_id)
    report: dict[str, Any] = {"data_version": version, "previous_version": previous}
    try:
        for stage, fn in (
            ("clean", lambda: clean_weibo(db, dataset_id, event_id)),
            ("suspensions", lambda: map_suspensions(db, dataset_id, event_id)),
            ("metrics", lambda: aggregate_metrics(db, dataset_id, event_id, version)),
            ("anomalies", lambda: run_anomaly_detection(db, dataset_id, event_id, version)),
        ):
            if fail_at == stage:
                raise RuntimeError(f"injected failure at {stage}")
            report[stage] = fn()
        pointer = db.get(ActiveVersion, (dataset_id, event_id))
        if pointer is None:
            pointer = ActiveVersion(dataset_id=dataset_id, event_id=event_id, data_version=version, run_id=run_id)
            db.add(pointer)
        else:
            pointer.data_version = version
            pointer.run_id = run_id
            pointer.updated_at = datetime.utcnow()
        run = db.get(AnalysisRun, run_id)
        run.status = "success"
        run.data_version = version
        run.finished_at = datetime.utcnow()
        run.report = report
        db.commit()
        return {"ok": True, "run_id": run_id, "status": "success", **report}
    except Exception as exc:  # noqa: BLE001 - recorded on the run, previous version keeps serving
        db.rollback()
        run = db.get(AnalysisRun, run_id)
        run.status = "failed"
        run.message = str(exc)
        run.finished_at = datetime.utcnow()
        db.commit()
        return {
            "ok": False,
            "run_id": run_id,
            "status": "failed",
            "message": str(exc),
            "active_version": previous,
        }


def run_full_pipeline(db: Session, dataset_id: str, event_id: int | None = None, trigger: str = "manual") -> dict[str, Any]:
    q = db.query(Event).filter(Event.dataset_id == dataset_id)
    if event_id is not None:
        q = q.filter(Event.id == event_id)
    results = [run_event_pipeline(db, dataset_id, ev.id, trigger) for ev in q.order_by(Event.id).all()]
    return {"ok": all(r["ok"] for r in results), "runs": results}
