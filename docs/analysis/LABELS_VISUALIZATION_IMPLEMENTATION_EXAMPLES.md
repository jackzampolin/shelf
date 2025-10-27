# Labels Stage Visualization - Implementation Examples

## Quick Implementation Guide

This document provides concrete code examples for implementing each visualization.

---

## 1. Stat Cards (HTML + Python Backend)

### Backend (Python)
```python
# In shelf_viewer.py or similar

@app.route('/stats/labels/<scan_id>')
def labels_stats(scan_id):
    """Get stats for labels stage."""
    book_dir = Path(LIBRARY_ROOT) / scan_id
    report_path = book_dir / 'labels' / 'report.csv'
    
    if not report_path.exists():
        return {'error': 'No report found'}, 404
    
    df = pd.read_csv(report_path)
    
    stats = {
        'total_pages': len(df),
        'avg_confidence': float(df['avg_classification_confidence'].mean()),
        'pages_with_numbers': int(df['page_number_extracted'].sum()),
        'chapter_headings': int(df['has_chapter_heading'].sum()),
        'section_headings': int(df['has_section_heading'].sum()),
        'front_matter': int((df['page_region'] == 'front_matter').sum()),
        'body': int((df['page_region'] == 'body').sum()),
        'back_matter': int((df['page_region'] == 'back_matter').sum()),
        'total_cost': float(df.get('processing_cost', [0]).sum()) if 'processing_cost' in df.columns else 0.0,
    }
    
    return stats

# In Flask route
@app.route('/labels/<scan_id>')
def labels_viewer(scan_id):
    stats = get('/stats/labels/<scan_id>')  # Call above endpoint
    return render_template('labels/viewer.html', scan_id=scan_id, stats=stats)
```

### Frontend (HTML/JavaScript)
```html
<div class="stat-cards">
    <div class="stat-card">
        <div class="stat-label">Pages Processed</div>
        <div class="stat-value">{{ stats.total_pages }}/{{ stats.total_pages }}</div>
        <div class="stat-percent">100%</div>
    </div>
    
    <div class="stat-card">
        <div class="stat-label">Avg Confidence</div>
        <div class="stat-value">{{ "%.3f"|format(stats.avg_confidence) }}</div>
        <div class="stat-color" style="background: {% if stats.avg_confidence > 0.90 %}green{% elif stats.avg_confidence > 0.80 %}orange{% else %}red{% endif %}"></div>
    </div>
    
    <div class="stat-card">
        <div class="stat-label">Page Numbers Extracted</div>
        <div class="stat-value">{{ stats.pages_with_numbers }}/{{ stats.total_pages }}</div>
        <div class="stat-percent">{{ (100 * stats.pages_with_numbers / stats.total_pages)|round(1) }}%</div>
    </div>
    
    <div class="stat-card">
        <div class="stat-label">Chapter Headings</div>
        <div class="stat-value">{{ stats.chapter_headings }}</div>
    </div>
    
    <div class="stat-card">
        <div class="stat-label">Region Distribution</div>
        <div class="stat-value">F: {{ stats.front_matter }} | B: {{ stats.body }} | K: {{ stats.back_matter }}</div>
    </div>
</div>

<style>
.stat-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 15px;
    margin-bottom: 30px;
}

.stat-card {
    background: white;
    border: 1px solid #ddd;
    border-radius: 6px;
    padding: 15px;
    text-align: center;
}

.stat-label {
    color: #666;
    font-size: 12px;
    text-transform: uppercase;
    margin-bottom: 8px;
}

.stat-value {
    font-size: 24px;
    font-weight: bold;
    color: #333;
}

.stat-percent {
    font-size: 14px;
    color: #999;
    margin-top: 5px;
}

.stat-color {
    width: 30px;
    height: 6px;
    margin: 10px auto 0;
    border-radius: 3px;
}
</style>
```

---

## 2. Confidence Distribution Histogram

### Backend (Python - Chart Data)
```python
@app.route('/charts/labels/confidence/<scan_id>')
def labels_confidence_chart(scan_id):
    """Generate confidence distribution data for chart."""
    book_dir = Path(LIBRARY_ROOT) / scan_id
    report_path = book_dir / 'labels' / 'report.csv'
    
    df = pd.read_csv(report_path)
    
    # Create bins
    bins = [0, 0.80, 0.85, 0.90, 0.95, 1.0]
    labels = ['<0.80', '0.80-0.85', '0.85-0.90', '0.90-0.95', '0.95-1.0']
    
    hist, _ = np.histogram(df['avg_classification_confidence'], bins=bins)
    
    return {
        'labels': labels,
        'data': hist.tolist(),
        'total': len(df),
        'mean': float(df['avg_classification_confidence'].mean()),
        'median': float(df['avg_classification_confidence'].median()),
        'std': float(df['avg_classification_confidence'].std()),
    }
```

