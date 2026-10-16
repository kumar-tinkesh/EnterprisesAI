from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Tuple
import os.path
import requests
import json
import audio

# Vendor addition (not upstream): env-configurable. Upstream assumed this
# Python process always runs as a child of the Go bridge's own working
# directory and talks to it on localhost — true only when both run in the
# same container. Our per-account bridge runs in its own isolated container
# (see apps/whatsapp_orchestrator/), reachable over the whatsapp docker
# network by name, not localhost — hence WHATSAPP_API_BASE_URL being
# set per user (see vendor.services.whatsapp_bridge.manager.get_mcp_env). Every read below (list_messages, search_contacts,
# ...) that upstream ran as a local SQLite query against messages.db is
# instead a call to one of the bridge's own read endpoints (see
# vendor_src/bridge/main.go's "Vendor addition" REST handlers) — this
# process has no local access to that per-instance file, and never will
# under this architecture, so there's no MESSAGES_DB_PATH here anymore.
WHATSAPP_API_BASE_URL = os.environ.get("WHATSAPP_API_BASE_URL", "http://localhost:8080/api")
# EnterpriseAI addition: the per-instance token the bridge requires on every
# request (unset = none, for standalone upstream use).
_BRIDGE_HEADERS = {"X-Bridge-Token": os.environ["WHATSAPP_BRIDGE_TOKEN"]} if os.environ.get("WHATSAPP_BRIDGE_TOKEN") else {}


def _bridge_post(path: str, payload: dict) -> dict:
    """POSTs to one of the bridge's read endpoints and returns the decoded
    JSON body. Raises requests.RequestException / ValueError on transport or
    non-2xx failure — every caller below already sits inside a try/except
    that logs and degrades (empty list / None), matching upstream's own
    sqlite3.Error handling shape."""
    response = requests.post(f"{WHATSAPP_API_BASE_URL}{path}", json=payload, headers=_BRIDGE_HEADERS, timeout=15)
    response.raise_for_status()
    return response.json()

@dataclass
class Message:
    timestamp: datetime
    sender: str
    content: str
    is_from_me: bool
    chat_jid: str
    id: str
    chat_name: Optional[str] = None
    media_type: Optional[str] = None

@dataclass
class Chat:
    jid: str
    name: Optional[str]
    last_message_time: Optional[datetime]
    last_message: Optional[str] = None
    last_sender: Optional[str] = None
    last_is_from_me: Optional[bool] = None

    @property
    def is_group(self) -> bool:
        """Determine if chat is a group based on JID pattern."""
        return self.jid.endswith("@g.us")

@dataclass
class Contact:
    phone_number: str
    name: Optional[str]
    jid: str

@dataclass
class MessageContext:
    message: Message
    before: List[Message]
    after: List[Message]


def _to_message(msg: dict) -> Message:
    return Message(
        timestamp=datetime.fromisoformat(msg["timestamp"]),
        sender=msg["sender"],
        chat_name=msg["chat_name"],
        content=msg["content"],
        is_from_me=msg["is_from_me"],
        chat_jid=msg["chat_jid"],
        id=msg["id"],
        media_type=msg["media_type"],
    )


def _to_chat(chat: dict) -> Chat:
    return Chat(
        jid=chat["jid"],
        name=chat["name"],
        last_message_time=datetime.fromisoformat(chat["last_message_time"]) if chat["last_message_time"] else None,
        last_message=chat["last_message"],
        last_sender=chat["last_sender"],
        last_is_from_me=chat["last_is_from_me"],
    )


def get_sender_name(sender_jid: str) -> str:
    try:
        return _bridge_post("/contacts/name", {"jid": sender_jid}).get("name", sender_jid)
    except requests.RequestException as e:
        print(f"Bridge error while getting sender name: {e}")
        return sender_jid

def format_message(message: Message, show_chat_info: bool = True) -> None:
    """Print a single message with consistent formatting."""
    output = ""
    
    if show_chat_info and message.chat_name:
        output += f"[{message.timestamp:%Y-%m-%d %H:%M:%S}] Chat: {message.chat_name} "
    else:
        output += f"[{message.timestamp:%Y-%m-%d %H:%M:%S}] "
        
    content_prefix = ""
    if hasattr(message, 'media_type') and message.media_type:
        content_prefix = f"[{message.media_type} - Message ID: {message.id} - Chat JID: {message.chat_jid}] "
    
    try:
        sender_name = get_sender_name(message.sender) if not message.is_from_me else "Me"
        output += f"From: {sender_name}: {content_prefix}{message.content}\n"
    except Exception as e:
        print(f"Error formatting message: {e}")
    return output

