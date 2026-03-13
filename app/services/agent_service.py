from sqlalchemy.orm import Session
from app.db.models import Message, ConversationSummary
from app.services.llm_service import call_llm
from sqlalchemy import desc

SYSTEM_PROMPT = """
Você é um Professor de Inglês virtual que atua exclusivamente via Web Interface.

Seu objetivo é ajudar o usuário a aprender e praticar inglês de forma leve,
prática e progressiva, adaptando-se automaticamente ao nível do aluno.

REGRAS GERAIS:
- Seja amigável, paciente e encorajador
- Use mensagens curtas e claras
- Não use textos longos
- Utilize emojis com moderação 🇺🇸
- Nunca constranja o aluno por erros

COMPORTAMENTO:
- Se o usuário escrever em português, responda em português
- Se escrever em inglês, responda principalmente em inglês
- Corrija erros de forma educativa e gentil
- Sempre explique a correção em português

CORREÇÕES:
- Mostre o erro apenas quando existir
- Formato da correção:
  ❌ Frase incorreta
  ✅ Frase correta
  📌 Explicação curta em português

DIDÁTICA:
- Ajuste o vocabulário ao nível do aluno
- Se o aluno errar muito, simplifique
- Se for muito fácil, aumente levemente a dificuldade
- Proponha pequenas perguntas para continuar a conversa
"""

MAX_TURNS = 10

async def run_agent(db: Session, session_id: str, user_message: str) -> str:
    # 1. Get recent history
    recent_messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(desc(Message.created_at))
        .limit(MAX_TURNS)
        .all()
    )
    
    recent_history = [
        {"role": m.role, "content": m.content} 
        for m in reversed(recent_messages)
    ]

    # 2. Get summary
    summary_record = (
        db.query(ConversationSummary)
        .filter(ConversationSummary.session_id == session_id)
        .first()
    )
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    if summary_record and summary_record.summary:
        messages.append({
            "role": "system",
            "content": f"Conversation summary:\n{summary_record.summary}"
        })

    messages.extend(recent_history)
    messages.append({"role": "user", "content": user_message})

    # 3. Call LLM
    response_text = call_llm(messages)

    # 4. Save messages
    user_msg = Message(session_id=session_id, role="user", content=user_message)
    assistant_msg = Message(session_id=session_id, role="assistant", content=response_text)
    db.add(user_msg)
    db.add(assistant_msg)
    db.commit()

    # 5. Occasional summary update
    # Simple strategy: update if we have more than 10 messages and no summary, or every 10 new messages
    msg_count = db.query(Message).filter(Message.session_id == session_id).count()
    if msg_count % 10 == 0:
        await update_long_memory_summary(db, session_id)

    return response_text

async def update_long_memory_summary(db: Session, session_id: str):
    """
    Summarize the last 12 messages and update the ConversationSummary.
    """
    recent_messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(desc(Message.created_at))
        .limit(12)
        .all()
    )

    if not recent_messages:
        return

    text = "\n".join(
        f"{m.role}: {m.content}" for m in reversed(recent_messages)
    )

    prompt = [
        {
            "role": "system",
            "content": (
                "Summarize the following conversation in a very short way. "
                "Focus on the user's English level, mistakes, preferences "
                "and what is being practiced."
            ),
        },
        {"role": "user", "content": text},
    ]

    summary_text = call_llm(prompt)

    summary_record = (
        db.query(ConversationSummary)
        .filter(ConversationSummary.session_id == session_id)
        .first()
    )

    if summary_record:
        summary_record.summary = summary_text
    else:
        summary_record = ConversationSummary(session_id=session_id, summary=summary_text)
        db.add(summary_record)
    
    db.commit()
