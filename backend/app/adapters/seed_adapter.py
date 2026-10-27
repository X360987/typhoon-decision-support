"""Deterministic demo seed. Clear SIM- prefixes; never pretends to be real Weibo."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any, Iterator

from app.adapters.base import DataSourceAdapter, ForecastProvider
from app.domain.geo import PROVINCE_ALIASES

PROVINCES = ["FJ", "GD", "ZJ", "JS", "SH", "TW"]
PROVINCE_NAMES = {v: k for k, v in PROVINCE_ALIASES.items() if len(k) == 2 or k.endswith("省") or k.endswith("市")}
# Prefer short Chinese names
PROVINCE_CN = {"FJ": "福建", "GD": "广东", "ZJ": "浙江", "JS": "江苏", "SH": "上海", "TW": "台湾"}


def _rng(seed: int, *parts: Any) -> float:
    h = hashlib.md5(f"{seed}|{'|'.join(map(str, parts))}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


class SeedAdapter(DataSourceAdapter):
    name = "seed"

    def __init__(
        self,
        seed: int = 42,
        hours: int = 72,
        provinces: list[str] | None = None,
    ):
        self.seed = seed
        self.hours = hours
        self.provinces = provinces or PROVINCES
        self.start = datetime(2023, 7, 26, 0, 0, 0)  # Doksuri-like demo window
        self.events = [
            {
                "event_code": "SIM-DOKSURI-2023",
                "name": "模拟台风杜苏芮案例",
                "external_typhoon_id": "SIM-202305",
                "start_time": self.start,
                "end_time": self.start + timedelta(hours=hours - 1),
                "status": "historical",
            },
            {
                "event_code": "SIM-NEW-EVENT-A",
                "name": "模拟新台风事件A",
                "external_typhoon_id": "SIM-209901",
                "start_time": self.start + timedelta(days=40),
                "end_time": self.start + timedelta(days=40, hours=hours - 1),
                "status": "tracking",
            },
        ]

    def iter_records(self, entity: str) -> Iterator[dict[str, Any]]:
        if entity == "events":
            yield from self.events
        elif entity == "accounts":
            yield from self._accounts()
        elif entity == "timetable":
            yield from self._timetable()
        elif entity == "weibo":
            yield from self._weibo()
        elif entity == "suspensions":
            yield from self._suspensions()
        elif entity == "hazards":
            yield from self._hazards()
        elif entity == "forecasts":
            yield from self._forecasts()
        else:
            return

    def _accounts(self) -> Iterator[dict[str, Any]]:
        for i, p in enumerate(self.provinces):
            yield {
                "user_id": f"SIM-OFF-{p}",
                "nickname": f"模拟{PROVINCE_CN[p]}政务发布",
                "account_class": "official",
                "verified": True,
                "verify_type": "机构认证",
                "checklist_source": "demo_official_checklist",
                "home_province": p,
            }
            yield {
                "user_id": f"SIM-PER-{p}-{i}",
                "nickname": f"模拟用户{p}{i}",
                "account_class": "personal",
                "verified": False,
                "verify_type": None,
                "checklist_source": "demo_personal_default",
                "home_province": p,
            }

    def _timetable(self) -> Iterator[dict[str, Any]]:
        trains = [
            ("SIM-G7001", [("福州", "FJ", "08:00"), ("厦门", "FJ", "10:00"), ("汕头", "GD", "12:30")]),
            ("SIM-G7002", [("广州", "GD", "09:00"), ("深圳", "GD", "10:10"), ("厦门", "FJ", "13:00")]),
            ("SIM-D3101", [("杭州", "ZJ", "07:30"), ("上海", "SH", "09:00"), ("南京", "JS", "11:20")]),
            ("SIM-G8001", [("台北", "TW", "08:40"), ("高雄", "TW", "11:00")]),
            ("SIM-K5201", [("南京", "JS", "22:10"), ("上海", "SH", "01:20"), ("杭州", "ZJ", "03:40")]),  # cross midnight
        ]
        for train_code, stops in trains:
            for order, (station, prov, t) in enumerate(stops, start=1):
                yield {
                    "record_no": f"SIM-TT-{train_code}-{order}",
                    "train_code": train_code,
                    "timetable_version": "SIM-TT-v1",
                    "stop_order": order,
                    "station_name": station,
                    "city": station,
                    "province_code": prov,
                    "arrive_time": t,
                    "depart_time": t,
                    "passenger_service": True,
                    "passenger_flag_note": "模拟客运办理",
                }

    def _scene_hour(self, event_idx: int, hour_offset: int, province: str) -> str:
        """Named scenes for tests — stored only in test checklist, not fed to detector."""
        # Event 0 scenarios
        if event_idx == 0:
            if 20 <= hour_offset <= 26 and province == "FJ":
                return "social_only_negative"
            if 30 <= hour_offset <= 34 and province == "GD":
                return "org_only_gap"
            if 40 <= hour_offset <= 46 and province == "ZJ":
                return "physical_only_suspension"
            if 50 <= hour_offset <= 54 and province == "JS":
                return "pair_social_org"
            if 55 <= hour_offset <= 58 and province == "SH":
                return "pair_org_physical"
            if 60 <= hour_offset <= 64 and province == "FJ":
                return "joint_triple"
            if 10 <= hour_offset <= 14 and province == "TW":
                return "pre_disaster_forecast_talk"
            if hour_offset == 18 and province == "GD":
                return "low_sample"
        return "normal"

    def _weibo(self) -> Iterator[dict[str, Any]]:
        wid = 0
        for ei, ev in enumerate(self.events):
            start: datetime = ev["start_time"]
            for h in range(self.hours):
                hour = start + timedelta(hours=h)
                for p in self.provinces:
                    scene = self._scene_hour(ei, h, p)
                    # personal posts
                    n_personal = 2 + int(_rng(self.seed, ei, h, p, "n") * 3)
                    if scene == "social_only_negative":
                        n_personal = 12
                    if scene == "pair_social_org":
                        n_personal = 15
                    if scene == "joint_triple":
                        n_personal = 10
                    if scene == "low_sample":
                        n_personal = 1
                    if scene == "pre_disaster_forecast_talk":
                        n_personal = 6

                    for k in range(n_personal):
                        wid += 1
                        published = hour + timedelta(minutes=int(_rng(self.seed, wid) * 50))
                        neg = scene in (
                            "social_only_negative",
                            "pair_social_org",
                            "joint_triple",
                        ) or (scene == "pre_disaster_forecast_talk" and k % 2 == 0)
                        if scene == "normal":
                            neg = _rng(self.seed, ei, h, p, k, "neg") > 0.85
                        content = (
                            f"【模拟】{PROVINCE_CN[p]}担心台风停运，求助最新通知"
                            if neg
                            else f"【模拟】{PROVINCE_CN[p]}关注天气预报，希望顺利"
                        )
                        if scene == "pre_disaster_forecast_talk":
                            content = f"【模拟】灾前预报性讨论：{PROVINCE_CN[p]}留意路径，尚未受明显影响"
                        yield {
                            "source_id": f"SIM-WB-{wid}",
                            "bid": f"SIM-BID-{wid}",
                            "user_id": f"SIM-PER-{p}-{self.provinces.index(p)}",
                            "nickname": f"模拟用户{p}",
                            "content": content,
                            "publish_location": PROVINCE_CN[p],
                            "topics": "#模拟台风#",
                            "reposts": int(_rng(self.seed, wid, "r") * 5),
                            "comments": int(_rng(self.seed, wid, "c") * 8),
                            "likes": int(_rng(self.seed, wid, "l") * 20),
                            "published_at": published,
                            "ip": f"{self.provinces.index(p)+1}.{self.provinces.index(p)+1}.{self.provinces.index(p)+1}.{k+1}",
                            "verify_type": None,
                            "heat": None,
                            "stage": None,  # post-hoc stage not used as feature
                            "event_code": ev["event_code"],
                            "available_at": published + timedelta(minutes=2 + int(_rng(self.seed, wid, "arr") * 18)),
                            "_scene": scene,  # stripped before DB; tests may use separate checklist
                        }

                    # official posts
                    n_off = 1 if _rng(self.seed, ei, h, p, "off") > 0.4 else 0
                    if scene == "org_only_gap":
                        n_off = 0
                    if scene == "pair_social_org":
                        n_off = 0
                    if scene == "pair_org_physical":
                        n_off = 0 if h < 57 else 2
                    if scene == "joint_triple":
                        n_off = 4
                    if scene == "social_only_negative":
                        n_off = 2  # org normal while social spikes
                    if scene == "physical_only_suspension":
                        n_off = 1
                    for k in range(n_off):
                        wid += 1
                        yield {
                            "source_id": f"SIM-WB-{wid}",
                            "bid": f"SIM-BID-{wid}",
                            "user_id": f"SIM-OFF-{p}",
                            "nickname": f"模拟{PROVINCE_CN[p]}政务发布",
                            "content": f"【模拟公告】{PROVINCE_CN[p]}出行提示与情况说明（非真实公告）",
                            "publish_location": PROVINCE_CN[p],
                            "topics": "#模拟预警#",
                            "reposts": 3,
                            "comments": 2,
                            "likes": 10,
                            "published_at": hour + timedelta(minutes=5 * (k + 1)),
                            "ip": f"{self.provinces.index(p)+1}.0.0.1",
                            "verify_type": "机构认证",
                            "heat": 1.0,
                            "stage": None,
                            "event_code": ev["event_code"],
                            "available_at": hour + timedelta(minutes=5 * (k + 1) + 3),
                            "_scene": scene,
                        }

            # boundary samples only once on event 0
            if ei == 0:
                wid += 1
                yield {
                    "source_id": f"SIM-WB-{wid}",
                    "bid": f"SIM-BID-{wid}",
                    "user_id": "SIM-PER-FJ-0",
                    "nickname": "模拟边界样本",
                    "content": "【模拟】跨省提及福建和广东的讨论",
                    "publish_location": None,
                    "topics": "",
                    "reposts": 0,
                    "comments": 0,
                    "likes": 0,
                    "published_at": start + timedelta(hours=5, minutes=10),
                    "ip": None,
                    "verify_type": None,
                    "event_code": ev["event_code"],
                    "available_at": start + timedelta(hours=5, minutes=15),
                }
                wid += 1
                yield {
                    "source_id": f"SIM-WB-{wid}",
                    "bid": f"SIM-BID-{wid}",
                    "user_id": "SIM-PER-UNKNOWN",
                    "nickname": "模拟未知地区",
                    "content": "【模拟】没有明确地名的讨论",
                    "publish_location": None,
                    "topics": "",
                    "reposts": None,
                    "comments": None,
                    "likes": None,
                    "published_at": start + timedelta(hours=6),
                    "ip": "9.9.9.9",
                    "verify_type": None,
                    "event_code": ev["event_code"],
                    "available_at": start + timedelta(hours=6, minutes=4),
                }
                # duplicate id for import isolation testing is handled in CSV templates, not seed

    def _suspensions(self) -> Iterator[dict[str, Any]]:
        sid = 0
        for ei, ev in enumerate(self.events):
            start: datetime = ev["start_time"]
            for h in range(self.hours):
                hour = start + timedelta(hours=h)
                for p in self.provinces:
                    scene = self._scene_hour(ei, h, p)
                    n = 0
                    if scene == "physical_only_suspension":
                        n = 10
                    elif scene == "pair_org_physical":
                        n = 8
                    elif scene == "joint_triple":
                        n = 9
                    elif scene == "social_only_negative":
                        n = 1  # physical near-normal
                    elif scene == "org_only_gap":
                        n = 1
                    elif _rng(self.seed, ei, h, p, "sus") > 0.92:
                        n = 1
                    trains = ["SIM-G7001", "SIM-G7002", "SIM-D3101", "SIM-G8001", "SIM-K5201"]
                    for i in range(n):
                        sid += 1
                        train = trains[i % len(trains)]
                        yield {
                            "record_no": f"SIM-SUS-{sid}",
                            "suspension_date": hour,
                            "train_code": train,
                            "train_db_id": f"SIM-DB-{train}",
                            "train_type": "G",
                            "scope": "区段停运",
                            "segment_start": None,
                            "segment_end": None,
                            "scope_basis": "模拟公告文本",
                            "notice_source_type": "模拟官方微博",
                            "notice_account": f"SIM-OFF-{p}",
                            "confidence": 0.8,
                            "evidence_text": f"【模拟停运证据】{train} 于 {hour.isoformat()} 影响 {PROVINCE_CN[p]}",
                            "match_method": "train_code",
                            "merged_source_count": 1,
                            "known_at": hour - timedelta(hours=1),
                            "event_code": ev["event_code"],
                            "force_province": p,
                        }
            if ei == 0:
                # Segment-level notices: one matched cross-midnight segment, one with an unmatched endpoint.
                day = start + timedelta(days=1)
                for segment_start, segment_end in (("上海", "杭州"), ("苏州", "杭州")):
                    sid += 1
                    yield {
                        "record_no": f"SIM-SUS-{sid}",
                        "suspension_date": day,
                        "train_code": "SIM-K5201",
                        "train_db_id": "SIM-DB-SIM-K5201",
                        "train_type": "K",
                        "scope": f"{segment_start}至{segment_end}区段停运",
                        "segment_start": segment_start,
                        "segment_end": segment_end,
                        "scope_basis": "模拟公告文本",
                        "notice_source_type": "模拟官方微博",
                        "notice_account": "SIM-OFF-SH",
                        "confidence": 0.7,
                        "evidence_text": f"【模拟停运证据】SIM-K5201 {segment_start}—{segment_end} 区段停运",
                        "match_method": "train_code+segment",
                        "merged_source_count": 1,
                        "known_at": day - timedelta(hours=3),
                        "event_code": ev["event_code"],
                        "force_province": None,
                    }

    def _hazards(self) -> Iterator[dict[str, Any]]:
        for ei, ev in enumerate(self.events):
            start: datetime = ev["start_time"]
            for h in range(0, self.hours, 6):
                hour = start + timedelta(hours=h)
                for p in self.provinces:
                    wind = 15 + 20 * _rng(self.seed, ei, h, p, "wind")
                    if 20 <= h <= 40:
                        wind += 10
                    yield {
                        "observed_at": hour,
                        "arrived_at": hour + timedelta(minutes=10),
                        "province_code": p,
                        "metric": "max_wind",
                        "value": wind,
                        "unit": "m/s",
                        "source": "SIM-HAZARD",
                        "original_granularity": "6h",
                        "quality_flags": {"proxy": False},
                        "event_code": ev["event_code"],
                    }
                    # daily rainfall proxy evenly split — must be flagged
                    yield {
                        "observed_at": hour,
                        "arrived_at": hour + timedelta(minutes=10),
                        "province_code": p,
                        "metric": "rainfall_hourly_proxy",
                        "value": (50 * _rng(self.seed, ei, h, p, "rain")) / 6.0,
                        "unit": "mm",
                        "source": "SIM-HAZARD",
                        "original_granularity": "daily_split_proxy",
                        "quality_flags": {"daily_split_proxy": True},
                        "event_code": ev["event_code"],
                    }

    def _forecasts(self) -> Iterator[dict[str, Any]]:
        for ei, ev in enumerate(self.events):
            start: datetime = ev["start_time"]
            for h in range(0, self.hours, 6):
                issued = start + timedelta(hours=h)
                arrived = issued + timedelta(minutes=5)
                points = []
                for lead in (6, 12, 24):
                    points.append(
                        {
                            "valid_time": issued + timedelta(hours=lead),
                            "lead_hours": lead,
                            "lat": 25.0 + ei,
                            "lon": 119.0,
                            "metric": "max_wind",
                            "value": 25 + lead * 0.2,
                            "unit": "m/s",
                            "province_code": None,
                            "path_distance_proxy": 80 + lead,
                        }
                    )
                yield {
                    "event_code": ev["event_code"],
                    "source": "SIM-FORECAST",
                    "issued_at": issued,
                    "arrived_at": arrived,
                    "revision": 1 if h < 30 else 2,
                    "points": points,
                    "raw_payload": {"note": "模拟预报快照"},
                }


class SeedForecastProvider(ForecastProvider):
    name = "seed_forecast"

    def __init__(self, seed: int = 42):
        self.adapter = SeedAdapter(seed=seed)

    def fetch_snapshots(self, event_code: str) -> list[dict[str, Any]]:
        return [r for r in self.adapter.iter_records("forecasts") if r["event_code"] == event_code]