### Frontend (using Chart.js)
```html
<div class="chart-container">
    <h3>Block Classification Confidence Distribution</h3>
    <canvas id="confidence-chart"></canvas>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
fetch(`/charts/labels/confidence/{{ scan_id }}`)
    .then(r => r.json())
    .then(data => {
        const colors = ['#E74C3C', '#E67E22', '#F39C12', '#F1C40F', '#2ECC71'];
        const ctx = document.getElementById('confidence-chart').getContext('2d');
        
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.labels,
                datasets: [{
                    label: 'Pages',
                    data: data.data,
                    backgroundColor: colors,
                    borderColor: '#ccc',
                    borderWidth: 1
                }]
            },
            options: {
                indexAxis: 'y',
                scales: {
                    x: {
                        beginAtZero: true,
                        title: { display: true, text: 'Number of Pages' }
                    }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            afterLabel: function(ctx) {
                                const pct = (ctx.parsed.x / data.total * 100).toFixed(1);
                                return `${pct}% of pages`;
                            }
                        }
                    }
                }
            }
        });
        
        // Add stats below chart
        document.querySelector('.chart-stats').innerHTML = `
            <p>Mean: ${data.mean.toFixed(3)} | Median: ${data.median.toFixed(3)} | StdDev: ${data.std.toFixed(3)}</p>
            <p><strong>⚠ ${data.data[0]} pages have confidence &lt; 0.80 (review)</strong></p>
        `;
    });
</script>
```

---

## 3. Problem Pages Table (Sortable)

### Backend (Python)
```python
@app.route('/tables/labels/problems/<scan_id>')
def labels_problem_pages(scan_id):
    """Get list of pages needing review."""
    book_dir = Path(LIBRARY_ROOT) / scan_id
    report_path = book_dir / 'labels' / 'report.csv'
    
    df = pd.read_csv(report_path)
    
    # Flag problem pages
    problems = df[
        (df['avg_classification_confidence'] < 0.80) |
        (df['page_region_classified'] == False) |
        (df['total_blocks_classified'] < 2) |
        (df['total_blocks_classified'] > 20)
    ].copy()
    
    # Sort by severity (confidence)
    problems = problems.sort_values('avg_classification_confidence')
    
    # Add severity label
    def severity(row):
        if row['avg_classification_confidence'] < 0.75:
            return 'critical'
        elif row['avg_classification_confidence'] < 0.85:
            return 'warning'
        else:
            return 'info'
    
    problems['severity'] = problems.apply(severity, axis=1)
    
    return {
        'total_problems': len(problems),
        'problems': problems[[
            'page_num', 'page_region', 'avg_classification_confidence',
            'total_blocks_classified', 'severity'
        ]].to_dict('records')
    }
```

### Frontend (HTML Table)
```html
<div class="problems-section">
    <h3>Pages Requiring Review</h3>
    <table class="problems-table">
        <thead>
            <tr>
                <th onclick="sortTable(0)">Page</th>
                <th onclick="sortTable(1)">Region</th>
                <th onclick="sortTable(2)">Confidence</th>
                <th onclick="sortTable(3)">Blocks</th>
                <th onclick="sortTable(4)">Issue</th>
            </tr>
        </thead>
        <tbody id="problems-tbody">
        </tbody>
    </table>
</div>

<script>
fetch(`/tables/labels/problems/{{ scan_id }}`)
    .then(r => r.json())
    .then(data => {
        const tbody = document.getElementById('problems-tbody');
        
        data.problems.forEach(p => {
            const tr = document.createElement('tr');
            tr.className = `severity-${p.severity}`;
            
            const conf_color = p.avg_classification_confidence > 0.85 ? '🟢' :
                             p.avg_classification_confidence > 0.75 ? '🟠' : '🔴';
            
            tr.innerHTML = `
                <td><a href="/labels/{{ scan_id }}/${p.page_num}">${p.page_num}</a></td>
                <td>${p.page_region || '-'}</td>
                <td>${conf_color} ${p.avg_classification_confidence.toFixed(2)}</td>
                <td>${p.total_blocks_classified}</td>
                <td>${getIssueType(p)}</td>
            `;
            
            tbody.appendChild(tr);
        });
    });

function getIssueType(p) {
    if (p.avg_classification_confidence < 0.80) return 'Low confidence';
    if (p.total_blocks_classified < 2) return 'Sparse page';
    if (p.total_blocks_classified > 20) return 'Dense page';
    if (!p.page_region) return 'No region';
    return 'Check';
}
</script>

<style>
.problems-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 10px;
}

.problems-table th {
    background: #f5f5f5;
    padding: 10px;
    text-align: left;
    cursor: pointer;
    border-bottom: 2px solid #ddd;
}

.problems-table td {
    padding: 10px;
    border-bottom: 1px solid #eee;
}

.problems-table tr.severity-critical {
    background: rgba(231, 76, 60, 0.1);
}

.problems-table tr.severity-warning {
    background: rgba(230, 126, 34, 0.1);
}

.problems-table tr.severity-info {
    background: rgba(52, 152, 219, 0.1);
}

.problems-table a {
    color: #3498db;
    text-decoration: none;
}
</style>
```

