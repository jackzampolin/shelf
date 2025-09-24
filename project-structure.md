# Updated Project Structure for Biographical Research

## Core Philosophy
Organize by **player** not by document type. Each historical figure gets their own research space, with agents processing their materials.

```
aerospace-republic/
├── README.md                    # Project overview & thesis
├── keyplayers.md               # Master list of biographical subjects
├── sources.md                  # Access strategy & credentials
├── agents.md                   # Agent architecture documentation
│
├── config/
│   ├── thesis.yaml            # Core thesis & themes
│   ├── periods.yaml           # Time periods of interest
│   ├── sources.yaml           # API keys, library credentials
│   └── agents_config.yaml     # Agent parameters & prompts
│
├── players/                    # ONE FOLDER PER PERSON
│   ├── macarthur_douglas/
│   │   ├── profile.md         # Quick bio & thesis relevance
│   │   ├── timeline.json      # Key dates & decisions
│   │   ├── sources/
│   │   │   ├── primary/       # Letters, speeches, reports
│   │   │   ├── biographies/   # Full text biographies
│   │   │   │   ├── manchester_american_caesar.md
│   │   │   │   └── herman_macarthur.md
│   │   │   └── contemporary/  # News, criticism from 1935-55
│   │   ├── extracts/          # Agent-extracted content
│   │   │   ├── quotes.json    # Key quotations
│   │   │   ├── decisions.json # Critical decisions
│   │   │   ├── relationships.json
│   │   │   └── contradictions.json
│   │   ├── crossroads/        # Intersection moments
│   │   │   ├── 1944_pacific_debate.md
│   │   │   ├── 1950_korea_strategy.md
│   │   │   └── 1951_dismissal.md
│   │   └── analysis/
│   │       ├── thesis_alignment.md
│   │       ├── alternative_paths.md
│   │       └── contemporary_critics.md
│   │
│   ├── marshall_george/
│   │   └── [same structure]
│   │
│   ├── acheson_dean/
│   │   └── [same structure]
│   │
│   └── [other players...]
│
├── agents/                     # Agent code
│   ├── __init__.py
│   ├── orchestrator.py        # Main coordinator
│   ├── discovery/
│   │   ├── biography_hunter.py
│   │   ├── archive_searcher.py
│   │   └── crossroads_detector.py
│   ├── filters/
│   │   ├── thesis_alignment.py
│   │   ├── relevance_scorer.py
│   │   └── opposition_finder.py
│   ├── extractors/
│   │   ├── quote_extractor.py
│   │   ├── metadata_extractor.py
│   │   └── relationship_mapper.py
│   └── synthesis/
│       ├── narrative_builder.py
│       ├── contradiction_finder.py
│       └── timeline_creator.py
│
├── crossroads/                 # Key intersection moments
│   ├── 1940_41_intervention_debate/
│   │   ├── overview.md
│   │   ├── players_involved.json
│   │   ├── positions/         # Each player's stance
│   │   └── outcome_analysis.md
│   ├── 1944_45_pacific_priority/
│   ├── 1945_atomic_decision/
│   ├── 1946_china_policy/
│   ├── 1950_korea_intervention/
│   └── 1951_macarthur_firing/
│
├── themes/                     # Cross-player thematic analysis
│   ├── industrial_decline/
│   │   ├── evidence.md
│   │   ├── players_positions.json
│   │   └── timeline.md
│   ├── financial_dominance/
│   ├── aerospace_supremacy/
│   ├── china_loss/
│   └── surveillance_state/
│
├── scripts/                    # Automation & utilities
│   ├── download_sources.py
│   ├── run_agents.py
│   ├── validate_data.py
│   └── build_narrative.py
│
├── outputs/                    # Generated content
│   ├── narratives/            # Complete player narratives
│   │   ├── macarthur_narrative.md
│   │   └── marshall_narrative.md
│   ├── timelines/             # Interactive timelines
│   ├── networks/              # Relationship visualizations
│   └── podcast_notes/         # Prepared podcast content
│
├── raw_downloads/              # Original sources (git-ignored)
│   ├── archive_org/
│   ├── google_books/
│   └── jstor/
│
└── cache/                      # Agent processing cache
    ├── llm_responses/          # Cached AI analysis
    ├── ocr_output/             # Processed documents
    └── search_results/         # API response cache
```

## Key Improvements

