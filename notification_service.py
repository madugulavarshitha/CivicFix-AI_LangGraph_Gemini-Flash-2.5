from sqlalchemy.orm import Session
from app.models.entities import Notification
from typing import Optional

def create_notification(
    db: Session,
    user_id: int,
    title: str,
    message: str,
    notification_type: str,
    complaint_id: Optional[int] = None
) -> Notification:
    notif = Notification(
        user_id=user_id,
        complaint_id=complaint_id,
        title=title,
        message=message,
        notification_type=notification_type,
        is_read=False
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif
