"""Instagram manager: one request -> the step for that kind of job -> the answer.

    in -> Pick the job (condition, AI) -> one of
          Report | My posts | Publish | Comments | Messages | Research | Help
       -> out

The condition step reads the request and takes exactly one line; the others are skipped. Each step is an agent
that gets only its group's Instagram tools (``tool_needs`` on thenavidm/instagram-mcp), so a report can never post
and a research question can never reply to a comment. Steps that change something (publish, reply, hide, DM) ask
first: approvals edit/delete are on. Never given: delete_comment (hide is the reversible way) and the unofficial_*
tools (Instagram's private API, against Meta's terms).
"""
from __future__ import annotations

INSTAGRAM = ("Instagram", ["thenavidm/instagram-mcp"])

# Reading never stops a run; anything that changes the account asks first.
ASK_BEFORE_CHANGES = {"read": False, "edit": True, "delete": True}

COMMON = (
    " Use only what the tools returned – never invent a number, username, comment or link. If a tool fails with a "
    "permission error (code 10 or 200), say which Meta permission it needs (instagram_manage_insights, "
    "instagram_manage_comments, instagram_content_publish, instagram_manage_messages or pages_read_engagement) and "
    "that it is added when the token is made again. Answer in the language the request was written in."
)


def need(tools: list[str]) -> list[dict]:
    return [{"system": INSTAGRAM[0], "match": INSTAGRAM[1], "tools": tools, "required": True}]


def agent_node(node_id: str, x: int, y: int, *, name: str, role: str, goal: str, instructions: str,
               tools: list[str] | None, max_calls: int = 6) -> dict:
    config: dict = {
        "approvals": ASK_BEFORE_CHANGES,
        "tool_needs": need(tools) if tools else [],
        "tools": {"max_calls": max_calls, "timeout_seconds": 90, "on_failure": "continue"},
        "response": {"citations": "off"},
    }
    return {
        "id": node_id, "type": "agent", "label": name, "position": {"x": x, "y": y},
        "draft_agent": {"name": name, "role": role, "goal": goal, "instructions": instructions + COMMON, "config": config},
    }


# (node id, the condition line's label, the step)
BRANCHES: list[tuple[str, str, dict]] = [
    ("report", "Report", dict(
        name="Report",
        role="Instagram analyst",
        goal="Say how the account is doing: reach, followers, profile views and which posts worked.",
        instructions=(
            "Read the account's insights for the period asked (the last 7 days if none), then the recent posts and "
            "the insights of the best and worst of them. Answer with: a 3-line summary, a small table of the numbers "
            "(this period vs the one before when growth_history has it), the top 3 posts with their permalink and "
            "why they worked, and 2-3 concrete suggestions."
        ),
        tools=["whoami", "get_account_insights", "get_media", "get_media_insights", "growth_history", "post_movement"],
        max_calls=8,
    )),
    ("posts", "My posts", dict(
        name="My posts",
        role="Instagram content librarian",
        goal="Find and list the account's own posts, stories and the posts it was tagged in.",
        instructions=(
            "Find what was asked: recent posts (get_media), the whole history (list_all_media, only when the request "
            "needs older posts), live stories, one post by id, or posts others tagged the account in. Answer with a "
            "table: date, type, caption (first 60 characters), likes, comments, permalink."
        ),
        tools=["get_media", "get_media_by_id", "list_all_media", "list_stories", "list_tagged_media"],
    )),
    ("publish", "Publish", dict(
        name="Publish",
        role="Instagram publisher",
        goal="Publish the post, carousel, reel or story the request describes.",
        instructions=(
            "First check get_publishing_limit. Meta fetches the media itself, so every image or video must be a "
            "public https URL; if the request has none, do not call a publishing tool – answer that a public link to "
            "the image or video is needed. Tidy the caption if asked (keep the person's words and hashtags), then use "
            "post (one image or video), post_carousel (2-20 items, in order), publish_reel or publish_story. The run "
            "asks the person before anything is published. Answer with what was published and its permalink, or the "
            "error."
        ),
        tools=["get_publishing_limit", "post", "post_carousel", "publish_reel", "publish_story", "search_audio",
               "get_container_status"],
    )),
    ("comments", "Comments", dict(
        name="Comments",
        role="Instagram community manager",
        goal="Read the comments, sort them, and reply to or hide the ones the request is about.",
        instructions=(
            "Read the comments (read_all_comments for recent posts, get_comments for one post, get_comment_replies "
            "for a thread). Sort them into questions, praise, complaints and spam. Only when the request asks for it: "
            "reply_to_comment with a short, friendly reply in the commenter's language; hide_comment for spam or "
            "abuse (hiding can be undone – never delete); private_reply_to_comment to answer someone in DM, e.g. a "
            "price or link request. Each of these asks the person first. Answer with the sorted list and what was "
            "done."
        ),
        tools=["read_all_comments", "get_comments", "get_comment_replies", "reply_to_comment", "hide_comment",
               "private_reply_to_comment"],
        max_calls=12,
    )),
    ("messages", "Messages", dict(
        name="Messages",
        role="Instagram inbox assistant",
        goal="Read the DM threads and send the replies the request asks for.",
        instructions=(
            "List the conversations, open the ones that matter, and summarise who wrote and what they want. Send a "
            "reply with send_dm only when the request asks for it; Instagram allows it only within 24 hours of the "
            "person's last message – if that window has passed, say so instead. Sending asks the person first."
        ),
        tools=["list_conversations", "get_conversation", "send_dm"],
        max_calls=8,
    )),
    ("research", "Research", dict(
        name="Research",
        role="Instagram market researcher",
        goal="Look at other Business or Creator accounts and hashtags and say what is working for them.",
        instructions=(
            "For accounts: discover_account by username (without @), compare_accounts for several side by side. For "
            "hashtags: search_hashtag to get its id, then hashtag_top_media and hashtag_recent_media (Instagram "
            "allows only 30 different hashtags a week, so look up only the ones asked). Answer with a short table "
            "and 3 ideas the account could use."
        ),
        tools=["discover_account", "compare_accounts", "search_hashtag", "hashtag_top_media", "hashtag_recent_media"],
        max_calls=8,
    )),
    ("help", "", dict(
        name="Help",
        role="Instagram manager guide",
        goal="Explain what this workflow can do when the request isn't clear.",
        instructions=(
            "The request did not clearly ask for one of this workflow's jobs. In a few lines, say what you understood "
            "and ask one question to make it clear. List what can be asked, one line each: a report (reach, followers, "
            "best posts), my posts, publish a post/carousel/reel/story (needs a public image or video link), "
            "comments (read, reply, hide, reply in DM), messages (read and reply within 24 hours), research (other "
            "accounts, hashtags)."
        ),
        tools=None,
    )),
]

