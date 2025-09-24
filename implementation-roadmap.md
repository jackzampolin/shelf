# Implementation Roadmap: From Zero to Research Pipeline

## Week 1: Foundation & First Sources

### Day 1-2: Access Setup
**Morning:**
- [ ] Create Internet Archive account with borrowing enabled
- [ ] Sign up for Scribd free trial
- [ ] Apply for state library card (for ProQuest access)
- [ ] Set up project repository with basic structure

**Afternoon:**
```bash
# Initialize project
mkdir aerospace-republic && cd aerospace-republic
git init
python -m venv venv
source venv/activate

# Install core dependencies
pip install internetarchive requests beautifulsoup4 
pip install pandas jsonschema pyyaml
pip install spacy && python -m spacy download en_core_web_sm
```

### Day 3-4: First Biography Test
**Target: MacArthur's "American Caesar" on Scribd**

```python
# scripts/test_extraction.py
import json
from pathlib import Path

# Manual test: Copy 3 chapters about 1944-1945
test_text = """[Paste chapter about MacArthur-Marshall debate]"""

# Test basic extraction
def extract_quotes(text):
    quotes = []
    # Find quoted speech
    import re
    pattern = r'"([^"]{50,500})"'
    for match in re.finditer(pattern, text):
        quotes.append({
            'text': match.group(1),
            'position': match.span()
        })
    return quotes

quotes = extract_quotes(test_text)
print(f"Found {len(quotes)} quotes")

# Save for analysis
Path("test_output").mkdir(exist_ok=True)
with open("test_output/macarthur_quotes.json", "w") as f:
    json.dump(quotes, f, indent=2)
```

### Day 5: Validate Key Players List
**Review and finalize top 10 players:**
- [ ] Confirm biography availability for each
- [ ] Check primary source collections
- [ ] Note which need purchase vs. borrow

## Week 2: Agent Prototypes

### Day 6-7: Build First Agent
**Start with QuoteExtractor - it's concrete and testable**

```python
# agents/extractors/quote_extractor.py
class QuoteExtractor:
    def __init__(self):
        self.min_length = 50
        self.max_length = 500
        
    def extract(self, text, context_window=200):
        """Extract quotes with surrounding context"""
        quotes = []
        
        # Multiple patterns for different quote styles
        patterns = [
            r'"([^"]+)"',  # Double quotes
            r"'([^']+)'",  # Single quotes  
            r'[""]([^""]+)[""]',  # Smart quotes
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                quote_text = match.group(1)
                
                # Apply length filter
                if self.min_length <= len(quote_text) <= self.max_length:
                    # Get context
                    start = max(0, match.start() - context_window)
                    end = min(len(text), match.end() + context_window)
                    context = text[start:end]
                    
                    quotes.append({
                        'text': quote_text,
                        'context': context,
                        'attribution': self.find_speaker(text, match.start())
                    })
        
        return quotes
    
    def find_speaker(self, text, quote_position):
        """Look backwards for attribution"""
        # Get previous 100 chars
        start = max(0, quote_position - 100)
        before_quote = text[start:quote_position]
        
        # Look for "X said", "X wrote", etc.
        attribution_patterns = [
            r'(\w+)\s+said',
            r'(\w+)\s+wrote',
            r'(\w+)\s+argued',
            r'according to\s+(\w+)',
        ]
        
        for pattern in attribution_patterns:
            if match := re.search(pattern, before_quote):
                return match.group(1)
        
        return "Unknown"
```

### Day 8-9: Build Relevance Filter
```python
# agents/filters/thesis_filter.py
class ThesisRelevanceFilter:
    def __init__(self):
        # Keywords that signal thesis relevance
        self.thesis_keywords = {
            'high_relevance': [
                'industrial base', 'manufacturing decline',
                'financial dominance', 'bretton woods',
                'china policy', 'lose china', 'chiang kai-shek',
                'limited war', 'total victory',
                'air power', 'strategic bombing'
            ],
            'medium_relevance': [
                'soviet', 'communism', 'cold war',
                'marshall plan', 'nato', 'pentagon'
            ]
        }
    
    def score_relevance(self, text):
        """Score 0-100 based on keyword density"""
        text_lower = text.lower()
        score = 0
        
        # Check high relevance terms
        for term in self.thesis_keywords['high_relevance']:
            count = text_lower.count(term)
            score += count * 10
            
        # Check medium relevance  
        for term in self.thesis_keywords['medium_relevance']:
            count = text_lower.count(term)
            score += count * 5
            
        # Cap at 100
        return min(100, score)
```

### Day 10: First Integration Test
```python
# scripts/test_pipeline.py
def test_pipeline():
    # Load test document
    with open("test_docs/macarthur_chapter.txt") as f:
        text = f.read()
    
    # Run agents
    extractor = QuoteExtractor()
    filter = ThesisRelevanceFilter()
    
    # Check relevance first
    relevance = filter.score_relevance(text)
    print(f"Relevance score: {relevance}")
    
    if relevance > 50:
        quotes = extractor.extract(text)
        print(f"Extracted {len(quotes)} quotes")
        
        # Save results
        output = {
            'source': 'macarthur_chapter.txt',
            'relevance': relevance,
            'quotes': quotes
        }
        
        with open("test_output/pipeline_test.json", "w") as f:
            json.dump(output, f, indent=2)
```

