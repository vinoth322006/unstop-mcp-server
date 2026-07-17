from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from mcp.server.fastmcp import Context
from server import mcp
import json

# --- Pydantic Models for Strict Validation ---
class ContestModel(BaseModel):
    id: str = Field(..., description="Unique identifier for the contest")
    name: str = Field(..., description="Name of the contest")
    category: str = Field(..., description="Category of the contest (e.g., Hackathon, Coding, AI, Design)")
    status: str = Field(..., description="Current status of the contest (e.g., Open, Closed)")
    prize: str = Field(..., description="Prize pool amount")

class ParticipationModel(BaseModel):
    contest_id: str = Field(..., description="ID of the contest the user participated in")
    status: str = Field(..., description="User's status in the contest (e.g., Registered, Completed, Shortlisted)")

class AnalyticsModel(BaseModel):
    participants: int = Field(..., description="Total number of participants")
    average_score: Any = Field(..., description="Average score of participants")
    top_college: str = Field(..., description="College with the highest representation or score")

# --- Mock Data ---
CONTESTS: List[Dict[str, Any]] = [
    {"id": "c1", "name": "Hack the Future 2026", "category": "Hackathon", "status": "Open", "prize": "$10,000"},
    {"id": "c2", "name": "Code Crafters Challenge", "category": "Coding", "status": "Closed", "prize": "$5,000"},
    {"id": "c3", "name": "AI Innovation Fest", "category": "AI", "status": "Open", "prize": "$20,000"},
    {"id": "c4", "name": "Designathon 3.0", "category": "Design", "status": "Open", "prize": "$3,000"},
]

USER_PARTICIPATION: Dict[str, List[Dict[str, str]]] = {
    "user123": [{"contest_id": "c1", "status": "Registered"}, {"contest_id": "c2", "status": "Completed"}],
    "user456": [{"contest_id": "c3", "status": "Shortlisted"}]
}

ANALYTICS: Dict[str, Dict[str, Any]] = {
    "c1": {"participants": 1500, "average_score": "N/A (Ongoing)", "top_college": "MIT"},
    "c2": {"participants": 800, "average_score": 85.5, "top_college": "Stanford"},
    "c3": {"participants": 3200, "average_score": "N/A (Ongoing)", "top_college": "IIT Bombay"},
    "c4": {"participants": 450, "average_score": "N/A (Ongoing)", "top_college": "NID"}
}

# --- Resources ---
@mcp.resource("unstop://rules")
def get_platform_rules() -> str:
    """Read the official Unstop platform rules and guidelines."""
    return (
        "UNSTOP PLATFORM RULES:\n"
        "1. All participants must be currently enrolled in an educational institution or be recent graduates.\n"
        "2. Plagiarism in coding contests will result in immediate disqualification.\n"
        "3. Teams must consist of 1 to 4 members unless specified otherwise.\n"
    )

@mcp.resource("unstop://categories")
def get_valid_categories() -> str:
    """Get the list of valid contest categories."""
    return json.dumps(["Hackathon", "Coding", "AI", "Design"])


# --- Tools ---
@mcp.tool()
async def discover_contests(ctx: Context, category: Optional[str] = None, status: Optional[str] = None) -> List[ContestModel]:
    """
    Discover contests on Unstop.
    Optionally filter by category or status.
    """
    await ctx.info(f"Filtering contests. Category: {category}, Status: {status}")
    results = CONTESTS
    if category:
        results = [c for c in results if c['category'].lower() == category.lower()]
    if status:
        results = [c for c in results if c['status'].lower() == status.lower()]
    
    if not results:
        await ctx.warning("No contests found matching the given criteria.")
        
    return [ContestModel(**c) for c in results]

@mcp.tool()
async def track_participation(ctx: Context, user_id: str) -> List[ParticipationModel]:
    """
    Track participation status for a specific user ID.
    Returns a list of contests the user has participated in and their status.
    """
    await ctx.info(f"Fetching participation record for user: {user_id}")
    records = USER_PARTICIPATION.get(user_id, [])
    if not records:
        await ctx.warning(f"No participation records found for user {user_id}")
    
    return [ParticipationModel(**r) for r in records]

@mcp.tool()
async def get_analytics(ctx: Context, contest_id: str) -> AnalyticsModel:
    """
    Get analytics for a specific contest ID.
    """
    await ctx.info(f"Generating analytics report for contest: {contest_id}")
    data = ANALYTICS.get(contest_id)
    if not data:
        await ctx.error(f"Contest {contest_id} not found.")
        raise ValueError(f"Contest {contest_id} not found in the database.")
        
    return AnalyticsModel(**data)


# --- Prompts ---
@mcp.prompt("analyze_contest")
def analyze_contest_prompt(contest_id: str) -> str:
    """Create a prompt to analyze a specific contest."""
    return (
        f"Please use the `get_analytics` tool to fetch the analytics for the contest '{contest_id}'. "
        "Then, summarize the participant performance and provide insights based on the average score and top college representation."
    )
