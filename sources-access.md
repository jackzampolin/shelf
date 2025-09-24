# Sources Access Strategy: Getting Full Text Biographies & Documents

## The Access Challenge
Most quality biographies from university presses and major publishers are NOT freely available. We need a multi-pronged strategy combining free, institutional, and paid access.

## Tier 1: Free Full-Text Sources

### Internet Archive (archive.org)
**What's Actually Available**:
- Pre-1929 biographies (public domain)
- Some 1960s-1980s biographies via Controlled Digital Lending
- Government documents and reports
- Contemporary magazines (Time, Life, etc.)

**Access Method**:
```python
# Use their borrowing system for copyrighted works
import internetarchive as ia
ia.configure('YOUR_EMAIL', 'YOUR_PASSWORD')
item = ia.get_item('americancaesardo00manc')  # Manchester's MacArthur
item.borrow()  # 14-day loan
item.download(formats=['pdf', 'epub'])
```

**Limitations**: 1-hour or 14-day loans, one user at a time

### HathiTrust
**What's Available**:
- 17+ million volumes
- Full view for pre-1929
- Search-only for copyrighted works (unless you have institutional access)

**How to Get Full Access**:
1. **Alumni Access**: Many universities offer alumni library cards ($50-200/year)
   - University of Michigan
   - UC Berkeley  
   - Indiana University
2. **Community Borrowing**: Some universities allow local residents
3. **Emergency Temporary Access** (if still active)

### Google Books
**Reality Check**:
- Preview limited to 20% of most books
- No API access to full text even if viewable
- Useful for verification and citations, not reading

**Workaround**:
```python
# Build full text from multiple searches
def extract_maximum_content(book_id):
    search_terms = extract_key_terms_from_toc(book_id)
    snippets = []
    for term in search_terms:
        result = search_inside_book(book_id, term)
        snippets.extend(result['snippets'])
    return deduplicate_and_order(snippets)
```

## Tier 2: Institutional Access Required

### JSTOR
**Cost**: $200/year individual or institutional access required
**What You Get**:
- Full text academic books
- Historical journals and newspapers
- Primary sources from 1935-1955

**Best Option**: Register as an independent researcher
- 100 article downloads/month
- Book chapter access
- MyJSTOR workspace for annotations

### ProQuest (includes many biographies)
**Access Options**:
1. Public library cards often include ProQuest
2. State library cards (many states offer free cards to residents)
3. Alumni access through university

### Project MUSE
**What's There**: University press books, including key biographies
**Access**: Usually requires institutional access
**Alternative**: Individual subscriptions to specific publishers

## Tier 3: Paid Services Worth Considering

### Scribd ($11.99/month)
**Surprisingly Good For**:
- Popular biographies (Manchester, Brands, etc.)
- Unlimited reading
- Download for offline

**What's Actually There** (verified):
- American Caesar (MacArthur)
- Truman (McCullough)
- Eisenhower biographies
- The Wise Men (Acheson & friends)

### Kindle Unlimited ($9.99/month)
**Limited But Includes**:
- Older biographies
- Self-published compilations of primary sources
- Some university press backlist

### Direct Purchase Strategy
**When to Buy**:
- Core Tier 1 biographies not available elsewhere
- Recent definitive biographies (post-2000)
- Estimate: $300-500 for 15-20 essential books

**Where to Buy**:
- Used books via AbeBooks/ThriftBooks: $5-15 per book
- Kindle editions during sales: $2-10
- University press sales: 40-50% off

## Tier 4: Primary Sources

### Free Government Documents

**FRUS (Foreign Relations of the United States)**
- URL: history.state.gov
- Complete 1935-1955 available free
- Full text, searchable

**Truman Library**
- trumanlibrary.gov
- Digitized papers, oral histories
- Free API access

**FDR Library**
- fdrlibrary.org
- Extensive digital collections
- Map Room papers, correspondence

**National Archives**
- catalog.archives.gov
- Military records (some digitized)
- Presidential materials

### Congressional Hearings
**ProQuest Congressional** (needs institutional access)
**Alternative**: 
- HathiTrust has many pre-1960 hearings
- Archive.org has MacArthur hearings, China testimony

## Recommended Access Stack

### Minimum Viable Access ($50/month)
1. **Scribd**: $12/month - commercial biographies
2. **JSTOR Independent**: $20/month - academic sources  
3. **State Library Card**: Free - ProQuest, newspaper archives
4. **Internet Archive**: Free - borrowing system
5. **Used Book Purchases**: $20/month budget

### Optimal Access ($150/month)
- Everything above PLUS:
- University alumni access: $100-200/year
- Newspapers.com: $30/month
- Direct book purchases: $50/month

## The Aggregation Strategy

```python
class SourceAggregator:
    def __init__(self):
        self.sources = {
            'free': [InternetArchive(), GoogleBooks(), FRUS()],
            'library': [HathiTrust(), ProQuest()],
            'paid': [Scribd(), JSTOR(), KindleUnlimited()],
            'purchase': [AbeBooks(), ThriftBooks()]
        }
    
    def find_biography(self, person, title):
        """Try sources in cost order"""
        results = {}
        
        # Try free first
        for source in self.sources['free']:
            if result := source.search(person, title):
                results[source.name] = result
                
        # Check if we have full text
        if not has_full_text(results):
            # Try library/institutional
            for source in self.sources['library']:
                if self.has_access(source):
                    results[source.name] = source.search(person, title)
                    
        # Last resort - paid
        if not has_full_text(results):
            purchase_price = self.sources['purchase'].get_lowest_price(title)
            results['purchase_option'] = purchase_price
            
        return results
```

## Quick Wins: Immediately Available Full Texts

### On Internet Archive NOW:
- *Years of Decision* by Truman (memoir)
- *Crusade in Europe* by Eisenhower
- *Present at the Creation* by Acheson (1969 edition)
- *The Forrestal Diaries* edited by Millis
- Contemporary magazines 1935-1955

### On HathiTrust (full view):
- Many pre-1929 biographies of earlier lives
- Government reports and hearings
- Military histories from 1950s-60s

### Via Scribd (verified available):
- Manchester's *American Caesar*
- Brands' *The General vs. The President*
- McCullough's *Truman*
- Ambrose's Eisenhower biographies

## Action Plan

1. **Week 1**: Set up free accounts
   - Internet Archive (with borrowing)
   - HathiTrust (basic search)
   - FRUS account
   - Apply for state library card

2. **Week 2**: Test paid services
   - Scribd free trial
   - JSTOR independent researcher
   - Check alumni access options

3. **Week 3**: Create source matrix
   - Map each biography to best source
   - Identify gaps requiring purchase
   - Build automated checking system

4. **Ongoing**: Budget $50-100/month for:
   - One streaming service (Scribd/JSTOR)
   - Strategic book purchases
   - Document delivery services

## The Reality

**You'll likely need**:
- 2-3 paid services
- Strategic purchases of 10-15 books
- Institutional access through alumni or library
- Total cost: $500-1000 for complete access to all key biographies

**But you can start with**:
- Internet Archive borrowing
- Scribd trial
- Strategic purchases of 3-4 essential biographies
- Cost: <$50 to begin meaningful research