# Agent Architecture for Historical Research Pipeline

## Problem Statement
Searching for "Douglas MacArthur" returns thousands of results. We need intelligent agents to:
1. Filter for relevance to our Aerospace Republic thesis
2. Extract key quotes and metadata
3. Build relationship networks
4. Identify "crossroads moments"

## Agent Hierarchy

```
┌─────────────────────────────────────┐
│     Orchestrator Agent              │
│     (Research Director)             │
└────────────┬────────────────────────┘
             │
    ┌────────┴────────┬──────────┬─────────┐
    │                 │          │         │
┌───▼──────┐ ┌───────▼──────┐ ┌─▼──────┐ ┌▼────────┐
│Discovery │ │Relevance     │ │Extract │ │Synthesis│
│Agents    │ │Filter Agents │ │Agents  │ │Agents   │
└──────────┘ └──────────────┘ └────────┘ └─────────┘
```

## Layer 1: Discovery Agents

### BiographyHunter Agent
```python
class BiographyHunterAgent:
    def __init__(self, player_name, time_period=(1935, 1955)):
        self.player = player_name
        self.period = time_period
        self.thesis_keywords = [
            "industrial", "financial", "aerospace", "atomic",
            "China", "limited war", "surveillance", "CIA"
        ]
    
    async def search_all_sources(self):
        """Cast wide net across all platforms"""
        tasks = [
            self.search_internet_archive(),
            self.search_google_books(),
            self.search_hathitrust(),
            self.search_jstor()
        ]
        results = await asyncio.gather(*tasks)
        return self.deduplicate(results)
    
    def score_relevance(self, result):
        """Initial relevance scoring"""
        score = 0
        # Time period overlap
        if overlaps_period(result['date'], self.period):
            score += 10
        # Thesis keywords in description
        for keyword in self.thesis_keywords:
            if keyword in result.get('description', '').lower():
                score += 5
        # Primary source vs secondary
        if result['type'] == 'primary':
            score += 15
        return score
```

### CrossroadsDetector Agent
```python
class CrossroadsDetectorAgent:
    """Finds moments where key players intersected"""
    
    def __init__(self):
        self.crossroads_patterns = [
            r"(MacArthur|Marshall).*(disagreed|opposed|conflicted)",
            r"(Truman|MacArthur).*(fired|dismissed|relieved)",
            r"(China|Chiang|Mao).*(policy|decision|debate)",
            r"(atomic|nuclear).*(decision|deployment|strategy)"
        ]
        
    def identify_crossroads(self, text):
        crossroads = []
        for pattern in self.crossroads_patterns:
            if match := re.search(pattern, text, re.IGNORECASE):
                context = self.extract_context(text, match.span(), window=500)
                date = self.extract_date(context)
                players = self.extract_players(context)
                crossroads.append({
                    'pattern': pattern,
                    'context': context,
                    'date': date,
                    'players': players,
                    'importance': self.score_importance(context)
                })
        return crossroads
```

## Layer 2: Relevance Filter Agents

### ThesisAlignmentAgent
```python
class ThesisAlignmentAgent:
    """Determines if content supports/challenges our thesis"""
    
    def __init__(self):
        self.thesis_themes = {
            'industrial_decline': [
                'deindustrialization', 'manufacturing', 'rust belt',
                'production', 'factories', 'steel'
            ],
            'financial_dominance': [
                'bretton woods', 'dollar', 'IMF', 'world bank',
                'currency', 'financial'
            ],
            'aerospace_supremacy': [
                'air force', 'strategic air', 'missiles', 'space',
                'aviation', 'aerospace'
            ],
            'china_loss': [
                'china', 'chiang', 'mao', 'communist china',
                'formosa', 'taiwan'
            ],
            'surveillance_state': [
                'FBI', 'CIA', 'NSA', 'surveillance', 'intelligence',
                'classification', 'secrecy'
            ]
        }
    
    def analyze_relevance(self, document):
        """Deep relevance analysis using Claude"""
        prompt = f"""
        Analyze this document excerpt for relevance to the thesis that 
        US decisions 1935-1955 created an "Aerospace Republic" that 
        sacrificed industrial strength for aerospace/financial dominance.
        
        Document: {document[:3000]}
        
        Score 0-100 for:
        1. Direct relevance to thesis
        2. Contains key decision point
        3. Shows alternative path not taken
        4. Reveals contradiction/tension
        
        Return: {{"relevance": score, "reason": "explanation", "key_quote": "..."}}
        """
        
        # This would call Claude API or local LLM
        return self.llm_analyze(prompt)
```