ROUTER_INSTRUCTIONS = (
    "The text is a person's request about their Instagram account. Pick the job it asks for: "
    "Report = numbers, insights, reach, followers, growth, how posts performed; "
    "My posts = list or find the account's own posts, stories or tagged posts; "
    "Publish = post, upload, share or schedule an image, carousel, reel or story; "
    "Comments = read, reply to, hide or answer comments; "
    "Messages = DMs, inbox, direct messages; "
    "Research = another account, a competitor, or a hashtag. "
    "When it asks for two jobs, pick the one it asks to DO (Publish, Comments, Messages) over the one it asks to read."
)


def build() -> dict:
    """The workflow to create: a ``WorkflowCreate`` body."""
    nodes = [
        {"id": "in", "type": "input", "label": "Your request", "position": {"x": 40, "y": 600}},
        {"id": "pick", "type": "condition", "label": "Pick the job", "position": {"x": 340, "y": 600},
         "condition_config": {"mode": "ai", "instructions": ROUTER_INSTRUCTIONS, "default_branch": "help"}},
        *[agent_node(nid, 680, 40 + i * 190, **spec) for i, (nid, _, spec) in enumerate(BRANCHES)],
        {"id": "out", "type": "output", "label": "Answer", "position": {"x": 1020, "y": 600},
         "output_config": {"format": "markdown", "compose": "off"}},
    ]
    edges = [{"id": "e_in", "source": "in", "target": "pick"}]
    for nid, label, _ in BRANCHES:
        edges.append({"id": f"e_pick_{nid}", "source": "pick", "target": nid, **({"condition": label} if label else {})})
        edges.append({"id": f"e_{nid}_out", "source": nid, "target": "out"})
    return {
        "name": "Instagram manager",
        "description": (
            "Ask anything about your Instagram account: a report, your posts, publishing, comments, messages or "
            "research on other accounts and hashtags. It picks the right step for the request and runs only that one; "
            "anything that posts, replies, hides or sends asks you first."
        ),
        "nodes": nodes,
        "edges": edges,
        "config": {
            "max_run_seconds": 900,
            "on_node_failure": "abort",
            "approvals": ASK_BEFORE_CHANGES,
            "answer_general_questions": True,
        },
    }


TEMPLATE = {
    "key": "instagram_manager",
    "name": "Instagram manager",
    "summary": "One request -> the right Instagram step (report, posts, publish, comments, messages, research).",
    "build": build,
}