---

## 4. Page Number Extraction Timeline

### Backend (Python)
```python
@app.route('/charts/labels/timeline/<scan_id>')
def labels_timeline(scan_id):
    """Generate page number extraction timeline."""
    book_dir = Path(LIBRARY_ROOT) / scan_id
    report_path = book_dir / 'labels' / 'report.csv'
    
    df = pd.read_csv(report_path).sort_values('page_num')
    
    # Prepare data for timeline
    timeline = {
        'pages': df['page_num'].tolist(),
        'extracted': df['page_number_extracted'].astype(int).tolist(),
        'numbering_styles': df['numbering_style'].tolist(),
        'printed_numbers': df['printed_page_number'].tolist(),
    }
    
    # Detect transitions (roman to arabic)
    styles = df['numbering_style'].dropna()
    transitions = []
    prev_style = None
    for idx, (page_num, style) in enumerate(zip(df['page_num'], df['numbering_style'])):
        if style != prev_style and prev_style is not None:
            transitions.append({
                'page': int(page_num),
                'from': prev_style,
                'to': style
            })
        if pd.notna(style):
            prev_style = style
    
    timeline['transitions'] = transitions
    
    return timeline
```

### Frontend (using Chart.js - Line Chart)
```html
<div class="timeline-container">
    <h3>Printed Page Number Extraction Timeline</h3>
    <canvas id="timeline-chart" style="max-height: 300px;"></canvas>
</div>

<script>
fetch(`/charts/labels/timeline/{{ scan_id }}`)
    .then(r => r.json())
    .then(data => {
        const ctx = document.getElementById('timeline-chart').getContext('2d');
        
        // Convert extracted to binary values for display
        const extractedValues = data.extracted.map((v, i) => 
            v ? 50 : null  // Only show 50 where extracted
        );
        
        new Chart(ctx, {
            type: 'scatter',
            data: {
                datasets: [{
                    label: 'Page Number Extracted',
                    data: data.pages.map((p, i) => ({
                        x: p,
                        y: data.extracted[i] ? 1 : 0
                    })),
                    backgroundColor: data.pages.map((p, i) => {
                        const style = data.numbering_styles[i];
                        if (style === 'roman') return '#9B59B6';
                        if (style === 'arabic') return '#3498DB';
                        return '#95A5A6';
                    }),
                    pointRadius: 4,
                }]
            },
            options: {
                scales: {
                    x: {
                        title: { display: true, text: 'PDF Page Number' }
                    },
                    y: {
                        beginAtZero: true,
                        max: 1.2,
                        title: { display: true, text: 'Extracted' },
                        ticks: { callback: v => v ? 'Yes' : 'No' }
                    }
                },
                plugins: {
                    legend: { display: false },
                    annotation: {
                        annotations: data.transitions.map(t => ({
                            type: 'line',
                            xMin: t.page,
                            xMax: t.page,
                            borderColor: '#E74C3C',
                            borderWidth: 2,
                            label: { content: [`${t.from} → ${t.to}`] }
                        }))
                    }
                }
            }
        });
    });
</script>
```

---

## 5. Chapter Boundary Detection

### Backend (Python)
```python
@app.route('/chapters/labels/<scan_id>')
def labels_chapters(scan_id):
    """Get detected chapter boundaries."""
    book_dir = Path(LIBRARY_ROOT) / scan_id
    report_path = book_dir / 'labels' / 'report.csv'
    
    df = pd.read_csv(report_path)
    
    # Get pages with chapter headings
    chapters = df[df['has_chapter_heading'] == True][[
        'page_num', 'printed_page_number', 'page_region'
    ]].to_dict('records')
    
    # Distribution by region
    regions = df['page_region'].value_counts().to_dict()
    chapter_regions = chapters.DataFrame(chapters)['page_region'].value_counts().to_dict()
    
    return {
        'total_chapters': len(chapters),
        'chapters': chapters,
        'region_distribution': {
            'front_matter': chapter_regions.get('front_matter', 0),
            'body': chapter_regions.get('body', 0),
            'back_matter': chapter_regions.get('back_matter', 0),
        },
        'readiness': {
            'has_chapters': len(chapters) > 20,
            'correct_region_distribution': chapter_regions.get('body', 0) > 20,
        }
    }
```

