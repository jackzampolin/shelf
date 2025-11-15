# Gap Healing Agent Design

## Architecture (Based on link_toc pattern)

### Orchestrator Pattern
```
pipeline/label_structure/gap_healing/orchestrator.py
```

**Responsibilities:**
1. Load clusters from `clusters.json`
2. Create one `AgentConfig` per cluster
3. Run agents in parallel (batch of ~30 for accidental-president)
4. Collect results incrementally
5. Apply healing decisions to page files
6. Generate final summary

### Agent Tools

**Agent gets custom tools instance per cluster:**
```python
class GapHealingTools(AgentTools):
    def __init__(self, storage: BookStorage, cluster: Dict):
        self.storage = storage
        self.cluster = cluster  # Contains: cluster_id, type, scan_pages, etc.
        self._pending_decision: Optional[Dict] = None
```

**Available tools:**

1. **`get_page_metadata(page_num: int)`**
   - Load full `page_{:04d}.json` from label-structure
   - Shows: headings, header/footer, page_number observation, pattern_hints
   - Returns complete merged output (mechanical + structure + annotations)

2. **`view_page_image(page_num: int, current_page_observations: str)`**
   - Same pattern as link_toc (enforces observation before switching)
   - Load downsampled source image
   - Use when metadata is ambiguous
   - Costs ~$0.001/page (vision model)

3. **`grep_headings(pattern: str)`**
   - Search heading text across ALL pages
   - Find similar chapter patterns
   - Returns: matches with page numbers and heading levels

4. **`get_page_sequence(start_page: int, end_page: int)`**
   - Get page number sequence for range
   - Shows detected vs expected values
   - Useful for understanding cascade extent

5. **`write_healing_decision(...)`**
   - Final output (terminates agent)
   - Records decision in `_pending_decision`

## Output Format

**Per-cluster healing decision file:**
```
{book}/label-structure/healing/{cluster_id}.json
```

**Schema:**
```python
{
    "cluster_id": "backward_jump_0037",
    "cluster_type": "backward_jump",
    "scan_pages": [37, 38],

    # Agent decision
    "healing_action": "fix_page_number" | "mark_as_chapter" | "accept_as_is" | "needs_manual_review",
    "confidence": 0.95,
    "reasoning": "Agent's explanation...",

    # Page updates (one per page in cluster)
    "page_updates": [
        {
            "scan_page": 37,
            "page_number_update": {
                "present": true,
                "number": "23",
                "location": "margin",
                "confidence": "high",
                "source_provider": "agent_healed"
            },
            "chapter_marker": {  # Optional - only if this is a chapter page
                "chapter_num": 3,
                "chapter_title": "The First Days",
                "confidence": 0.95,
                "detected_from": "heading"
            }
        },
        {
            "scan_page": 38,
            "page_number_update": {
                "present": true,
                "number": "24",
                "location": "margin",
                "confidence": "high",
                "source_provider": "agent_healed"
            }
        }
    ],

    # Agent metadata
    "agent_iterations": 5,
    "pages_examined": [36, 37, 38, 39],
    "images_viewed": [37],
    "cost_usd": 0.003
}
```

**Key design choices:**

1. **Partial updates only:** `page_number_update` contains ONLY the fields to merge
   - Matches existing `PageNumberObservation` schema
   - Easy to apply: `page_data['page_number'].update(update_fields)`

2. **Chapter discovery as metadata:** Optional `chapter_marker` extracted from backward_jumps
   - Separate from page_number healing
   - Can aggregate later for TOC comparison

3. **One decision file per cluster:**
   - Audit trail preserved
   - Can re-run individual clusters
   - Easy to review before applying

## Workflow

### Phase 1: Agent Dispatch (orchestrator.py)

```python
def heal_all_clusters(storage, logger, model, max_iterations=10):
    # Load clusters
    cluster_data = storage.stage("label-structure").load_file("clusters.json")
    clusters = cluster_data['clusters']

    # Create agent configs
    configs = []
    for cluster in clusters:
        tools = GapHealingTools(storage, cluster)

        initial_messages = [
            {"role": "system", "content": HEALER_SYSTEM_PROMPT},
            {"role": "user", "content": build_healer_user_prompt(cluster)}
        ]

        configs.append(AgentConfig(
            model=model,
            initial_messages=initial_messages,
            tools=tools,
            stage_storage=storage.stage('label-structure'),
            agent_id=f"heal_{cluster['cluster_id']}",
            max_iterations=max_iterations
        ))

    # Run batch
    batch = AgentBatchClient(AgentBatchConfig(configs, max_workers=10))
    results = batch.run()

    # Save decisions
    healing_dir = storage.stage("label-structure").output_dir / "healing"
    healing_dir.mkdir(exist_ok=True)

    for agent_result, cluster in zip(results.results, clusters):
        tools = tools_by_cluster[cluster['cluster_id']]

        if agent_result.success and tools._pending_decision:
            decision = tools._pending_decision
            decision['agent_iterations'] = agent_result.iterations
            decision['cost_usd'] = agent_result.cost_usd

            # Save decision file
            decision_path = healing_dir / f"{cluster['cluster_id']}.json"
            with open(decision_path, 'w') as f:
                json.dump(decision, f, indent=2)
```