def format_messages_list(messages: List[Message], show_chat_info: bool = True) -> None:
    output = ""
    if not messages:
        output += "No messages to display."
        return output
    
    for message in messages:
        output += format_message(message, show_chat_info)
    return output

def list_messages(
    after: Optional[str] = None,
    before: Optional[str] = None,
    sender_phone_number: Optional[str] = None,
    chat_jid: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_context: bool = True,
    context_before: int = 1,
    context_after: int = 1
) -> List[Message]:
    """Get messages matching the specified criteria with optional context."""
    try:
        # Validated and normalized to ISO-8601 here (same validation upstream
        # did before binding to the SQL param) — the bridge's /api/messages
        # just forwards these through to its own "timestamp > ?"/"< ?" params.
        if after:
            try:
                after = datetime.fromisoformat(after).isoformat()
            except ValueError:
                raise ValueError(f"Invalid date format for 'after': {after}. Please use ISO-8601 format.")
        if before:
            try:
                before = datetime.fromisoformat(before).isoformat()
            except ValueError:
                raise ValueError(f"Invalid date format for 'before': {before}. Please use ISO-8601 format.")

        data = _bridge_post("/messages", {
            "after": after or "", "before": before or "",
            "sender_phone_number": sender_phone_number or "", "chat_jid": chat_jid or "",
            "query": query or "", "limit": limit, "page": page,
        })

        result = [_to_message(msg) for msg in data.get("messages", [])]

        if include_context and result:
            # Add context for each message
            messages_with_context = []
            for msg in result:
                context = get_message_context(msg.id, context_before, context_after)
                messages_with_context.extend(context.before)
                messages_with_context.append(context.message)
                messages_with_context.extend(context.after)

            return format_messages_list(messages_with_context, show_chat_info=True)

        # Format and display messages without context
        return format_messages_list(result, show_chat_info=True)

    except requests.RequestException as e:
        print(f"Bridge error: {e}")
        return []


def get_message_context(
    message_id: str,
    before: int = 5,
    after: int = 5
) -> MessageContext:
    """Get context around a specific message."""
    try:
        response = requests.post(
            f"{WHATSAPP_API_BASE_URL}/messages/context",
            json={"message_id": message_id, "before": before, "after": after},
            headers=_BRIDGE_HEADERS,
            timeout=15,
        )
        if response.status_code == 404:
            raise ValueError(f"Message with ID {message_id} not found")
        response.raise_for_status()
        data = response.json()

        return MessageContext(
            message=_to_message(data["message"]),
            before=[_to_message(m) for m in data.get("before", [])],
            after=[_to_message(m) for m in data.get("after", [])],
        )

    except requests.RequestException as e:
        print(f"Bridge error: {e}")
        raise


def list_chats(
    query: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
    include_last_message: bool = True,
    sort_by: str = "last_active"
) -> List[Chat]:
    """Get chats matching the specified criteria."""
    try:
        data = _bridge_post("/chats", {
            "query": query or "", "limit": limit, "page": page,
            "include_last_message": include_last_message, "sort_by": sort_by,
        })
        return [_to_chat(c) for c in data.get("chats", [])]
    except requests.RequestException as e:
        print(f"Bridge error: {e}")
        return []


def search_contacts(query: str) -> List[Contact]:
    """Search contacts by name or phone number."""
    try:
        data = _bridge_post("/contacts/search", {"query": query})
        return [
            Contact(phone_number=c["jid"].split("@")[0], name=c["name"], jid=c["jid"])
            for c in data.get("contacts", [])
        ]
    except requests.RequestException as e:
        print(f"Bridge error: {e}")
        return []


def get_contact_chats(jid: str, limit: int = 20, page: int = 0) -> List[Chat]:
    """Get all chats involving the contact.
    
    Args:
        jid: The contact's JID to search for
        limit: Maximum number of chats to return (default 20)
        page: Page number for pagination (default 0)
    """
    try:
        data = _bridge_post("/contacts/chats", {"jid": jid, "limit": limit, "page": page})
        return [_to_chat(c) for c in data.get("chats", [])]
    except requests.RequestException as e:
        print(f"Bridge error: {e}")
        return []