### Frontend (HTML)
```html
<div class="chapters-section">
    <h3>Chapter Boundary Detection</h3>
    
    <div class="chapter-stats">
        <p>Total chapter headings detected: <strong>{{ chapters_data.total_chapters }}</strong></p>
        <p>Distribution by region:</p>
        <ul>
            <li>Front Matter: {{ chapters_data.region_distribution.front_matter }}</li>
            <li>Body: {{ chapters_data.region_distribution.body }}</li>
            <li>Back Matter: {{ chapters_data.region_distribution.back_matter }}</li>
        </ul>
    </div>
    
    <table class="chapters-table">
        <thead>
            <tr>
                <th>#</th>
                <th>PDF Page</th>
                <th>Printed #</th>
                <th>Region</th>
            </tr>
        </thead>
        <tbody id="chapters-tbody">
        </tbody>
    </table>
    
    <div class="readiness-check">
        {% if chapters_data.readiness.has_chapters %}
        <p><strong>✓</strong> Sufficient chapters for structure extraction</p>
        {% else %}
        <p><strong>⚠</strong> Few chapters detected - structure extraction may struggle</p>
        {% endif %}
    </div>
</div>

<script>
// Populate chapters table
const chapters = {{ chapters_data.chapters | tojson }};
const tbody = document.getElementById('chapters-tbody');
chapters.forEach((ch, i) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
        <td>${i + 1}</td>
        <td><a href="/labels/{{ scan_id }}/${ch.page_num}">${ch.page_num}</a></td>
        <td>${ch.printed_page_number || '-'}</td>
        <td>${ch.page_region}</td>
    `;
    tbody.appendChild(tr);
});
</script>
```

---

## Full Dashboard Template

### HTML Structure
```html
{% extends "base.html" %}

{% block title %}Labels Viewer - {{ scan_id }}{% endblock %}

{% block content %}
<div class="page-header">
    <h2>{{ scan_id }} - Labels Stage</h2>
    <div class="breadcrumb">
        <a href="/">Home</a> > 
        <a href="/books">Books</a> > 
        <span>{{ scan_id }}</span>
    </div>
</div>

<!-- Stat Cards -->
<section class="quality-overview">
    <h3>Quality Overview</h3>
    {% include 'labels/stat_cards.html' %}
</section>

<!-- Visualizations -->
<section class="visualizations">
    <h3>Metrics & Distributions</h3>
    <div class="visualization-grid">
        <div class="chart">{% include 'labels/confidence_histogram.html' %}</div>
        <div class="chart">{% include 'labels/region_distribution.html' %}</div>
        <div class="chart">{% include 'labels/timeline.html' %}</div>
    </div>
</section>

<!-- Problem Pages -->
<section class="problems-review">
    <h3>Pages Requiring Review</h3>
    {% include 'labels/problem_pages_table.html' %}
</section>

<!-- Chapter Detection -->
<section class="chapter-detection">
    {% include 'labels/chapters.html' %}
</section>

{% endblock %}
```

---

## Key Implementation Patterns

### 1. Data Loading
```python
# Always check file exists first
if not report_path.exists():
    return {'error': 'No report found'}, 404

# Use pandas for easy filtering
df = pd.read_csv(report_path)
low_conf = df[df['avg_classification_confidence'] < 0.80]
```

### 2. Error Handling
```python
try:
    df = pd.read_csv(report_path)
    if len(df) == 0:
        return {'error': 'Report is empty'}, 400
except Exception as e:
    return {'error': str(e)}, 500
```

### 3. Color Coding
```javascript
function getConfidenceColor(conf) {
    if (conf >= 0.95) return '#2ECC71';  // Green
    if (conf >= 0.90) return '#F39C12';  // Orange
    if (conf >= 0.80) return '#E67E22';  // Dark orange
    return '#E74C3C';                    // Red
}
```

### 4. Testing Data Access
```python
# Quick test of data loading
book_dir = Path.home() / 'Documents/book_scans' / 'modest-lovelace'
report = pd.read_csv(book_dir / 'labels' / 'report.csv')
print(f"Loaded {len(report)} pages")
print(f"Avg confidence: {report['avg_classification_confidence'].mean():.3f}")
```

---

## Next Steps

1. Implement stat cards first (simplest, establishes baseline)
2. Add confidence histogram (most valuable for quality assessment)
3. Add problem pages table (actionable)
4. Add timeline and chapter detection (structural insights)
5. Add visual viewer with overlays (verification tool)

All visualizations work with existing data in `report.csv` and `page_*.json` files.