### OppositionVoiceAgent
```python
class OppositionVoiceAgent:
    """Specifically seeks dissenting views from the period"""
    
    def find_contemporary_criticism(self, decision, date):
        """Find what critics said AT THE TIME"""
        search_queries = [
            f'"{decision}" criticism {date}',
            f'"{decision}" opposition {date}',
            f'"{decision}" "warned against" {date}',
            f'"{decision}" mistake {date}'
        ]
        
        critics = []
        for query in search_queries:
            results = self.search_period_sources(query, date)
            for result in results:
                if self.is_contemporary_criticism(result, date):
                    critics.append({
                        'critic': self.extract_critic_name(result),
                        'criticism': self.extract_criticism(result),
                        'date': result['date'],
                        'source': result['source'],
                        'proved_correct': self.check_vindication(result)
                    })
        return critics
```

## Layer 3: Extraction Agents

### QuoteExtractorAgent
```python
class QuoteExtractorAgent:
    """Extracts powerful quotes that support/challenge thesis"""
    
    def __init__(self):
        self.quote_patterns = [
            r'"([^"]{50,500})"',  # Direct quotes
            r"said,?\s*['\"]([^'\"]{50,500})['\"]",
            r"wrote:?\s*['\"]([^'\"]{50,500})['\"]"
        ]
        
    def extract_quotes(self, text, player_name):
        quotes = []
        # Find direct quotes
        for pattern in self.quote_patterns:
            for match in re.finditer(pattern, text):
                quote_text = match.group(1)
                attribution = self.find_attribution(text, match.span())
                
                if self.is_relevant_quote(quote_text):
                    quotes.append({
                        'text': quote_text,
                        'speaker': attribution or player_name,
                        'context': self.extract_context(text, match.span()),
                        'date': self.extract_date_near(text, match.span()),
                        'significance': self.rate_significance(quote_text)
                    })
        
        return sorted(quotes, key=lambda x: x['significance'], reverse=True)
```

### MetadataExtractorAgent
```python
class MetadataExtractorAgent:
    """Extracts structured metadata from documents"""
    
    def extract_document_metadata(self, document):
        return {
            'people': self.extract_people(document),
            'dates': self.extract_dates(document),
            'places': self.extract_places(document),
            'organizations': self.extract_organizations(document),
            'decisions': self.extract_decisions(document),
            'relationships': self.extract_relationships(document)
        }
    
    def extract_relationships(self, text):
        """Who allied with whom, who opposed whom"""
        relationships = []
        patterns = [
            r"(\w+)\s+(?:allied with|supported|backed)\s+(\w+)",
            r"(\w+)\s+(?:opposed|fought|disagreed with)\s+(\w+)",
            r"(\w+)\s+(?:fired|dismissed|relieved)\s+(\w+)"
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                relationships.append({
                    'person1': match.group(1),
                    'person2': match.group(2),
                    'type': self.classify_relationship(match.group(0)),
                    'context': self.extract_context(text, match.span())
                })
        
        return relationships
```

## Layer 4: Synthesis Agents

### NarrativeBuilderAgent
```python
class NarrativeBuilderAgent:
    """Builds coherent narrative from extracted pieces"""
    
    def build_player_narrative(self, player_name, all_extracts):
        """Create biographical narrative focused on thesis"""
        
        timeline = self.build_timeline(all_extracts)
        key_decisions = self.identify_key_decisions(all_extracts)
        relationships = self.map_relationships(all_extracts)
        alternative_paths = self.find_alternatives(all_extracts)
        
        narrative = {
            'player': player_name,
            'thesis_role': self.determine_role(all_extracts),
            'timeline': timeline,
            'key_decisions': key_decisions,
            'relationships': relationships,
            'alternatives_not_taken': alternative_paths,
            'supporting_quotes': self.select_best_quotes(all_extracts),
            'contradictions': self.find_contradictions(all_extracts),
            'contemporary_criticism': self.gather_criticism(all_extracts)
        }
        
        return narrative
```

### ContradictionFinderAgent
```python
class ContradictionFinderAgent:
    """Finds contradictions between stated goals and actual outcomes"""
    
    def find_contradictions(self, player_data):
        contradictions = []
        
        # Stated goals vs actions
        for statement in player_data['public_statements']:
            for action in player_data['actions']:
                if self.contradicts(statement, action):
                    contradictions.append({
                        'stated': statement,
                        'actual': action,
                        'date_stated': statement['date'],
                        'date_acted': action['date'],
                        'significance': self.rate_contradiction(statement, action)
                    })
        
        return contradictions
```