def get_last_interaction(jid: str) -> str:
    """Get most recent message involving the contact."""
    try:
        data = _bridge_post("/messages/last-interaction", {"jid": jid})
        msg = data.get("message")
        if not msg:
            return None
        return format_message(_to_message(msg))
    except requests.RequestException as e:
        print(f"Bridge error: {e}")
        return None


def get_chat(chat_jid: str, include_last_message: bool = True) -> Optional[Chat]:
    """Get chat metadata by JID."""
    try:
        data = _bridge_post("/chats/get", {"chat_jid": chat_jid, "include_last_message": include_last_message})
        chat = data.get("chat")
        return _to_chat(chat) if chat else None
    except requests.RequestException as e:
        print(f"Bridge error: {e}")
        return None


def get_direct_chat_by_contact(sender_phone_number: str) -> Optional[Chat]:
    """Get chat metadata by sender phone number."""
    try:
        data = _bridge_post("/chats/by-contact", {"sender_phone_number": sender_phone_number})
        chat = data.get("chat")
        return _to_chat(chat) if chat else None
    except requests.RequestException as e:
        print(f"Bridge error: {e}")
        return None

def send_message(recipient: str, message: str) -> Tuple[bool, str]:
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"
        
        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {
            "recipient": recipient,
            "message": message,
        }

        # Vendor addition (not upstream): explicit timeout, matching
        # _bridge_post's own pattern above — this call (unlike that one) had
        # none at all, so a stalled bridge/WhatsApp-server round-trip left
        # this request hanging indefinitely on the Python side too, with
        # nothing here to ever raise a clear, actionable error. 45s is a few
        # seconds above the Go bridge's own server-side WriteTimeout (see
        # services/whatsapp-bridge/main.go), so a legitimately-completing
        # send is never cut off here first.
        response = requests.post(url, json=payload, headers=_BRIDGE_HEADERS, timeout=45)
        
        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"
            
    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

def send_file(recipient: str, media_path: str) -> Tuple[bool, str]:
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"
        
        if not media_path:
            return False, "Media path must be provided"
        
        if not os.path.isfile(media_path):
            return False, f"Media file not found: {media_path}"
        
        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {
            "recipient": recipient,
            "media_path": media_path
        }

        # See send_message's own timeout comment above — same gap, same fix.
        response = requests.post(url, json=payload, headers=_BRIDGE_HEADERS, timeout=45)

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

def send_audio_message(recipient: str, media_path: str) -> Tuple[bool, str]:
    try:
        # Validate input
        if not recipient:
            return False, "Recipient must be provided"
        
        if not media_path:
            return False, "Media path must be provided"
        
        if not os.path.isfile(media_path):
            return False, f"Media file not found: {media_path}"

        if not media_path.endswith(".ogg"):
            try:
                media_path = audio.convert_to_opus_ogg_temp(media_path)
            except Exception as e:
                return False, f"Error converting file to opus ogg. You likely need to install ffmpeg: {str(e)}"
        
        url = f"{WHATSAPP_API_BASE_URL}/send"
        payload = {
            "recipient": recipient,
            "media_path": media_path
        }

        # See send_message's own timeout comment above — same gap, same fix.
        response = requests.post(url, json=payload, headers=_BRIDGE_HEADERS, timeout=45)

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            return result.get("success", False), result.get("message", "Unknown response")
        else:
            return False, f"Error: HTTP {response.status_code} - {response.text}"

    except requests.RequestException as e:
        return False, f"Request error: {str(e)}"
    except json.JSONDecodeError:
        return False, f"Error parsing response: {response.text}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

def download_media(message_id: str, chat_jid: str) -> Optional[str]:
    """Download media from a message and return the local file path.
    
    Args:
        message_id: The ID of the message containing the media
        chat_jid: The JID of the chat containing the message
    
    Returns:
        The local file path if download was successful, None otherwise
    """
    try:
        url = f"{WHATSAPP_API_BASE_URL}/download"
        payload = {
            "message_id": message_id,
            "chat_jid": chat_jid
        }

        # See send_message's own timeout comment above — same gap, same fix.
        response = requests.post(url, json=payload, headers=_BRIDGE_HEADERS, timeout=45)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                path = result.get("path")
                print(f"Media downloaded successfully: {path}")
                return path
            else:
                print(f"Download failed: {result.get('message', 'Unknown error')}")
                return None
        else:
            print(f"Error: HTTP {response.status_code} - {response.text}")
            return None
            
    except requests.RequestException as e:
        print(f"Request error: {str(e)}")
        return None
    except json.JSONDecodeError:
        print(f"Error parsing response: {response.text}")
        return None
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return None
