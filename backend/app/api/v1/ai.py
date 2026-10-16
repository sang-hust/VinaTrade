import json
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, select

from app.api.deps import DB, CurrentUser
from app.api.presenters import clean, row
from app.core.config import settings
from app.core.errors import ApiError, not_found
from app.models import AiConversation, AiMessage, CoachReport
from app.schemas.common import Ok
from app.services import ai

router = APIRouter(tags=["ai"])


class ConvIn(BaseModel):
    title: str | None = None
    context: dict | None = None


class MsgIn(BaseModel):
    content: str
    context: dict | None = None


@router.get("/ai/conversations")
async def list_conversations(user: CurrentUser, db: DB, limit: int = 30):
    rows = (await db.execute(select(AiConversation).where(AiConversation.user_id == user.id).order_by(desc(AiConversation.updated_at)).limit(limit))).scalars().all()
    return [{"id": str(c.id), "title": c.title, "context": c.context, "updated_at": clean(c.updated_at)} for c in rows]


@router.post("/ai/conversations")
async def create_conversation(body: ConvIn, user: CurrentUser, db: DB):
    c = AiConversation(user_id=user.id, title=body.title, context=body.context)
    db.add(c)
    await db.commit()
    return {"id": str(c.id), "title": c.title, "context": c.context, "suggestions": _suggestions(body.context)}


def _suggestions(ctx: dict | None) -> list[str]:
    sym = (ctx or {}).get("symbol")
    screen = (ctx or {}).get("screen")
    if sym:
        return [f"Phân tích {sym} cho trung hạn", f"Vì sao {sym} có khuyến nghị này?", f"Rủi ro của {sym} là gì?", f"So sánh {sym} với mã cùng ngành"]
    if screen == "portfolio":
        return ["Danh mục của tôi đang rủi ro chỗ nào?", "Mã nào trong danh mục nên chốt lời?", "Tỷ trọng ngành của tôi có quá tập trung không?"]
    if screen == "screener":
        return ["Lọc mã ngân hàng đang về hỗ trợ", "Mã nào vừa phá nền với khối lượng lớn?", "Cổ phiếu P/E dưới 10, ROE trên 15%"]
    return ["Hôm nay thị trường ra sao?", "Những mã ngân hàng nào đang về hỗ trợ?", "Ngành nào đang hút dòng tiền?", "Tín hiệu mua nổi bật hôm nay"]


@router.get("/ai/conversations/{cid}")
async def get_conversation(cid: uuid.UUID, user: CurrentUser, db: DB):
    c = await db.get(AiConversation, cid)
    if not c or c.user_id != user.id:
        raise not_found()
    msgs = (await db.execute(select(AiMessage).where(AiMessage.conversation_id == c.id).order_by(AiMessage.id))).scalars().all()
    return {"id": str(c.id), "title": c.title, "context": c.context, "messages": [row(m, ["id", "role", "content", "data_cards", "created_at"]) for m in msgs], "suggestions": _suggestions(c.context)}


@router.delete("/ai/conversations/{cid}", response_model=Ok)
async def delete_conversation(cid: uuid.UUID, user: CurrentUser, db: DB):
    c = await db.get(AiConversation, cid)
    if not c or c.user_id != user.id:
        raise not_found()
    await db.delete(c)
    await db.commit()
    return Ok()


@router.post("/ai/conversations/{cid}/messages")
async def send_message(cid: uuid.UUID, body: MsgIn, user: CurrentUser, db: DB):
    """Server-sent events: data: {"type":"text","delta":...} | {"type":"card",...} | {"type":"done",...}"""
    c = await db.get(AiConversation, cid)
    if not c or c.user_id != user.id:
        raise not_found()
    used = await ai.daily_usage(db, user)
    if used >= settings.ai_daily_limit:
        raise ApiError(429, "AI_LIMIT", f"Bạn đã dùng hết {settings.ai_daily_limit} câu hỏi hôm nay. Hạn mức làm mới lúc 0:00.")
    prev = (await db.execute(select(AiMessage).where(AiMessage.conversation_id == c.id).order_by(AiMessage.id))).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in prev[-12:]] + [{"role": "user", "content": body.content.strip()[:2000]}]
    um = AiMessage(conversation_id=c.id, role="user", content=body.content.strip()[:2000])
    db.add(um)
    if not c.title:
        c.title = body.content.strip()[:80]
    if body.context:
        c.context = body.context
    await db.commit()
    ctx = body.context or c.context

    async def gen():
        final = None
        try:
            async for ev in ai.chat_stream(db, user, history, ctx):
                if ev["type"] == "done":
                    final = ev
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)[:200]}, ensure_ascii=False)}\n\n"
        if final:
            db.add(AiMessage(conversation_id=c.id, role="assistant", content=final.get("text") or "", tool_calls=final.get("tool_calls"), data_cards=final.get("cards"),
                             input_tokens=(final.get("usage") or {}).get("input"), output_tokens=(final.get("usage") or {}).get("output")))
            await db.commit()

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/coach/reports")
async def coach_reports(user: CurrentUser, db: DB, limit: int = 12):
    rows = (await db.execute(select(CoachReport).where(CoachReport.user_id == user.id).order_by(desc(CoachReport.week_start)).limit(limit))).scalars().all()
    return [{"id": str(r.id), **row(r, ["week_start", "metrics", "insights", "rule", "summary", "benchmark", "created_at"])} for r in rows]


@router.get("/coach/reports/{week}")
async def coach_report(week: str, user: CurrentUser, db: DB):
    from datetime import date

    if week == "latest":
        r = (await db.execute(select(CoachReport).where(CoachReport.user_id == user.id).order_by(desc(CoachReport.week_start)).limit(1))).scalar_one_or_none()
    else:
        r = (await db.execute(select(CoachReport).where(CoachReport.user_id == user.id, CoachReport.week_start == date.fromisoformat(week)))).scalar_one_or_none()
    if not r:
        raise not_found("Chưa có báo cáo")
    return {"id": str(r.id), **row(r, ["week_start", "metrics", "insights", "rule", "summary", "benchmark", "created_at"])}


@router.post("/coach/reports/generate")
async def generate_now(user: CurrentUser, db: DB):
    from app.services.coach import build_report

    r = await build_report(db, user)
    await db.commit()
    return {"id": str(r.id), **row(r, ["week_start", "metrics", "insights", "rule", "summary", "benchmark", "created_at"])}
