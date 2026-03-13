from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from app.db.database import get_db
from app.db.models import Message, ConversationSummary
from app.services.agent_service import run_agent
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()

class ChatRequest(BaseModel):
    session_id: str
    message: str

class ChatResponse(BaseModel):
    response: str

class MessageSchema(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True

class SessionSchema(BaseModel):
    session_id: str
    title: str
    updated_at: datetime

@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    try:
        response_text = await run_agent(db, request.session_id, request.message)
        return ChatResponse(response=response_text)
    except Exception as e:
        print(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/sessions", response_model=List[SessionSchema])
async def list_sessions(db: Session = Depends(get_db)):
    # Get unique session_ids and their latest message/update time
    sessions = (
        db.query(
            Message.session_id,
            func.max(Message.created_at).label("updated_at")
        )
        .group_by(Message.session_id)
        .order_by(func.max(Message.created_at).desc())
        .all()
    )
    
    result = []
    for session_id, updated_at in sessions:
        # Get the first user message as the title
        first_msg = (
            db.query(Message)
            .filter(Message.session_id == session_id, Message.role == "user")
            .order_by(Message.created_at.asc())
            .first()
        )
        
        title = "New Chat"
        if first_msg:
            words = first_msg.content.split(' ')[:5]
            title = ' '.join(words)
            if len(title) > 30:
                title = title[:30] + "..."
        
        result.append(SessionSchema(
            session_id=session_id,
            title=title,
            updated_at=updated_at
        ))
    
    return result

@router.get("/history/{session_id}", response_model=List[MessageSchema])
async def get_history(session_id: str, db: Session = Depends(get_db)):
    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return messages

@router.delete("/session/{session_id}")
async def delete_session(session_id: str, db: Session = Depends(get_db)):
    try:
        db.query(Message).filter(Message.session_id == session_id).delete()
        db.query(ConversationSummary).filter(ConversationSummary.session_id == session_id).delete()
        db.commit()
        return {"message": "Session deleted"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