## Orchestration Layer

### ResearchDirectorAgent
```python
class ResearchDirectorAgent:
    """Coordinates all other agents"""
    
    def __init__(self):
        self.discovery_agents = []
        self.filter_agents = []
        self.extractor_agents = []
        self.synthesis_agents = []
        
    async def research_player(self, player_name):
        """Complete research pipeline for one player"""
        
        # Phase 1: Discovery
        print(f"Discovering sources for {player_name}...")
        raw_sources = await self.discover_sources(player_name)
        
        # Phase 2: Filter
        print(f"Filtering {len(raw_sources)} sources...")
        relevant_sources = await self.filter_relevant(raw_sources)
        
        # Phase 3: Extract
        print(f"Extracting from {len(relevant_sources)} sources...")
        extracts = await self.extract_all(relevant_sources)
        
        # Phase 4: Synthesize
        print(f"Building narrative...")
        narrative = await self.synthesize_narrative(player_name, extracts)
        
        # Phase 5: Quality check
        narrative = await self.verify_claims(narrative)
        
        return narrative
        
    async def verify_claims(self, narrative):
        """Fact-check extracted claims against multiple sources"""
        for claim in narrative['key_claims']:
            claim['verification'] = await self.verify_claim(claim)
        return narrative
```

## Implementation Strategy

### Phase 1: Manual Prototype (Week 1)
- Test each agent type manually with 2-3 documents
- Refine relevance criteria
- Build initial prompts

### Phase 2: Semi-Automated (Week 2-3)
```python
# Start with simple rule-based agents
extractor = QuoteExtractorAgent()
filter_agent = ThesisAlignmentAgent()

for document in documents[:10]:
    if filter_agent.is_relevant(document):
        quotes = extractor.extract_quotes(document)
        save_to_dataset(quotes)
```

### Phase 3: LLM Integration (Week 4)
```python
# Add Claude for complex analysis
class ClaudeAnalysisAgent:
    def analyze_document(self, document, player, thesis):
        response = claude.complete(
            prompt=self.build_analysis_prompt(document, player, thesis),
            max_tokens=1000
        )
        return self.parse_analysis(response)
```

### Phase 4: Full Pipeline (Week 5-6)
- Connect all agents
- Add monitoring and logging
- Build feedback loops

## Storage Schema for Agent Output

```json
{
  "player": "Douglas MacArthur",
  "document_id": "doc_12345",
  "source": "American Caesar, p. 245",
  "agent_extracts": {
    "relevance_score": 85,
    "thesis_alignment": "challenges_financial_priority",
    "key_quotes": [
      {
        "text": "The decision to prioritize Europe...",
        "significance": "high",
        "date": "1944-03-15"
      }
    ],
    "relationships": [
      {
        "with": "Marshall",
        "type": "opposition",
        "issue": "Pacific strategy"
      }
    ],
    "crossroads": {
      "description": "MacArthur-Marshall Pacific debate",
      "date": "1944-03",
      "outcome": "Europe-first confirmed",
      "alternative": "Pacific priority would have..."
    }
  },
  "extraction_metadata": {
    "agent": "ThesisAlignmentAgent v1.2",
    "timestamp": "2024-01-15T10:30:00Z",
    "confidence": 0.92
  }
}
```

## Metrics & Monitoring

```python
class AgentMonitor:
    def track_performance(self):
        metrics = {
            'documents_processed': 1250,
            'relevant_found': 89,
            'quotes_extracted': 342,
            'crossroads_identified': 23,
            'false_positives': 12,
            'processing_time': '4h 23m',
            'cost': {
                'api_calls': 450,
                'llm_tokens': 1_250_000,
                'storage_gb': 2.3
            }
        }
        return metrics
```

## Cost Optimization

### Tiered Processing
1. **Cheap filters first**: Regex, keywords
2. **Mid-tier**: Local LLMs (Llama, Mistral)
3. **Expensive last**: Claude/GPT-4 only for complex analysis

### Caching Strategy
- Cache all LLM responses
- Reuse extracts across agents
- Store intermediate results

## Next Steps

1. **Build prototype** of QuoteExtractor and ThesisAlignment agents
2. **Test on 3 documents** about MacArthur-Marshall conflict
3. **Measure precision/recall** of relevance filtering
4. **Iterate prompts** based on results
5. **Scale to full pipeline** once accuracy > 80%