### 1. Player-Centric Organization
- Each person is a complete research unit
- Easy to track completeness per biography
- Natural for biographical narrative approach

### 2. Crossroads as First-Class Citizens
- Dedicated folders for key historical moments
- Shows where players intersected/conflicted
- Perfect for podcast episode structure

### 3. Agent Integration
```python
# scripts/run_agents.py
def process_player(player_name):
    """Run all agents for one biographical subject"""
    
    # Create player directory structure
    player_dir = Path(f"players/{player_name}")
    player_dir.mkdir(exist_ok=True)
    
    # Run discovery agents
    sources = discover_sources(player_name)
    
    # Run filter agents
    relevant = filter_relevant(sources, thesis_config)
    
    # Run extraction agents
    for source in relevant:
        extracts = extract_all(source)
        save_extracts(player_dir / "extracts", extracts)
    
    # Run synthesis
    narrative = build_narrative(player_dir)
    save_narrative(narrative)
```

### 4. Thesis Tracking
```yaml
# config/thesis.yaml
thesis:
  core: "1935-1955 decisions created Aerospace Republic"
  themes:
    - id: "industrial_decline"
      claim: "Prioritized aerospace over manufacturing"
      evidence_needed:
        - "Marshall Plan impact on US factories"
        - "Air Force independence consequences"
    - id: "china_loss"  
      claim: "Ignored MacArthur/China Lobby warnings"
      evidence_needed:
        - "MacArthur 1944-45 memos"
        - "State Dept purge of China experts"
```

### 5. Source Management
```python
# Each source gets metadata
{
  "source_id": "manchester_1978",
  "type": "biography",
  "title": "American Caesar",
  "author": "William Manchester",
  "year": 1978,
  "access": {
    "platform": "scribd",
    "status": "full_text",
    "cost": "subscription"
  },
  "relevance_score": 95,
  "extracted": true,
  "agent_notes": "Critical for MacArthur-Marshall conflict"
}
```

## Workflow Example

### Researching MacArthur

1. **Setup Phase**
```bash
python scripts/setup_player.py --name "macarthur_douglas"
# Creates directory structure
```

2. **Discovery Phase**
```bash
python agents/orchestrator.py discover --player macarthur
# Searches all configured sources
# Output: players/macarthur_douglas/sources/candidates.json
```

3. **Filter Phase**
```bash
python agents/orchestrator.py filter --player macarthur
# Applies thesis relevance filters
# Output: players/macarthur_douglas/sources/relevant.json
```

4. **Extract Phase**
```bash
python agents/orchestrator.py extract --player macarthur
# Runs all extraction agents
# Output: players/macarthur_douglas/extracts/
```

5. **Synthesis Phase**
```bash
python agents/orchestrator.py synthesize --player macarthur
# Builds narrative
# Output: outputs/narratives/macarthur_narrative.md
```

## Git Strategy

### What to Track
```gitignore
# Don't track
raw_downloads/
cache/llm_responses/
*.pdf
*.epub

# Do track
players/*/profile.md
players/*/timeline.json
players/*/extracts/*.json
players/*/analysis/*.md
crossroads/
themes/
outputs/narratives/
```

### Branch Strategy
- `main`: Validated, synthesized narratives
- `research/[player]`: Active research on specific person
- `agents/[feature]`: Agent development
- `crossroads/[event]`: Deep dive on specific moment

## Metrics Dashboard

```python
# scripts/research_status.py
def generate_status():
    return {
        "players": {
            "macarthur": {
                "sources_found": 89,
                "sources_processed": 34,
                "quotes_extracted": 234,
                "crossroads_identified": 12,
                "narrative_complete": 75
            },
            "marshall": {
                "sources_found": 67,
                "sources_processed": 12,
                "quotes_extracted": 89,
                "crossroads_identified": 8,
                "narrative_complete": 35
            }
        },
        "themes": {
            "industrial_decline": {
                "evidence_pieces": 45,
                "players_analyzed": 8,
                "strength": "strong"
            }
        },
        "total_cost": {
            "api_calls": "$23.45",
            "book_purchases": "$234.00",
            "subscriptions": "$43.00"
        }
    }
```

## Next Actions

1. **Create `setup_project.py`** to initialize structure
2. **Build first agent** - QuoteExtractor for testing
3. **Choose 3 test documents** about MacArthur
4. **Run extraction pipeline** manually first
5. **Iterate on agent prompts** based on results
6. **Scale to full automation** once working