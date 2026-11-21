"""态度和异常查询。汇总规则放在 app.attitude，路由只做参数校验。"""

from fastapi import APIRouter, Depends

from app.api.context import fail, query_context
from app.attitude import anomalies_payload, results_payload

router = APIRouter(prefix="/api/v1")


@router.get("/anomalies")
def anomalies(page: int = 1, page_size: int = 20, q=Depends(query_context)):
    if page < 1 or not 1 <= page_size <= 100:
        fail("invalid_pagination", "页码至少为 1，每页 1 至 100 条")
    return anomalies_payload(q[1], page, page_size)


@router.get("/analysis/results")
def analysis_results(q=Depends(query_context)):
    return results_payload(q[1])
