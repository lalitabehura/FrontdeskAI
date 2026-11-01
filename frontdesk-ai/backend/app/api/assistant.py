"""Business-side configuration of the assistant: identity, hours, services, knowledge, test chat, install."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import rate_limit
from app.db import get_db
from app.deps import OrgContext, get_org_context, require_role
from app.models import AssistantConfig, KnowledgeItem, Service
from app.schemas import AssistantIn, AssistantOut, KnowledgeIn, KnowledgeOut, ServiceIn, ServiceOut, TestChatIn
from app.services import audit, engine
from app.services.tenancy import new_widget_key

router = APIRouter(tags=["assistant"])
MAX_SERVICES, MAX_KNOWLEDGE = 100, 300


def _cfg(db: Session, ctx: OrgContext) -> AssistantConfig:
    return db.get(AssistantConfig, ctx.org_id)


@router.get("/assistant", response_model=AssistantOut)
def get_assistant(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    return _cfg(db, ctx)


@router.put("/assistant", response_model=AssistantOut)
def put_assistant(body: AssistantIn, request: Request, ctx: OrgContext = Depends(require_role("admin")),
                  db: Session = Depends(get_db)):
    cfg = _cfg(db, ctx)
    for k, v in body.model_dump().items():
        setattr(cfg, k, v)
    audit.record(db, "assistant.updated", ctx.user.id, request, org_id=ctx.org_id)
    db.commit()
    return cfg


@router.post("/assistant/rotate-key", response_model=AssistantOut)
def rotate_key(request: Request, ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    cfg = _cfg(db, ctx)
    cfg.widget_key = new_widget_key()
    audit.record(db, "assistant.key_rotated", ctx.user.id, request, org_id=ctx.org_id)
    db.commit()
    return cfg


@router.get("/assistant/install")
def install(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    cfg = _cfg(db, ctx)
    base = get_settings().frontend_url
    return {
        "snippet": f'<script src="{base}/widget.js" data-key="{cfg.widget_key}" async></script>',
        "preview_url": f"{base}/widget/{cfg.widget_key}",
        "allowed_domains": cfg.allowed_domains,
    }


@router.post("/assistant/test", dependencies=[Depends(rate_limit("assistant_test", 30, 60))])
def test_chat(body: TestChatIn, ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    """Try the assistant with the current settings. Nothing is saved; doesn't count toward usage."""
    history = [(h.get("role", "visitor") if h.get("role") in ("visitor", "assistant") else "visitor",
                str(h.get("content", ""))[:2000]) for h in body.history]
    out = engine.respond(engine.load_context(db, ctx.org, _cfg(db, ctx)), history, body.message)
    return {"reply": out.reply, "action": out.action, "needs_human": out.needs_human, "used_ai": out.used_ai}


# --------------------------------------------------------------------------- services
def _service(db: Session, ctx: OrgContext, service_id: str) -> Service:
    s = db.get(Service, service_id)
    if s is None or s.org_id != ctx.org_id:
        raise HTTPException(status_code=404, detail="Service not found")
    return s


@router.get("/services", response_model=list[ServiceOut])
def list_services(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    return db.scalars(select(Service).where(Service.org_id == ctx.org_id).order_by(Service.sort_order, Service.name)).all()


@router.post("/services", response_model=ServiceOut, status_code=201)
def create_service(body: ServiceIn, ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    if db.scalar(select(func.count()).select_from(Service).where(Service.org_id == ctx.org_id)) >= MAX_SERVICES:
        raise HTTPException(status_code=400, detail=f"At most {MAX_SERVICES} services.")
    s = Service(org_id=ctx.org_id, **body.model_dump())
    db.add(s)
    db.commit()
    return s


@router.put("/services/{service_id}", response_model=ServiceOut)
def update_service(service_id: str, body: ServiceIn, ctx: OrgContext = Depends(require_role("admin")),
                   db: Session = Depends(get_db)):
    s = _service(db, ctx, service_id)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    db.commit()
    return s


@router.delete("/services/{service_id}", status_code=204)
def delete_service(service_id: str, ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    s = _service(db, ctx, service_id)
    s.active = False  # soft delete keeps past appointments intact
    s.bookable = False
    db.commit()


# --------------------------------------------------------------------------- knowledge base
def _knowledge(db: Session, ctx: OrgContext, item_id: str) -> KnowledgeItem:
    k = db.get(KnowledgeItem, item_id)
    if k is None or k.org_id != ctx.org_id:
        raise HTTPException(status_code=404, detail="Item not found")
    return k


@router.get("/knowledge", response_model=list[KnowledgeOut])
def list_knowledge(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)):
    return db.scalars(select(KnowledgeItem).where(KnowledgeItem.org_id == ctx.org_id)
                      .order_by(KnowledgeItem.created_at)).all()


@router.post("/knowledge", response_model=KnowledgeOut, status_code=201)
def create_knowledge(body: KnowledgeIn, ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    if db.scalar(select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.org_id == ctx.org_id)) >= MAX_KNOWLEDGE:
        raise HTTPException(status_code=400, detail=f"At most {MAX_KNOWLEDGE} knowledge items.")
    k = KnowledgeItem(org_id=ctx.org_id, **body.model_dump())
    db.add(k)
    db.commit()
    return k


@router.put("/knowledge/{item_id}", response_model=KnowledgeOut)
def update_knowledge(item_id: str, body: KnowledgeIn, ctx: OrgContext = Depends(require_role("admin")),
                     db: Session = Depends(get_db)):
    k = _knowledge(db, ctx, item_id)
    k.question, k.answer = body.question, body.answer
    db.commit()
    return k


@router.delete("/knowledge/{item_id}", status_code=204)
def delete_knowledge(item_id: str, ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db)):
    db.delete(_knowledge(db, ctx, item_id))
    db.commit()