### Phase 2: Application (apply.py)

```python
def apply_healing_decisions(storage, logger):
    """Apply all healing decisions to page files."""

    healing_dir = storage.stage("label-structure").output_dir / "healing"

    for decision_file in healing_dir.glob("*.json"):
        with open(decision_file) as f:
            decision = json.load(f)

        if decision['healing_action'] == 'needs_manual_review':
            logger.warning(f"Skipping {decision['cluster_id']}: needs manual review")
            continue

        # Apply page updates
        for page_update in decision['page_updates']:
            page_num = page_update['scan_page']

            # Load existing page file
            page_data = storage.stage("label-structure").load_file(f"page_{page_num:04d}.json")

            # Merge page_number update
            if 'page_number_update' in page_update:
                page_data['page_number'].update(page_update['page_number_update'])

            # Add chapter marker if present (new field)
            if 'chapter_marker' in page_update:
                page_data['chapter_marker'] = page_update['chapter_marker']

            # Save updated page
            storage.stage("label-structure").save_file(
                f"page_{page_num:04d}.json",
                page_data,
                schema=LabelStructurePageOutput
            )

        logger.info(f"Applied healing: {decision['cluster_id']}")
```

### Phase 3: Chapter Discovery (optional)

```python
def extract_chapter_markers(storage, logger):
    """Aggregate chapter markers from healing decisions."""

    healing_dir = storage.stage("label-structure").output_dir / "healing"
    chapters = []

    for decision_file in healing_dir.glob("*.json"):
        with open(decision_file) as f:
            decision = json.load(f)

        for page_update in decision['page_updates']:
            if 'chapter_marker' in page_update:
                marker = page_update['chapter_marker']
                chapters.append({
                    'chapter_num': marker['chapter_num'],
                    'scan_page': page_update['scan_page'],
                    'title': marker['chapter_title'],
                    'confidence': marker['confidence']
                })

    # Sort by chapter number
    chapters.sort(key=lambda x: x['chapter_num'])

    # Save for future TOC comparison
    storage.stage("label-structure").save_file(
        "discovered_chapters.json",
        {"chapters": chapters}
    )

    logger.info(f"Discovered {len(chapters)} chapter markers from healing")
```

## Prompting Strategy

**System Prompt:** Pattern recognition expert, knows all 4 issue types

**User Prompt:** Cluster-specific context
```
You are analyzing a gap healing cluster:

**Cluster:** {cluster_id}
**Type:** {type}
**Pages:** {scan_pages}
**Priority:** {priority}

{type-specific context}

**Tools available:**
- get_page_metadata: See full page labels
- view_page_image: Visual inspection ($0.001/page)
- grep_headings: Find similar patterns
- get_page_sequence: Understand cascade

**Your task:**
1. Examine pages in cluster + context
2. Determine root cause
3. Propose healing action
4. Extract chapter markers if applicable
5. Call write_healing_decision with your decision
```

**Type-specific prompts:**
- Backward jump → Check if detected value == chapter number
- OCR error → Apply substitution heuristics
- Structural gap → Verify intentional vs missing pages
- Gap mismatch → Determine cause of size difference

## Cost Estimation

**For accidental-president (30 clusters):**
- Text-only examination: ~$0.01/cluster = $0.30
- With vision (10% of cases): ~$0.001/image * 3 images = ~$0.03 extra
- **Total: ~$0.30-$0.50 per book**

**Library-wide (19 books, ~300 clusters):**
- **Total: ~$6-$10 for full library healing**

Much cheaper than running full label-structure again ($40).

## Next Steps

1. Implement `GapHealingTools` class
2. Write system + user prompts
3. Build orchestrator
4. Test on accidental-president
5. Apply healing
6. Regenerate report.csv
7. Verify improvements
