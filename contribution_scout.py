#!/usr/bin/env python3
"""
Contribution Scout v2 — Finds real contribution opportunities.
Uses `gh issue list` for reliable results.
"""

import json
import os
import subprocess
from datetime import datetime, timezone

# Repos Sir uses, tiered by relevance
REPO_WATCHLIST = {
    "primary": [
        ("serengil/deepface", "Face recognition — Sir's presence detection"),
        ("HKUDS/LightRAG", "Knowledge graph — Sir's RAG pipeline"),
        ("mem0ai/mem0", "Memory layer — Sir explored for memory mgmt"),
        ("howdy-ai/howdy", "Face recognition for Linux"),
    ],
    "tools": [
        ("openclaw/openclaw", "AI assistant framework — Rhendix runs on this"),
        ("Textualize/rich", "Terminal formatting — used in all our projects"),
        ("pallets/click", "CLI framework — used in all our projects"),
    ],
    "ml_ecosystem": [
        ("scikit-learn/scikit-learn", "ML library — Sir uses extensively"),
        ("dmlc/xgboost", "Gradient boosting — competition workhorse"),
        ("microsoft/LightGBM", "Gradient boosting — competition workhorse"),
        ("pytorch/vision", "Computer vision — Sir's focus area"),
    ],
}

# Labels to search for (in priority order)
SEARCH_LABELS = [
    "good first issue",
    "good-first-issue", 
    "help wanted",
    "documentation",
    "bug",
    "enhancement",
]

def run_gh(args, timeout=30):
    """Run gh CLI and return parsed JSON."""
    try:
        result = subprocess.run(
            ["gh"] + args + ["--json", "number,title,labels,url,comments,body"],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "GH_PAGER": ""}
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
        return []
    except Exception:
        return []

def score_opportunity(issue, repo, tier):
    """Score an issue for contribution fit."""
    score = 0.0
    
    tier_weights = {"primary": 0.4, "tools": 0.3, "ml_ecosystem": 0.2}
    score += tier_weights.get(tier, 0.1) * 30
    
    labels = [l.get("name", "").lower() for l in issue.get("labels", [])]
    
    # Label bonuses
    if any(x in labels for x in ["good first issue", "good-first-issue", "beginner friendly"]):
        score += 25
    if "documentation" in labels or "docs" in labels:
        score += 22  # High value, low effort
    if "help wanted" in labels:
        score += 18
    if "bug" in labels:
        score += 12
    if "enhancement" in labels:
        score += 8
    
    # Fewer comments = less competition  
    comments = issue.get("comments", 0)
    if isinstance(comments, list):
        comments = len(comments)
    if comments == 0:
        score += 15
    elif comments <= 3:
        score += 10
    elif comments <= 10:
        score += 5
    
    # Well-described issues
    body = issue.get("body", "") or ""
    if len(body) > 200:
        score += 5
    
    return min(score, 100)

def main():
    print("🔍 Contribution Scout v2\n")
    
    all_opportunities = []
    
    for tier, repos in REPO_WATCHLIST.items():
        for repo, desc in repos:
            found_for_repo = False
            
            for label in SEARCH_LABELS:
                if found_for_repo:
                    break
                    
                issues = run_gh(["issue", "list", "--repo", repo, 
                                "--state", "open", "--label", label, "--limit", "5"])
                
                for issue in issues:
                    labels = [l.get("name", "") for l in issue.get("labels", [])]
                    opp = {
                        "repo": repo,
                        "repo_desc": desc,
                        "tier": tier,
                        "issue_number": issue.get("number"),
                        "title": issue.get("title"),
                        "url": issue.get("url"),
                        "labels": labels,
                        "comments": issue.get("comments", 0),
                    }
                    opp["score"] = score_opportunity(issue, repo, tier)
                    all_opportunities.append(opp)
                    found_for_repo = True
            
            # If no labeled issues, grab recent open ones
            if not found_for_repo:
                issues = run_gh(["issue", "list", "--repo", repo,
                                "--state", "open", "--limit", "3"])
                for issue in issues:
                    opp = {
                        "repo": repo,
                        "repo_desc": desc,
                        "tier": tier,
                        "issue_number": issue.get("number"),
                        "title": issue.get("title"),
                        "url": issue.get("url"),
                        "labels": [l.get("name", "") for l in issue.get("labels", [])],
                        "comments": issue.get("comments", 0),
                    }
                    opp["score"] = score_opportunity(issue, repo, tier) * 0.5
                    all_opportunities.append(opp)
    
    # Sort and deduplicate
    all_opportunities.sort(key=lambda x: x["score"], reverse=True)
    seen = set()
    unique = []
    for opp in all_opportunities:
        if opp["url"] not in seen:
            seen.add(opp["url"])
            unique.append(opp)
    
    # Output
    print(f"📊 Found {len(unique)} opportunities across {sum(len(r) for r in REPO_WATCHLIST.values())} repos\n")
    print("=" * 80)
    
    for i, opp in enumerate(unique[:20], 1):
        tier_icon = {"primary": "🎯", "tools": "🔧", "ml_ecosystem": "🧠"}.get(opp["tier"], "📦")
        labels_str = ", ".join(opp.get("labels", [])[:4]) or "none"
        print(f"\n{i}. {tier_icon} [{opp['repo']}] Score: {opp['score']:.0f}")
        print(f"   #{opp['issue_number']} — {opp['title']}")
        print(f"   Labels: {labels_str}")
        print(f"   🔗 {opp['url']}")
    
    # Save
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(unique),
        "top": unique[:20],
    }
    path = os.path.expanduser("~/.openclaw/contribution-scout-results.json")
    with open(path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Saved to {path}")
    
    return output

if __name__ == "__main__":
    main()