## Week 3: Scale to Multiple Sources

### Day 11-13: Internet Archive Integration
```python
# agents/discovery/ia_searcher.py
import internetarchive as ia
from typing import List, Dict
import time

class InternetArchiveSearcher:
    def __init__(self, player_name: str, year_range: tuple):
        self.player = player_name
        self.years = year_range
        
    def search(self) -> List[Dict]:
        """Search IA for relevant documents"""
        results = []
        
        # Build search queries
        queries = [
            f'"{self.player}" AND year:[{self.years[0]} TO {self.years[1]}]',
            f'subject:"{self.player}" AND mediatype:texts',
            f'creator:"{self.player}" AND mediatype:texts'
        ]
        
        for query in queries:
            print(f"Searching: {query}")
            search_results = ia.search_items(query)
            
            for item in search_results:
                # Get metadata
                metadata = ia.get_item(item['identifier'])
                
                # Check if relevant
                if self.is_relevant(metadata):
                    results.append({
                        'identifier': item['identifier'],
                        'title': metadata.metadata.get('title'),
                        'date': metadata.metadata.get('date'),
                        'type': 'internet_archive',
                        'url': f"https://archive.org/details/{item['identifier']}"
                    })
                
                time.sleep(1)  # Be nice to IA
                
        return results
    
    def download_text(self, identifier: str) -> str:
        """Download text content from IA item"""
        item = ia.get_item(identifier)
        
        # Try different text formats
        for format in ['DjVuTXT', 'Text', 'Plain Text']:
            files = [f for f in item.files if f['format'] == format]
            if files:
                # Download first text file
                text_file = files[0]['name']
                item.download(files=[text_file])
                
                # Read and return
                with open(text_file, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
        
        return None
```

### Day 14-15: Add LLM Analysis
```python
# agents/analysis/llm_analyzer.py
import os
from anthropic import Anthropic

class LLMAnalyzer:
    def __init__(self):
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        
    def analyze_relevance(self, text: str, player: str) -> dict:
        """Use Claude to deeply analyze relevance"""
        
        prompt = f"""
        Analyze this historical text about {player} for relevance to the thesis
        that US decisions between 1935-1955 created an "Aerospace Republic" that
        sacrificed industrial strength for aerospace and financial dominance.
        
        Text excerpt (first 2000 chars):
        {text[:2000]}
        
        Return a JSON object with:
        1. relevance_score (0-100)
        2. key_theme (industrial_decline/financial_dominance/china_loss/surveillance_state/other)
        3. supports_thesis (true/false)
        4. key_evidence (brief description)
        5. suggested_action (keep/skip/needs_deeper_analysis)
        """
        
        response = self.client.messages.create(
            model="claude-3-sonnet-20241022",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Parse response
        import json
        try:
            return json.loads(response.content[0].text)
        except:
            return {"error": "Failed to parse", "raw": response.content[0].text}
```

## Week 4: Build Full Pipeline

### Day 16-18: Orchestrator
```python
# agents/orchestrator.py
class ResearchOrchestrator:
    def __init__(self, player_name: str):
        self.player = player_name
        self.base_dir = Path(f"players/{player_name}")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize agents
        self.searcher = InternetArchiveSearcher(player_name, (1935, 1955))
        self.extractor = QuoteExtractor()
        self.filter = ThesisRelevanceFilter()
        self.analyzer = LLMAnalyzer()
        
    def run_complete_pipeline(self):
        """Execute full research pipeline"""
        
        print(f"=== Starting research for {self.player} ===")
        
        # Step 1: Discovery
        print("Step 1: Discovering sources...")
        sources = self.searcher.search()
        print(f"Found {len(sources)} potential sources")
        
        # Save source list
        with open(self.base_dir / "sources.json", "w") as f:
            json.dump(sources, f, indent=2)
        
        # Step 2: Process each source
        for source in sources[:5]:  # Start with first 5
            print(f"\nProcessing: {source['title']}")
            
            # Download text
            text = self.searcher.download_text(source['identifier'])
            if not text:
                print("  - No text available")
                continue
                
            # Check relevance
            relevance = self.filter.score_relevance(text)
            print(f"  - Relevance: {relevance}")
            
            if relevance < 30:
                print("  - Skipping (low relevance)")
                continue
                
            # Deep analysis with LLM
            analysis = self.analyzer.analyze_relevance(text, self.player)
            print(f"  - LLM Analysis: {analysis.get('suggested_action')}")
            
            if analysis.get('suggested_action') == 'skip':
                continue
                
            # Extract quotes
            quotes = self.extractor.extract(text)
            print(f"  - Extracted {len(quotes)} quotes")
            
            # Save results
            output = {
                'source': source,
                'relevance_score': relevance,
                'llm_analysis': analysis,
                'quotes': quotes[:20]  # Top 20 quotes
            }
            
            filename = f"{source['identifier']}_analysis.json"
            with open(self.base_dir / "extracts" / filename, "w") as f:
                json.dump(output, f, indent=2)
                
        print(f"\n=== Completed research for {self.player} ===")
```

### Day 19-20: Test on Three Players
```bash
# Run for top 3 players
python -c "
from agents.orchestrator import ResearchOrchestrator

for player in ['Douglas MacArthur', 'George Marshall', 'Dean Acheson']:
    orchestrator = ResearchOrchestrator(player)
    orchestrator.run_complete_pipeline()
"
```

## Week 5: Refinement & Optimization

### Day 21-23: Add Caching
```python
# agents/cache.py
import hashlib
import pickle
from pathlib import Path

class AgentCache:
    def __init__(self, cache_dir="cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
    def get_cache_key(self, agent_name: str, input_data: str) -> str:
        """Generate cache key from agent and input"""
        content = f"{agent_name}:{input_data[:1000]}"
        return hashlib.md5(content.encode()).hexdigest()
        
    def get(self, agent_name: str, input_data: str):
        """Retrieve cached result"""
        key = self.get_cache_key(agent_name, input_data)
        cache_file = self.cache_dir / f"{key}.pkl"
        
        if cache_file.exists():
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        return None
        
    def set(self, agent_name: str, input_data: str, result):
        """Cache result"""
        key = self.get_cache_key(agent_name, input_data)
        cache_file = self.cache_dir / f"{key}.pkl"
        
        with open(cache_file, 'wb') as f:
            pickle.dump(result, f)
```

### Day 24-25: Build Status Dashboard
```python
# scripts/dashboard.py
def generate_dashboard():
    """Generate research status dashboard"""
    
    players_dir = Path("players")
    stats = {}
    
    for player_dir in players_dir.iterdir():
        if player_dir.is_dir():
            player_name = player_dir.name
            
            # Count files
            sources = len(list(player_dir.glob("sources/*.json")))
            extracts = len(list(player_dir.glob("extracts/*.json")))
            quotes = 0
            
            # Count quotes
            for extract_file in player_dir.glob("extracts/*.json"):
                with open(extract_file) as f:
                    data = json.load(f)
                    quotes += len(data.get('quotes', []))
            
            stats[player_name] = {
                'sources': sources,
                'extracts': extracts,
                'quotes': quotes,
                'status': 'complete' if extracts > 10 else 'in_progress'
            }
    
    # Generate HTML dashboard
    html = "<html><body><h1>Research Dashboard</h1><table>"
    html += "<tr><th>Player</th><th>Sources</th><th>Extracts</th><th>Quotes</th><th>Status</th></tr>"
    
    for player, data in stats.items():
        html += f"<tr><td>{player}</td><td>{data['sources']}</td>"
        html += f"<td>{data['extracts']}</td><td>{data['quotes']}</td>"
        html += f"<td>{data['status']}</td></tr>"
    
    html += "</table></body></html>"
    
    with open("dashboard.html", "w") as f:
        f.write(html)
    
    print("Dashboard generated: dashboard.html")
```

## Week 6: Production Ready

### Deploy Checklist
- [ ] All agents tested with 80%+ accuracy
- [ ] Caching reduces API calls by 50%+
- [ ] Error handling for all API failures
- [ ] Logging system in place
- [ ] Cost tracking implemented
- [ ] Backup system for extracted data
- [ ] Documentation complete

### Final Script
```python
# run_research.py
import argparse
from agents.orchestrator import ResearchOrchestrator

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--player', required=True)
    parser.add_argument('--sources', default=10, type=int)
    parser.add_argument('--use-cache', action='store_true')
    
    args = parser.parse_args()
    
    orchestrator = ResearchOrchestrator(
        player_name=args.player,
        max_sources=args.sources,
        use_cache=args.use_cache
    )
    
    orchestrator.run_complete_pipeline()
    
if __name__ == "__main__":
    main()
```

## Cost Projections

### Minimal Setup (Month 1)
- Scribd: $12
- Used books: $50
- API costs: $20
- **Total: $82**

### Full Research (Months 2-3)
- Scribd + JSTOR: $40/month
- Book purchases: $100
- API costs: $50/month
- **Total: $190/month**

### Complete Project (6 months)
- All sources: ~$1000
- Compute/API: ~$300
- Books: ~$500
- **Total: $1800**

## Success Metrics

Week 1: 
- [ ] 3 biographies accessed
- [ ] 100 quotes extracted

Week 2:
- [ ] First agent working
- [ ] 500 quotes extracted

Week 4:
- [ ] 3 players researched
- [ ] 2000 quotes extracted

Week 6:
- [ ] 10 players researched
- [ ] 5000 quotes extracted
- [ ] First narrative complete

## Ready to Start?

1. **Today**: Set up Internet Archive and Scribd accounts
2. **Tomorrow**: Download first MacArthur biography
3. **This Week**: Build QuoteExtractor agent
4. **Next Week**: Run first full pipeline
5. **Month 1**: Complete research for top 5 players